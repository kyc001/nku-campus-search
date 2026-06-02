from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import SNAPSHOT_DIR, ensure_dirs


def url_id(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def snapshot_path(url: str, suffix: str = ".html.gz") -> Path:
    ensure_dirs()
    return SNAPSHOT_DIR / f"{url_id(url)}{suffix}"


def save_html_snapshot(url: str, html: str) -> str:
    path = snapshot_path(url)
    with gzip.open(path, "wt", encoding="utf-8", errors="replace", compresslevel=1) as f:
        f.write(html)
    return str(path)


def load_html_snapshot(path: str | Path) -> str:
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()
    return path.read_text(encoding="utf-8", errors="replace")


def render_snapshot(snapshot_file: str | Path, url: str, crawled_at: str) -> str:
    html = load_html_snapshot(snapshot_file)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["a", "link", "script", "img"], href=True):
        tag["href"] = urljoin(url, tag["href"])
    for tag in soup.find_all(["script", "img"], src=True):
        tag["src"] = urljoin(url, tag["src"])
    banner = soup.new_tag("div")
    banner["style"] = (
        "position:sticky;top:0;z-index:9999;padding:10px 16px;"
        "background:#fff7d1;border-bottom:1px solid #d3a900;"
        "font:14px/1.5 system-ui, sans-serif;color:#3c3000;"
    )
    banner.string = f"网页快照 - 抓取时间: {crawled_at} - 原始 URL: {url}"
    if soup.body:
        soup.body.insert(0, banner)
    else:
        soup.insert(0, banner)
    return str(soup)
