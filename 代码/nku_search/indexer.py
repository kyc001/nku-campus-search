from __future__ import annotations

import json
import math
import os
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import INDEX_PATH, ensure_dirs
from .models import Document
from .pagerank import apply_link_analysis
from .storage import load_documents
from .text import load_user_dict, term_counter, tokenize

FIELD_WEIGHTS = {
    "title": 4.0,
    "anchor_text": 3.0,
    "body": 1.0,
    "attachment": 1.5,
    "url": 0.5,
}

MAX_INDEX_TEXT_CHARS = 4_000
MAX_STORED_BODY_CHARS = 2_000
MAX_FIELD_TERMS = 120


@dataclass
class IndexedDocument:
    id: str
    tf: dict[str, int]
    title_tf: dict[str, int]
    anchor_tf: dict[str, int]
    body_tf: dict[str, int]
    attachment_tf: dict[str, int]
    weighted_tf: dict[str, float]
    length: int
    title_norm: float = 0.0
    anchor_norm: float = 0.0
    body_norm: float = 0.0
    attachment_norm: float = 0.0


@dataclass
class SearchIndex:
    documents: list[dict]
    indexed_documents: dict[str, dict]
    idf: dict[str, float]
    avg_len: float
    suggestions: list[str]
    term_docs: dict[str, list[str]]

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "SearchIndex":
        return cls(
            documents=data.get("documents", []),
            indexed_documents=data.get("indexed_documents", {}),
            idf=data.get("idf", {}),
            avg_len=data.get("avg_len", 1.0),
            suggestions=data.get("suggestions", []),
            term_docs=data.get("term_docs", {}),
        )


def _field_norm(tf: dict[str, int], idf: dict[str, float]) -> float:
    total = 0.0
    for term, count in tf.items():
        if count <= 0:
            continue
        weight = (1.0 + math.log(count)) * idf.get(term, 0.0)
        total += weight * weight
    return math.sqrt(total)


def _trim_counter(counter: Counter[str], limit: int = MAX_FIELD_TERMS) -> Counter[str]:
    if len(counter) <= limit:
        return counter
    return Counter(dict(counter.most_common(limit)))


def _indexed_body(doc: Document) -> str:
    return (doc.body or "")[:MAX_INDEX_TEXT_CHARS]


def _stored_doc(doc: Document) -> dict:
    data = doc.to_dict()
    body = data.get("body") or ""
    if len(body) > MAX_STORED_BODY_CHARS:
        data["body"] = body[:MAX_STORED_BODY_CHARS]
    data["outlinks"] = (data.get("outlinks") or [])[:200]
    return data


def _weighted_tf(doc: Document) -> tuple[Counter[str], dict[str, Counter[str]]]:
    body = _indexed_body(doc)
    field_tfs = {
        "title": term_counter(doc.title),
        "anchor_text": term_counter(doc.anchor_text),
        "body": term_counter(body),
        "attachment": term_counter(body if doc.doc_type != "html" else ""),
        "url": term_counter(doc.url),
    }
    field_tfs = {field: _trim_counter(counter) for field, counter in field_tfs.items()}
    weighted: Counter[str] = Counter()
    for field, counter in field_tfs.items():
        for term, count in counter.items():
            weighted[term] += count * FIELD_WEIGHTS[field]
    merged: Counter[str] = Counter()
    for counter in field_tfs.values():
        merged.update(counter)
    return weighted, field_tfs | {"merged": merged}


def build_index(documents: list[Document] | None = None, path: Path = INDEX_PATH) -> SearchIndex:
    load_user_dict()
    ensure_dirs()
    docs = load_documents() if documents is None else documents
    docs = apply_link_analysis(docs)

    indexed: dict[str, IndexedDocument] = {}
    df: Counter[str] = Counter()
    term_docs: dict[str, list[str]] = defaultdict(list)
    total_len = 0
    suggestion_counter: Counter[str] = Counter()
    n_docs = max(len(docs), 1)

    for idx, doc in enumerate(docs, start=1):
        weighted, fields = _weighted_tf(doc)
        length = sum(fields["merged"].values())
        total_len += length
        for term in fields["merged"]:
            df[term] += 1
            term_docs[term].append(doc.id)
        if doc.title:
            suggestion_counter[doc.title] += 5
        for token in tokenize(doc.title):
            if len(token) >= 2:
                suggestion_counter[token] += 1
        indexed[doc.id] = IndexedDocument(
            id=doc.id,
            tf=dict(fields["merged"]),
            title_tf=dict(fields["title"]),
            anchor_tf=dict(fields["anchor_text"]),
            body_tf=dict(fields["body"]),
            attachment_tf=dict(fields["attachment"]),
            weighted_tf=dict(weighted),
            length=length,
        )
        if idx % 5000 == 0:
            print(f"[index] tokenized {idx}/{n_docs}", flush=True)

    # VSM 主排序使用 ltc TF-IDF。这里保存平滑后的 idf，使高频词仍有
    # 可解释的非零权重，避免小规模演示数据中公共主题词全部变成 0。
    idf = {
        term: math.log((n_docs + 1.0) / (freq + 1.0)) + 1.0
        for term, freq in df.items()
    }
    for data in indexed.values():
        data.title_norm = _field_norm(data.title_tf, idf)
        data.anchor_norm = _field_norm(data.anchor_tf, idf)
        data.body_norm = _field_norm(data.body_tf, idf)
        data.attachment_norm = _field_norm(data.attachment_tf, idf)
    suggestions = [
        item for item, _ in suggestion_counter.most_common(300)
        if item and len(item) <= 60
    ]
    index = SearchIndex(
        documents=[_stored_doc(doc) for doc in docs],
        indexed_documents={doc_id: asdict(data) for doc_id, data in indexed.items()},
        idf=idf,
        avg_len=total_len / n_docs,
        suggestions=suggestions,
        term_docs={term: ids for term, ids in term_docs.items()},
    )
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(index.to_json(), f, ensure_ascii=False)
    for attempt in range(10):
        try:
            tmp.replace(path)
            return index
        except PermissionError:
            time.sleep(0.2 * (attempt + 1))
    tmp.replace(path)
    return index


def load_index(path: Path = INDEX_PATH) -> SearchIndex:
    load_user_dict()
    if not path.exists():
        return build_index(path=path)
    with path.open("r", encoding="utf-8") as f:
        return SearchIndex.from_json(json.load(f))


def document_lookup(index: SearchIndex) -> dict[str, Document]:
    return {row["id"]: Document.from_dict(row) for row in index.documents}


def build_anchor_texts(documents: list[Document]) -> list[Document]:
    anchors: dict[str, list[str]] = defaultdict(list)
    url_to_doc = {doc.url: doc for doc in documents}
    for doc in documents:
        for out_url in doc.outlinks:
            if out_url in url_to_doc:
                anchors[out_url].append(doc.title)
    for doc in documents:
        existing = [doc.anchor_text] if doc.anchor_text else []
        doc.anchor_text = " ".join(existing + anchors.get(doc.url, []))
    return documents
