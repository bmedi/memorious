import os
import io
import yaml
import logging
from datetime import timedelta, datetime
from importlib import import_module
from servicelayer.jobs import Dataset, Job

from memorious import settings
from memorious.core import conn
from memorious.model import Event, Crawl, Queue
from memorious.logic.stage import CrawlerStage

log = logging.getLogger(__name__)


class Crawler(object):
    """A processing graph that constitutes a crawler."""
    SCHEDULES = {
        'disabled': None,
        'hourly': timedelta(hours=1),
        'daily': timedelta(days=1),
        'weekly': timedelta(weeks=1),
        'monthly': timedelta(weeks=4)
    }

    def __init__(self, manager, source_file):
        self.manager = manager
        self.source_file = source_file
        with io.open(source_file, encoding='utf-8') as fh:
            self.config_yaml = fh.read()
            self.config = yaml.safe_load(self.config_yaml)

        self.name = os.path.basename(source_file)
        self.name = self.config.get('name', self.name)
        self.description = self.config.get('description', self.name)
        self.category = self.config.get('category', 'scrape')
        self.schedule = self.config.get('schedule', 'disabled')
        self.init_stage = self.config.get('init', 'init')
        self.delta = Crawler.SCHEDULES.get(self.schedule)
        self.delay = int(self.config.get('delay', 0))
        self.expire = int(self.config.get('expire', settings.EXPIRE)) * 84600
        self.stealthy = self.config.get('stealthy', False)
        self.queue = Dataset(conn, self.name)
        self.aggregator_config = self.config.get('aggregator', {})

        self.stages = {}
        for name, stage in self.config.get('pipeline', {}).items():
            self.stages[name] = CrawlerStage(self, name, stage)

    def check_due(self):
        """Check if the last execution of this crawler is older than
        the scheduled interval."""
        if self.is_running:
            return False
        if self.delta is None:
            return False
        last_run = self.last_run
        if last_run is None:
            return True
        now = datetime.utcnow()
        if now > last_run + self.delta:
            return True
        return False

    @property
    def aggregator_method(self):
        if self.aggregator_config:
            method = self.aggregator_config.get("method")
            if not method:
                return
            if ':' in method:
                package, method = method.rsplit(':', 1)
                module = import_module(package)
                return getattr(module, method)

    def aggregate(self, context):
        if self.aggregator_method:
            log.info("Running aggregator for %s" % self.name)
            params = self.aggregator_config.get("params", {})
            self.aggregator_method(context, params)

    def flush(self):
        """Delete all run-time data generated by this crawler."""
        self.queue.cancel()
        Event.delete(self)
        Crawl.flush(self)

    def flush_events(self):
        Event.delete(self)

    def cancel(self):
        Crawl.abort_all(self)
        self.queue.cancel()

    def run(self, incremental=None, run_id=None):
        """Queue the execution of a particular crawler."""
        state = {
            'crawler': self.name,
            'run_id': run_id or Job.random_id(),
            'incremental': settings.INCREMENTAL
        }
        if incremental is not None:
            state['incremental'] = incremental

        # Cancel previous runs:
        self.cancel()
        # Flush out previous events:
        Event.delete(self)
        Queue.queue(self.init_stage, state, {})

    @property
    def is_running(self):
        """Is the crawler currently running?"""
        for job in self.queue.get_jobs():
            if not job.is_done():
                return True
        return False

    @property
    def last_run(self):
        return Crawl.last_run(self)

    @property
    def op_count(self):
        """Total operations performed for this crawler"""
        return Crawl.op_count(self)

    @property
    def runs(self):
        return Crawl.runs(self)

    @property
    def latest_runid(self):
        return Crawl.latest_runid(self)

    @property
    def pending(self):
        status = self.queue.get_status()
        return status.get('pending')

    def get(self, name):
        return self.stages.get(name)

    def __str__(self):
        return self.name

    def __iter__(self):
        return iter(self.stages.values())

    def __repr__(self):
        return '<Crawler(%s)>' % self.name
