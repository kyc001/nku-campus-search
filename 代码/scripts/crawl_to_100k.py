from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nku_search.crawler import crawl_from_file
from nku_search.frontier import expand_frontier


if __name__ == "__main__":
    expand_frontier(limit=120_000)
    crawl_from_file(
        Path("data/seeds.txt"),
        max_pages=130_000,
        delay=0.12,
        flush_every=200,
        workers=96,
        timeout=2.5,
        crawl_attachments=False,
        max_host_active=3,
    )
