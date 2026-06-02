from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import relocate_data_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Document:
    id: str
    url: str
    title: str
    body: str
    host: str
    doc_type: str = "html"
    anchor_text: str = ""
    outlinks: list[str] = field(default_factory=list)
    inlinks_count: int = 0
    pagerank: float = 0.0
    crawled_at: str = field(default_factory=utc_now_iso)
    last_modified: str = ""
    snapshot_path: str = ""
    attachment_url: str = ""
    attachment_path: str = ""
    file_size: int = 0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Document":
        values = dict(data)
        values.setdefault("doc_type", "html")
        values.setdefault("anchor_text", "")
        values.setdefault("outlinks", [])
        values.setdefault("inlinks_count", 0)
        values.setdefault("pagerank", 0.0)
        values.setdefault("crawled_at", utc_now_iso())
        values.setdefault("last_modified", "")
        values.setdefault("snapshot_path", "")
        values.setdefault("attachment_url", "")
        values.setdefault("attachment_path", "")
        values.setdefault("file_size", 0)
        values.setdefault("tags", [])
        values["snapshot_path"] = relocate_data_path(values.get("snapshot_path", ""))
        values["attachment_path"] = relocate_data_path(values.get("attachment_path", ""))
        return cls(**values)


@dataclass
class SearchResult:
    document: Document
    score: float
    snippet: str
    matched_features: list[str] = field(default_factory=list)
    ranking_signals: list[str] = field(default_factory=list)
    display_title: str = ""


@dataclass
class Recommendation:
    document: Document
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    category: str = "相关资源"
    snippet: str = ""
    display_title: str = ""


@dataclass
class ParsedQuery:
    raw: str
    terms: list[str]
    phrases: list[str] = field(default_factory=list)
    site: str = ""
    filetype: str = ""
    wildcard: str = ""
    regex: str = ""
