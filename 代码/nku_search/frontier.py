from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import ALLOWED_DOMAIN_SUFFIX, DOCUMENTS_PATH, FRONTIER_PATH, SEEDS_PATH, ensure_dirs
from .crawler import looks_like_noise_url, looks_like_static_asset
from .parser import clean_url

CORE_SEED_URLS = [
    "https://www.nankai.edu.cn/",
    "https://news.nankai.edu.cn/",
    "https://jwc.nankai.edu.cn/",
    "https://graduate.nankai.edu.cn/",
    "https://yzb.nankai.edu.cn/",
    "https://zsb.nankai.edu.cn/",
    "https://job.nankai.edu.cn/",
    "https://career.nankai.edu.cn/",
    "https://lib.nankai.edu.cn/",
    "https://cc.nankai.edu.cn/",
    "https://cs.nankai.edu.cn/",
    "https://ai.nankai.edu.cn/",
    "https://software.nankai.edu.cn/",
    "https://math.nankai.edu.cn/",
    "https://physics.nankai.edu.cn/",
    "https://chem.nankai.edu.cn/",
    "https://sky.nankai.edu.cn/",
    "https://bs.nankai.edu.cn/",
    "https://economics.nankai.edu.cn/",
    "https://finance.nankai.edu.cn/",
    "https://stat.nankai.edu.cn/",
    "https://mse.nankai.edu.cn/",
    "https://pharmacy.nankai.edu.cn/",
    "https://env.nankai.edu.cn/",
    "https://history.nankai.edu.cn/",
    "https://wxy.nankai.edu.cn/",
    "https://sfs.nankai.edu.cn/",
    "https://law.nankai.edu.cn/",
    "https://foreign.nankai.edu.cn/",
    "https://international.nankai.edu.cn/",
    "https://rsc.nankai.edu.cn/",
    "https://xxgk.nankai.edu.cn/",
]
TARGET_HOST_HINTS = {
    "jwc.nankai.edu.cn": 6500,
    "graduate.nankai.edu.cn": 5200,
    "yzb.nankai.edu.cn": 3600,
    "zsb.nankai.edu.cn": 3200,
    "job.nankai.edu.cn": 3200,
    "career.nankai.edu.cn": 5200,
    "lib.nankai.edu.cn": 3600,
    "cc.nankai.edu.cn": 3200,
    "cs.nankai.edu.cn": 3600,
    "ai.nankai.edu.cn": 3600,
    "software.nankai.edu.cn": 2800,
    "news.nankai.edu.cn": 6800,
    "www.nankai.edu.cn": 2400,
    "math.nankai.edu.cn": 2800,
    "physics.nankai.edu.cn": 2600,
    "chem.nankai.edu.cn": 3000,
    "sky.nankai.edu.cn": 2600,
    "bs.nankai.edu.cn": 2600,
    "economics.nankai.edu.cn": 2400,
    "finance.nankai.edu.cn": 2200,
    "stat.nankai.edu.cn": 2200,
    "mse.nankai.edu.cn": 2400,
    "pharmacy.nankai.edu.cn": 2200,
    "env.nankai.edu.cn": 2200,
    "history.nankai.edu.cn": 2200,
    "wxy.nankai.edu.cn": 2200,
    "sfs.nankai.edu.cn": 2200,
    "law.nankai.edu.cn": 2400,
    "foreign.nankai.edu.cn": 1800,
    "international.nankai.edu.cn": 2600,
    "rsc.nankai.edu.cn": 2200,
    "xxgk.nankai.edu.cn": 2200,
}
LOW_PRIORITY_HOSTS = {
    "ochem.nankai.edu.cn",
    "chinareal.nankai.edu.cn",
    "nkup.nankai.edu.cn",
    "weekly.nankai.edu.cn",
    "webplus3.nankai.edu.cn",
}
LOW_PRIORITY_HOST_MARKERS = (
    ".webplus",
    "weekly.",
)
ARTICLE_PATH_RE = re.compile(
    r"(?:/20\d{2}/\d{4}/c\d+a\d+/page\.htm$|/info/\d+/\d+\.htm$|"
    r"/(?:content|detail|view|show)(?:/id)?/\d+|/system/20\d{2}/\d{2}/\d{2}/\d+\.(?:s?html?|htm)$)",
    re.I,
)
LIST_PATH_RE = re.compile(r"(?:^|/)(?:list\d*|index|main)\.(?:psp|jsp|s?html?|htm)$", re.I)
DOWNLOAD_PATH_MARKERS = (
    "/download",
    "/_upload/",
    "/_content/download",
    "/system/resource/",
    "/system/getfile",
    "/getfile.asp",
    "/Download.asp",
)
TRAILING_PUNCTUATION = ("\u3002", "\uff0c", "\uff1b", "\uff1a", "\uff01", "\uff1f")


def allowed_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "nankai.edu.cn" or host.endswith(ALLOWED_DOMAIN_SUFFIX)


def safe_clean_url(url: str) -> str:
    try:
        clean = clean_url(url.strip())
    except (TypeError, ValueError):
        return ""
    if _looks_like_malformed_url(clean):
        return ""
    if not allowed_host(clean) or looks_like_static_asset(clean) or looks_like_noise_url(clean):
        return ""
    return clean


def _looks_like_malformed_url(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc:
        return True
    decoded_path_query = unquote(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
    lowered_decoded = decoded_path_query.lower()
    if "http://" in lowered_decoded or "https://" in lowered_decoded:
        return True
    if any(ch.isspace() for ch in decoded_path_query):
        return True
    if parsed.path.lower().endswith(("%e3%80%82", "%ef%bc%8c", "%ef%bc%9b", "%ef%bc%9a")):
        return True
    if decoded_path_query.endswith(TRAILING_PUNCTUATION):
        return True
    if len(url) > 260 and "%" in url:
        return True
    return False


def read_frontier(path: Path = FRONTIER_PATH) -> list[str]:
    if not path.exists():
        return []
    urls = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = safe_clean_url(line)
        if clean:
            urls.append(clean)
    return urls


def write_frontier(urls: list[str], path: Path = FRONTIER_PATH) -> None:
    ensure_dirs()
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")


def scan_known_documents(path: Path = DOCUMENTS_PATH) -> tuple[set[str], Counter[str]]:
    seen: set[str] = set()
    hosts: Counter[str] = Counter()
    if not path.exists():
        return seen, hosts
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            clean = safe_clean_url(row.get("url", ""))
            if not clean:
                continue
            seen.add(clean)
            hosts[urlparse(clean).netloc.lower()] += 1
    return seen, hosts


def known_urls(fast: bool = False) -> tuple[set[str], list[str], Counter[str]]:
    seen, hosts = (set(), Counter()) if fast else scan_known_documents()
    if SEEDS_PATH.exists():
        seen.update(safe_clean_url(line) for line in SEEDS_PATH.read_text(encoding="utf-8").splitlines())
    seen.discard("")
    frontier = read_frontier()
    return seen, frontier, hosts


def _add(candidate: str, candidates: list[str], queued: set[str], seen: set[str], limit: int) -> None:
    if len(candidates) >= limit:
        return
    clean = safe_clean_url(candidate)
    if clean and clean not in queued and clean not in seen:
        queued.add(clean)
        candidates.append(clean)


def _host_priority(host: str, current_counts: Counter[str], queued_counts: Counter[str]) -> tuple[int, int, str]:
    target = TARGET_HOST_HINTS.get(host, 900)
    host_tier = _host_quality_tier(host)
    deficit = max(target - current_counts.get(host, 0), 0)
    queued_penalty = queued_counts.get(host, 0)
    return host_tier, deficit, -queued_penalty, host


def _host_quality_tier(host: str) -> int:
    if host in TARGET_HOST_HINTS:
        return 3
    if host in LOW_PRIORITY_HOSTS or any(marker in host for marker in LOW_PRIORITY_HOST_MARKERS):
        return -2
    return 0


def _url_quality_score(url: str) -> tuple[int, int, int, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    path_lower = path.lower()
    query_lower = parsed.query.lower()
    score = _host_quality_tier(host) * 20
    if ARTICLE_PATH_RE.search(path):
        score += 14
    if "/info/" in path_lower:
        score += 6
    if any(marker in path_lower for marker in ("/content/", "/detail/", "/view/", "/show/")):
        score += 6
    if "/system/" in path_lower and re.search(r"/20\d{2}/", path_lower):
        score += 5
    if LIST_PATH_RE.search(path):
        score += 3
    if path_lower in {"", "/", "/index.htm", "/main.htm", "/list.htm", "/index/list.htm"}:
        score += 2
    if "_redirect" in path_lower and "articleid=" in query_lower:
        score += 8
    if parsed.query and re.search(r"(?:^|[?&;])(?:id|articleid|wbnewsid)=", "?" + parsed.query, flags=re.I):
        score += 3
    if any(marker.lower() in path_lower for marker in DOWNLOAD_PATH_MARKERS):
        score -= 10
    if path_lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
        score -= 8
    if len(path) > 120:
        score -= 4
    return score, -len(path), -len(parsed.query), url


def _host_round_chunks(host: str) -> int:
    tier = _host_quality_tier(host)
    if tier >= 3:
        return 6
    if tier < 0:
        return 1
    return 1


def rebalance_frontier(urls: list[str], current_counts: Counter[str] | None = None, per_host_round: int = 80) -> list[str]:
    current_counts = current_counts or Counter()
    buckets: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for url in urls:
        clean = safe_clean_url(url)
        if clean and clean not in seen:
            seen.add(clean)
            buckets[urlparse(clean).netloc.lower()].append(clean)
    for host, items in buckets.items():
        items.sort(key=_url_quality_score, reverse=True)
    queued_counts = Counter({host: len(items) for host, items in buckets.items()})
    hosts = sorted(buckets, key=lambda host: _host_priority(host, current_counts, queued_counts), reverse=True)
    balanced: list[str] = []
    while hosts:
        next_hosts = []
        for host in hosts:
            for _ in range(_host_round_chunks(host)):
                chunk = buckets[host][:per_host_round]
                balanced.extend(chunk)
                del buckets[host][:per_host_round]
                if not buckets[host]:
                    break
            if buckets[host]:
                next_hosts.append(host)
        hosts = sorted(next_hosts, key=lambda host: _host_priority(host, current_counts, queued_counts), reverse=True)
    return balanced


def write_seed_plan(path: Path = SEEDS_PATH) -> None:
    existing = []
    if path.exists():
        existing = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    merged = []
    seen = set()
    for url in [*existing, *CORE_SEED_URLS]:
        clean = safe_clean_url(url)
        if clean and clean not in seen:
            seen.add(clean)
            merged.append(clean)
    path.write_text("\n".join(merged) + "\n", encoding="utf-8")


def expand_frontier(limit: int = 100_000, fast: bool = False) -> int:
    seen, frontier, current_counts = known_urls(fast=fast)
    queued = set(frontier)
    candidates: list[str] = []
    all_known = list(seen | queued)
    write_seed_plan()

    hosts = sorted(
        {urlparse(url).netloc.lower() for url in [*all_known, *CORE_SEED_URLS] if url},
        key=lambda host: _host_priority(host, current_counts, Counter()),
        reverse=True,
    )
    for host in hosts:
        for path in ["", "/", "/index.htm", "/main.htm", "/list.htm", "/index/list.htm"]:
            _add(f"https://{host}{path}", candidates, queued, seen, limit)
        if len(candidates) >= limit:
            break

    numbered_lists: dict[tuple[str, str], int] = {}
    info_ids: dict[tuple[str, str], list[int]] = defaultdict(list)
    content_ids: dict[tuple[str, str], list[int]] = defaultdict(list)
    webplus_ids: dict[tuple[str, str, str], list[int]] = defaultdict(list)

    for url in all_known:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path

        m = re.match(r"(.*/)(\d{1,4})\.htm$", path)
        if m:
            prefix, number = m.group(1), int(m.group(2))
            if number <= 1000:
                key = (host, prefix)
                numbered_lists[key] = max(numbered_lists.get(key, 0), number)

        m = re.match(r"/info/(\d+)/(\d+)\.htm$", path)
        if m:
            info_ids[(host, m.group(1))].append(int(m.group(2)))

        m = re.search(r"(/(?:content|detail|view|show)(?:/id)?/)(\d+)", path)
        if m:
            content_ids[(host, m.group(1))].append(int(m.group(2)))

        m = re.search(r"/c(\d+)a(\d+)/page\.htm$", path)
        if m:
            prefix = path.split("/c", 1)[0]
            webplus_ids[(host, prefix, m.group(1))].append(int(m.group(2)))

    for (host, prefix), max_page in sorted(
        numbered_lists.items(),
        key=lambda item: (
            _host_priority(item[0][0], current_counts, Counter()),
            _url_quality_score(f"https://{item[0][0]}{item[0][1]}{item[1]}.htm"),
            item[1],
        ),
        reverse=True,
    ):
        if len(candidates) >= limit:
            break
        ceiling = min(max(max_page + 80, 200), 800)
        for page in range(1, ceiling + 1):
            _add(f"https://{host}{prefix}{page}.htm", candidates, queued, seen, limit)
            if len(candidates) >= limit:
                break

    for (host, cat), ids in sorted(
        info_ids.items(),
        key=lambda item: (
            _host_priority(item[0][0], current_counts, Counter()),
            len(item[1]),
        ),
        reverse=True,
    ):
        if len(candidates) >= limit:
            break
        lo = max(min(ids) - 800, 1)
        hi = max(ids) + 800
        span = min(hi - lo + 1, 3000)
        for doc_id in range(lo, lo + span):
            _add(f"https://{host}/info/{cat}/{doc_id}.htm", candidates, queued, seen, limit)
            if len(candidates) >= limit:
                break

    for (host, prefix), ids in sorted(
        content_ids.items(),
        key=lambda item: (
            _host_priority(item[0][0], current_counts, Counter()),
            len(item[1]),
        ),
        reverse=True,
    ):
        if len(candidates) >= limit:
            break
        lo = max(min(ids) - 800, 1)
        hi = max(ids) + 800
        span = min(hi - lo + 1, 3000)
        for doc_id in range(lo, lo + span):
            _add(f"https://{host}{prefix}{doc_id}", candidates, queued, seen, limit)
            if len(candidates) >= limit:
                break

    for (host, prefix, cat), ids in sorted(
        webplus_ids.items(),
        key=lambda item: (
            _host_priority(item[0][0], current_counts, Counter()),
            len(item[1]),
        ),
        reverse=True,
    ):
        if len(candidates) >= limit:
            break
        lo = max(min(ids) - 800, 1)
        hi = max(ids) + 800
        span = min(hi - lo + 1, 3000)
        for article_id in range(lo, lo + span):
            _add(f"https://{host}{prefix}/c{cat}a{article_id}/page.htm", candidates, queued, seen, limit)
            if len(candidates) >= limit:
                break

    new_frontier = rebalance_frontier(frontier + candidates, current_counts=current_counts)
    write_frontier(new_frontier)
    return len(candidates)
