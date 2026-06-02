from __future__ import annotations

import hashlib
import os
import queue
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .config import (
    ALLOWED_DOMAIN_SUFFIX,
    ATTACHMENT_DIR,
    DEFAULT_USER_AGENT,
    DOCUMENTS_PATH,
    FRONTIER_PATH,
    LINKS_PATH,
    ensure_dirs,
)
from .models import Document, utc_now_iso
from .parser import clean_url, guess_doc_type, looks_like_attachment, parse_attachment, parse_html, safe_filename
from .snapshot import save_html_snapshot, url_id
from .storage import append_documents, load_document_refs


SKIP_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".ico",
    ".svg",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".json",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".bz2",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}
SKIP_URL_MARKERS = (
    "/login",
    "/cas/",
    "caslogin",
    "do_caslogin",
    "oauth",
    "sso",
    "logout",
    "returnurl=",
    "redirect_uri=",
    "service=",
    "next=",
)


def looks_like_static_asset(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in SKIP_SUFFIXES


def looks_like_noise_url(url: str) -> bool:
    lowered = url.lower()
    host = urlparse(url).netloc.lower()
    if host in {"iam.nankai.edu.cn", "authserver.nankai.edu.cn", "ids.nankai.edu.cn"}:
        return True
    return any(marker in lowered for marker in SKIP_URL_MARKERS)


class PoliteCrawler:
    def __init__(
        self,
        seeds: list[str],
        max_pages: int = 1000,
        delay: float = 1.0,
        flush_every: int = 50,
        workers: int = 8,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 10.0,
        max_frontier: int = 500_000,
        crawl_attachments: bool = True,
        max_host_active: int = 1,
    ):
        self.seeds = [url for seed in seeds if (url := self.safe_clean_url(seed))]
        self.max_pages = max_pages
        self.delay = delay
        self.flush_every = max(flush_every, 1)
        self.workers = max(workers, 1)
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_frontier = max(max_frontier, max_pages * 2)
        self.crawl_attachments = crawl_attachments
        self.max_host_active = max(max_host_active, 1)

        self.robot_cache: dict[str, RobotFileParser] = {}
        self.sitemap_seen: set[str] = set()
        self.robot_lock = threading.Lock()
        self.host_locks: dict[str, threading.Lock] = {}
        self.host_locks_lock = threading.Lock()
        self.last_fetch: dict[str, float] = {}
        self.active_hosts: dict[str, int] = {}

        self.frontier: queue.Queue[str] = queue.Queue()
        self.seen_lock = threading.Lock()
        self.seen_urls: set[str] = set()
        self.done_ids: set[str] = set()

        self.total_lock = threading.Lock()
        self.total_docs = 0
        self.new_docs = 0
        self.skipped = 0
        self.failed = 0
        self.active = 0

        self.pending_lock = threading.Lock()
        self.flush_lock = threading.Lock()
        self.frontier_save_lock = threading.Lock()
        self.pending_documents: list[Document] = []
        self.pending_links: list[tuple[str, str, str]] = []

        self.stop_event = threading.Event()
        self.started_at = time.time()
        self._load_existing_state()
        self._load_frontier()

    def safe_clean_url(self, url: str) -> str:
        try:
            return clean_url(url.strip())
        except (TypeError, ValueError):
            return ""

    def allowed_host(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host == "nankai.edu.cn" or host.endswith(ALLOWED_DOMAIN_SUFFIX)

    def _load_existing_state(self) -> None:
        doc_ids, urls, _ = load_document_refs(DOCUMENTS_PATH)
        for url in urls:
            clean = self.safe_clean_url(url)
            if clean:
                self.seen_urls.add(clean)
        self.done_ids.update(doc_ids)
        self.total_docs = len(doc_ids)

    def _frontier_file_urls(self) -> list[str]:
        if not FRONTIER_PATH.exists():
            return []
        return [
            line.strip()
            for line in FRONTIER_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]

    def _load_frontier(self) -> None:
        candidates = self._frontier_file_urls()
        if not candidates:
            _, _, outlinks = load_document_refs(DOCUMENTS_PATH, include_outlinks=True)
            candidates.extend(self.seeds)
            candidates.extend(outlinks)
        for url in candidates:
            self.enqueue(url)

    def save_frontier(self) -> None:
        ensure_dirs()
        with self.frontier.mutex:
            pending = list(self.frontier.queue)[: self.max_frontier]
        with self.frontier_save_lock:
            tmp = FRONTIER_PATH.with_suffix(FRONTIER_PATH.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
            tmp.write_text("\n".join(pending) + ("\n" if pending else ""), encoding="utf-8", errors="replace")
            for attempt in range(10):
                try:
                    tmp.replace(FRONTIER_PATH)
                    return
                except PermissionError:
                    time.sleep(0.2 * (attempt + 1))
            try:
                tmp.replace(FRONTIER_PATH)
            except PermissionError:
                print(f"[crawl] warning: frontier save skipped after repeated file locks: {tmp}", flush=True)

    def enqueue(self, url: str) -> bool:
        clean = self.safe_clean_url(url)
        if not clean or not self.allowed_host(clean):
            return False
        if looks_like_static_asset(clean) or looks_like_noise_url(clean):
            return False
        if not self.crawl_attachments and looks_like_attachment(clean):
            return False
        with self.seen_lock:
            if clean in self.seen_urls:
                return False
            self.seen_urls.add(clean)
        self.frontier.put(clean)
        return True

    def robot_for(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self.robot_lock:
            if base in self.robot_cache:
                return self.robot_cache[base]
        rp = RobotFileParser()
        robots_url = f"{base}/robots.txt"
        rp.set_url(robots_url)
        text = ""
        try:
            response = requests.get(robots_url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
            if response.status_code < 400:
                text = response.text
                rp.parse(text.splitlines())
            else:
                rp.parse([])
        except requests.RequestException:
            rp.parse([])
        with self.robot_lock:
            cached = self.robot_cache.get(base)
            if cached is not None:
                return cached
            self.robot_cache[base] = rp
        self.discover_sitemaps(base, text)
        return rp

    def discover_sitemaps(self, base: str, robots_text: str = "") -> None:
        candidates = []
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                candidates.append(line.split(":", 1)[1].strip())
        candidates.extend([f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"])
        for sitemap_url in candidates:
            clean = self.safe_clean_url(sitemap_url)
            if not clean or not self.allowed_host(clean):
                continue
            with self.robot_lock:
                if clean in self.sitemap_seen:
                    continue
                self.sitemap_seen.add(clean)
            self.load_sitemap(clean)

    def load_sitemap(self, sitemap_url: str, depth: int = 0) -> None:
        if depth > 2:
            return
        try:
            response = requests.get(sitemap_url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
            if response.status_code >= 400:
                return
            text = response.text
        except requests.RequestException:
            return
        urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text, flags=re.I)
        added = 0
        for item in urls[:50_000]:
            clean = self.safe_clean_url(item)
            if not clean or not self.allowed_host(clean):
                continue
            if clean.endswith(".xml") and depth < 2:
                with self.robot_lock:
                    if clean in self.sitemap_seen:
                        continue
                    self.sitemap_seen.add(clean)
                self.load_sitemap(clean, depth + 1)
            elif self.enqueue(clean):
                added += 1
        if added:
            print(f"[crawl] sitemap added {added} urls from {sitemap_url}", flush=True)

    def can_fetch(self, url: str) -> bool:
        if not self.allowed_host(url):
            return False
        return self.robot_for(url).can_fetch(self.user_agent, url)

    def host_lock(self, host: str) -> threading.Lock:
        with self.host_locks_lock:
            lock = self.host_locks.get(host)
            if lock is None:
                lock = threading.Lock()
                self.host_locks[host] = lock
            return lock

    def throttle(self, host: str) -> None:
        lock = self.host_lock(host)
        with lock:
            now = time.time()
            wait = self.delay - (now - self.last_fetch.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self.last_fetch[host] = time.time()

    def fetch(self, session: requests.Session, url: str) -> requests.Response | None:
        host = urlparse(url).netloc.lower()
        self.throttle(host)
        try:
            response = session.get(url, timeout=self.timeout, allow_redirects=True, stream=True)
            if response.status_code >= 400:
                response.close()
                return None
            final_url = response.url
            content_type = response.headers.get("Content-Type", "").lower()
            if not self.allowed_content_type(final_url, content_type):
                response.close()
                return None
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > 30 * 1024 * 1024:
                response.close()
                return None
            max_bytes = 10 * 1024 * 1024 if looks_like_attachment(final_url) else 2 * 1024 * 1024
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > max_bytes:
                    response.close()
                    return None
            response._content = bytes(body)
            response._content_consumed = True
            response.close()
            return response
        except (requests.RequestException, ValueError):
            return None

    def allowed_content_type(self, url: str, content_type: str) -> bool:
        if looks_like_attachment(url):
            return True
        if not content_type:
            return True
        allowed_markers = (
            "text/html",
            "text/plain",
            "application/xhtml",
            "application/xml",
            "text/xml",
            "pdf",
            "word",
            "excel",
            "spreadsheet",
            "msword",
            "openxmlformats",
        )
        blocked_markers = (
            "image/",
            "video/",
            "audio/",
            "font/",
            "zip",
            "rar",
            "7z",
            "tar",
            "gzip",
            "javascript",
            "css",
            "json",
        )
        if any(marker in content_type for marker in allowed_markers):
            return True
        return not any(marker in content_type for marker in blocked_markers)

    def crawl(self) -> list[Document]:
        ensure_dirs()
        print(
            f"[crawl] start total={self.total_docs} target={self.max_pages} "
            f"frontier={self.frontier.qsize()} workers={self.workers} delay={self.delay}",
            flush=True,
        )
        threads = [
            threading.Thread(target=self.worker, name=f"crawler-{idx + 1}", daemon=True)
            for idx in range(self.workers)
        ]
        for thread in threads:
            thread.start()
        try:
            self.monitor()
        except KeyboardInterrupt:
            print("[crawl] interrupted, flushing pending data...", flush=True)
            self.stop_event.set()
        finally:
            self.stop_event.set()
            for thread in threads:
                thread.join(timeout=5)
            self.flush(force=True)
            self.save_frontier()
        return []

    def monitor(self) -> None:
        last_total = self.total_docs
        last_time = time.time()
        while not self.stop_event.is_set():
            time.sleep(5)
            with self.total_lock:
                total = self.total_docs
                active = self.active
                failed = self.failed
                skipped = self.skipped
            if total >= self.max_pages:
                self.stop_event.set()
                break
            if self.frontier.empty() and active == 0:
                self.stop_event.set()
                break
            now = time.time()
            if now - last_time >= 30:
                delta = total - last_total
                rate = delta / max(now - last_time, 1)
                print(
                    f"[crawl] progress total={total} new={self.new_docs} "
                    f"frontier={self.frontier.qsize()} active={active} "
                    f"rate={rate:.2f}/s failed={failed} skipped={skipped}",
                    flush=True,
                )
                self.save_frontier()
                last_total = total
                last_time = now

    def worker(self) -> None:
        session = requests.Session()
        session.headers.update({"User-Agent": self.user_agent})
        while not self.stop_event.is_set():
            with self.total_lock:
                if self.total_docs >= self.max_pages:
                    self.stop_event.set()
                    return
            url = self.next_url(timeout=1.0)
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            with self.total_lock:
                self.active += 1
            try:
                try:
                    self.process_url(session, url)
                except Exception as exc:
                    with self.total_lock:
                        self.failed += 1
                    print(f"[crawl] worker error {type(exc).__name__}: {url}", flush=True)
            finally:
                self.release_host(host)
                with self.total_lock:
                    self.active -= 1
                self.frontier.task_done()

    def next_url(self, timeout: float = 1.0) -> str:
        deadline = time.time() + timeout
        while not self.stop_event.is_set():
            with self.frontier.mutex:
                if self.frontier.queue:
                    fallback_idx = 0
                    chosen_idx = -1
                    chosen_host = ""
                    for idx, candidate in enumerate(self.frontier.queue):
                        host = urlparse(candidate).netloc.lower()
                        active = self.active_hosts.get(host, 0)
                        if active < self.max_host_active and not looks_like_attachment(candidate):
                            chosen_idx = idx
                            chosen_host = host
                            break
                    if chosen_idx < 0:
                        for idx, candidate in enumerate(self.frontier.queue):
                            host = urlparse(candidate).netloc.lower()
                            active = self.active_hosts.get(host, 0)
                            if active < self.max_host_active:
                                chosen_idx = idx
                                chosen_host = host
                                break
                    if chosen_idx < 0 and time.time() >= deadline:
                        candidate = self.frontier.queue[fallback_idx]
                        chosen_idx = fallback_idx
                        chosen_host = urlparse(candidate).netloc.lower()
                    if chosen_idx >= 0:
                        url = self.frontier.queue[chosen_idx]
                        del self.frontier.queue[chosen_idx]
                        self.active_hosts[chosen_host] = self.active_hosts.get(chosen_host, 0) + 1
                        return url
            if time.time() >= deadline:
                return ""
            time.sleep(0.05)
        return ""

    def release_host(self, host: str) -> None:
        with self.frontier.mutex:
            active = self.active_hosts.get(host, 0)
            if active <= 1:
                self.active_hosts.pop(host, None)
            else:
                self.active_hosts[host] = active - 1

    def process_url(self, session: requests.Session, url: str) -> None:
        if not self.crawl_attachments and looks_like_attachment(url):
            with self.total_lock:
                self.skipped += 1
            return
        if not self.can_fetch(url):
            with self.total_lock:
                self.skipped += 1
            return
        response = self.fetch(session, url)
        if not response:
            with self.total_lock:
                self.failed += 1
            return
        final_url = self.safe_clean_url(response.url)
        if not final_url or not self.allowed_host(final_url):
            with self.total_lock:
                self.skipped += 1
            return
        doc_type = guess_doc_type(final_url, response.headers.get("Content-Type", ""))
        if doc_type == "html":
            self.process_html(final_url, response)
        else:
            if not self.crawl_attachments:
                with self.total_lock:
                    self.skipped += 1
                return
            doc = self._save_attachment(final_url, response, doc_type)
            if doc:
                self.add_document(doc)

    def process_html(self, final_url: str, response: requests.Response) -> None:
        text = response.text
        title, body, links = parse_html(text, final_url)
        outlinks: list[str] = []
        link_rows: list[tuple[str, str, str]] = []
        for out_url, anchor in links:
            if not self.allowed_host(out_url):
                continue
            outlinks.append(out_url)
            link_rows.append((final_url, out_url, anchor))
            is_attachment = looks_like_attachment(out_url)
            if (is_attachment and self.crawl_attachments) or (
                not is_attachment and self.frontier.qsize() < self.max_frontier
            ):
                self.enqueue(out_url)
        snapshot = save_html_snapshot(final_url, text)
        self.add_links(link_rows)
        self.add_document(
            Document(
                id=url_id(final_url),
                url=final_url,
                title=title or final_url,
                body=body,
                host=urlparse(final_url).netloc.lower(),
                doc_type="html",
                outlinks=outlinks,
                crawled_at=utc_now_iso(),
                last_modified=response.headers.get("Last-Modified", ""),
                snapshot_path=snapshot,
                tags=infer_tags(title + " " + body),
            )
        )

    def add_document(self, doc: Document) -> None:
        with self.total_lock:
            if doc.id in self.done_ids:
                return
            self.done_ids.add(doc.id)
            self.total_docs += 1
            self.new_docs += 1
        should_flush = False
        with self.pending_lock:
            self.pending_documents.append(doc)
            should_flush = len(self.pending_documents) >= self.flush_every
        if should_flush:
            self.flush()

    def add_links(self, links: list[tuple[str, str, str]]) -> None:
        if not links:
            return
        with self.pending_lock:
            self.pending_links.extend(links)

    def flush(self, force: bool = False) -> None:
        if not force and len(self.pending_documents) < self.flush_every:
            return
        with self.flush_lock:
            with self.pending_lock:
                docs = self.pending_documents
                links = self.pending_links
                self.pending_documents = []
                self.pending_links = []
            if docs:
                append_documents(docs, DOCUMENTS_PATH)
            if links:
                self.save_links(links)
            if docs or links or force:
                self.save_frontier()
            if docs:
                print(
                    f"[crawl] saved {len(docs)} docs, total={self.total_docs}, "
                    f"new={self.new_docs}, frontier={self.frontier.qsize()}",
                    flush=True,
                )

    def _save_attachment(self, url: str, response: requests.Response, doc_type: str) -> Document | None:
        suffix = f".{doc_type}"
        name = safe_filename(Path(urlparse(url).path).name or hashlib.md5(url.encode()).hexdigest())
        if not name.lower().endswith(suffix):
            name += suffix
        path = ATTACHMENT_DIR / name
        try:
            path.write_bytes(response.content)
            body = parse_attachment(path, doc_type)
        except Exception:
            return None
        return Document(
            id=url_id(url),
            url=url,
            title=Path(name).stem,
            body=body,
            host=urlparse(url).netloc.lower(),
            doc_type=doc_type,
            attachment_url=url,
            attachment_path=str(path),
            file_size=path.stat().st_size,
            crawled_at=utc_now_iso(),
            last_modified=response.headers.get("Last-Modified", ""),
            tags=infer_tags(body),
        )

    def save_links(self, links: list[tuple[str, str, str]]) -> None:
        if not links:
            return
        with LINKS_PATH.open("a", encoding="utf-8", errors="replace") as f:
            for src, dst, anchor in links:
                f.write(f"{src}\t{dst}\t{anchor}\n")


def infer_tags(text: str) -> list[str]:
    mapping = {
        "新闻": ["新闻", "报道", "新闻网"],
        "教务": ["教务", "选课", "课程", "考试", "培养"],
        "学术": ["学术", "讲座", "论文", "研究", "实验室"],
        "招聘": ["招聘", "就业", "实习", "宣讲"],
        "文体": ["体育", "艺术", "社团", "动漫", "文化"],
        "院系": ["学院", "系", "教师", "专业"],
        "图书馆": ["图书馆", "数据库", "资源"],
        "计算机": ["计算机", "软件", "人工智能", "网络", "数据库"],
    }
    tags = [tag for tag, words in mapping.items() if any(word in text for word in words)]
    return tags or ["南开"]


def crawl_from_file(
    seed_file: Path,
    max_pages: int,
    delay: float,
    flush_every: int = 50,
    workers: int = 8,
    timeout: float = 10.0,
    crawl_attachments: bool = True,
    max_host_active: int = 1,
) -> list[Document]:
    seeds = [
        line.strip()
        for line in seed_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return PoliteCrawler(
        seeds=seeds,
        max_pages=max_pages,
        delay=delay,
        flush_every=flush_every,
        workers=workers,
        timeout=timeout,
        crawl_attachments=crawl_attachments,
        max_host_active=max_host_active,
    ).crawl()
