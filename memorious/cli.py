from memorious.logic.crawler import Crawler
import click
import logging
import sys
from tabulate import tabulate

from memorious import settings
from memorious.core import manager, init_memorious, is_sync_mode
from memorious.worker import get_worker

log = logging.getLogger(__name__)


@click.group()
@click.option("--debug/--no-debug", default=False, envvar="MEMORIOUS_DEBUG")
@click.option("--cache/--no-cache", default=True, envvar="MEMORIOUS_HTTP_CACHE")
@click.option(
    "--incremental/--non-incremental", default=True, envvar="MEMORIOUS_INCREMENTAL"
)
def cli(debug, cache, incremental):
    """Crawler framework for documents and structured scrapers."""
    settings.HTTP_CACHE = cache
    settings.INCREMENTAL = incremental
    settings.DEBUG = debug
    init_memorious()


def get_crawler(name):
    crawler = manager.get(name)
    if crawler is None:
        msg = "Crawler [%s] not found." % name
        raise click.BadParameter(msg, param=crawler)
    return crawler


@cli.command()
@click.argument("crawler")
def run(crawler):
    """Run a specified crawler."""
    crawler = get_crawler(crawler)
    crawler.run()
    if is_sync_mode():
        worker = get_worker()
        worker.sync()


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.option(
    "--src",
    required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Source file directory used by the crawler to add to path",
)
@click.option("--flush", is_flag=True, default=False)
def file_run(config_file, src=None, flush=False):
    # Use fakeredis:
    settings.sls.REDIS_URL = None
    # Disable timeouts:
    settings.CRAWLER_TIMEOUT = settings.CRAWLER_TIMEOUT * 1000

    crawler = Crawler(manager, config_file)
    manager.crawlers = {crawler.name: crawler}
    if flush:
        crawler.flush()
    if src:
        sys.path.insert(0, src)
    crawler.run()
    worker = get_worker()
    worker.get_stages = lambda: {stage.namespaced_name for stage in crawler}
    worker.sync()


@cli.command()
@click.argument("crawler")
def cancel(crawler):
    """Abort execution of a specified crawler."""
    crawler = get_crawler(crawler)
    crawler.cancel()


@cli.command()
@click.argument("crawler")
def flush(crawler):
    """Delete all data generated by a crawler."""
    crawler = get_crawler(crawler)
    crawler.flush()


@cli.command("flush-tags")
@click.argument("crawler")
def flush_tags(crawler):
    """Delete all tags generated by a crawler."""
    crawler = get_crawler(crawler)
    crawler.flush_tags()


@cli.command()
def process():
    """Start the queue and process tasks as they come. Blocks while waiting"""
    worker = get_worker()
    worker.run()


@cli.command("list")
def index():
    """List the available crawlers."""
    crawler_list = []
    for crawler in manager:
        is_due = "yes" if crawler.check_due() else "no"
        crawler_list.append(
            [
                crawler.name,
                crawler.description,
                crawler.schedule,
                is_due,
                crawler.pending,
            ]
        )
    headers = ["Name", "Description", "Schedule", "Due", "Pending"]
    print(tabulate(crawler_list, headers=headers))


@cli.command()
def killthekitten():
    """Completely kill redis contents."""
    from memorious.core import connect_redis

    conn = connect_redis()
    conn.flushall()


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
