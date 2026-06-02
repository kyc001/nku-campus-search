from pathlib import Path
from functools import lru_cache
import os

PACKAGE_ROOT = Path(__file__).resolve().parent
CODE_ROOT = PACKAGE_ROOT.parent
DATA_DIR = CODE_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
ATTACHMENT_DIR = DATA_DIR / "attachments"
DOCUMENTS_PATH = DATA_DIR / "documents.jsonl"
INDEX_PATH = DATA_DIR / "search_index.json"
LINKS_PATH = DATA_DIR / "links.tsv"
FRONTIER_PATH = DATA_DIR / "frontier.txt"
DB_PATH = DATA_DIR / "nku_search.sqlite3"
SEEDS_PATH = DATA_DIR / "seeds.txt"
CUSTOM_DICT_PATH = DATA_DIR / "nankai_terms.txt"

DEFAULT_USER_AGENT = "NKU-IR-HW4-Crawler (+mailto:keyunchao001@gmail.com)"
ALLOWED_DOMAIN_SUFFIX = ".nankai.edu.cn"
ES_URL = os.environ.get("NKU_SEARCH_ES_URL", "http://127.0.0.1:9200")
ES_INDEX = os.environ.get("NKU_SEARCH_ES_INDEX", "nku_search_pages")
ES_TIMEOUT = float(os.environ.get("NKU_SEARCH_ES_TIMEOUT", "3.0"))
NKU_SEARCH_BACKEND_DEFAULT = "auto"
NKU_SEARCH_BACKEND = os.environ.get("NKU_SEARCH_BACKEND", NKU_SEARCH_BACKEND_DEFAULT)

INTERESTS = ["新闻", "教务", "学术", "招聘", "文体", "院系", "图书馆", "计算机"]
ROLES = ["本科生", "研究生", "教师", "校友", "访客"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=200_000)
def relocate_data_path(value: str) -> str:
    """Map stale absolute data paths to this checkout's data directory."""
    if not value:
        return ""
    raw = str(value)
    normalized = raw.replace("\\", "/")
    current_data = str(DATA_DIR.resolve()).replace("\\", "/").lower().rstrip("/")
    lowered = normalized.lower()
    if lowered == current_data or lowered.startswith(current_data + "/"):
        return raw

    parts = normalized.split("/")
    for idx, part in enumerate(parts):
        if part.lower() != "data":
            continue
        candidate = DATA_DIR.joinpath(*parts[idx + 1 :])
        return str(candidate)
    return raw
