from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .config import DOCUMENTS_PATH, ensure_dirs
from .models import Document


def _clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(_clean_json_value(key)): _clean_json_value(item) for key, item in value.items()}
    return value


def _document_line(doc: Document) -> str:
    return json.dumps(_clean_json_value(doc.to_dict()), ensure_ascii=False) + "\n"


def read_jsonl(path: Path = DOCUMENTS_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_document_refs(path: Path = DOCUMENTS_PATH, include_outlinks: bool = False) -> tuple[set[str], set[str], list[str]]:
    doc_ids: set[str] = set()
    urls: set[str] = set()
    outlinks: list[str] = []
    if not path.exists():
        return doc_ids, urls, outlinks
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            doc_id = row.get("id")
            if not doc_id or doc_id in doc_ids:
                continue
            doc_ids.add(doc_id)
            url = row.get("url")
            if url:
                urls.add(url)
            if include_outlinks:
                outlinks.extend(row.get("outlinks") or [])
    return doc_ids, urls, outlinks


def load_documents(path: Path = DOCUMENTS_PATH) -> list[Document]:
    by_id: dict[str, Document] = {}
    for row in read_jsonl(path):
        doc = Document.from_dict(row)
        by_id[doc.id] = doc
    return list(by_id.values())


def save_documents(documents: list[Document], path: Path = DOCUMENTS_PATH) -> None:
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8", errors="replace") as f:
        for doc in documents:
            f.write(_document_line(doc))
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.2 * (attempt + 1))
    tmp.replace(path)


def upsert_documents(new_documents: list[Document], path: Path = DOCUMENTS_PATH) -> None:
    existing = {doc.id: doc for doc in load_documents(path)}
    for doc in new_documents:
        existing[doc.id] = doc
    save_documents(list(existing.values()), path)


def append_documents(new_documents: list[Document], path: Path = DOCUMENTS_PATH) -> None:
    if not new_documents:
        return
    ensure_dirs()
    with path.open("a", encoding="utf-8", errors="replace") as f:
        for doc in new_documents:
            f.write(_document_line(doc))
