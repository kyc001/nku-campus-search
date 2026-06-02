from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ES_INDEX, ES_TIMEOUT, ES_URL
from .indexer import SearchIndex
from .models import Document, ParsedQuery

try:
    from elasticsearch import Elasticsearch, helpers
except Exception:  # pragma: no cover - optional dependency fallback
    Elasticsearch = None
    helpers = None


TEXT_FIELDS = ["title^4", "anchor_text^3", "body", "url_text^0.5"]
MAX_ES_RECALL = 5000


@dataclass
class ElasticRecall:
    doc_ids: list[str]
    total: int
    available: bool


class ElasticsearchBackend:
    def __init__(
        self,
        url: str = ES_URL,
        index_name: str = ES_INDEX,
        enabled: bool = True,
        timeout: float = ES_TIMEOUT,
    ):
        self.url = url
        self.index_name = index_name
        self.enabled = enabled
        self.timeout = timeout
        self.client = None
        self._available: bool | None = False if not enabled else None
        if enabled and Elasticsearch is not None:
            try:
                self.client = Elasticsearch(url, request_timeout=timeout)
            except Exception:
                self.client = None
                self._available = False

    def available(self, force: bool = False) -> bool:
        if not self.enabled:
            return False
        if self.client is None and Elasticsearch is not None:
            try:
                self.client = Elasticsearch(self.url, request_timeout=self.timeout)
            except Exception:
                self.client = None
        if self.client is None:
            self._available = False
            return False
        if self._available is True and not force:
            return self._available
        try:
            self._available = bool(self.client.options(request_timeout=self.timeout).ping())
        except Exception:
            self._available = False
        return self._available

    def build_query(self, parsed: ParsedQuery, size: int = 1000) -> dict[str, Any]:
        must: list[dict[str, Any]] = []
        should: list[dict[str, Any]] = []
        filters: list[dict[str, Any]] = []

        if parsed.site:
            site = parsed.site.lower()
            # 与本地实现保持一致：parsed.site 是子串匹配（例如 "nankai.edu.cn" 可匹配
            # news.nankai.edu.cn）。这里用 wildcard 让 ES 召回口径与本地相同，避免
            # ES 后端在用户输入"nankai.edu.cn"时召回为空、本地却有结果的歧义。
            filters.append({"wildcard": {"host": {"value": f"*{site}*"}}})
        if parsed.filetype:
            filters.append({"term": {"doc_type": parsed.filetype}})

        if parsed.terms:
            must.append(
                {
                    "multi_match": {
                        "query": " ".join(parsed.terms),
                        "fields": TEXT_FIELDS,
                        "type": "best_fields",
                        "operator": "or",
                    }
                }
            )

        for phrase in parsed.phrases:
            must.append({"match_phrase": {"all_text": phrase}})

        if parsed.wildcard:
            should.append(
                {
                    "query_string": {
                        "query": parsed.wildcard,
                        "fields": ["title^5", "body^2", "anchor_text", "url_text"],
                        "analyze_wildcard": True,
                    }
                }
            )

        if parsed.regex:
            regex_should = [
                {"regexp": {field: {"value": f".*{parsed.regex}.*", "case_insensitive": True}}}
                for field in ["title.keyword", "url", "host"]
            ]
            should.append({"bool": {"should": regex_should, "minimum_should_match": 1}})

        bool_query: dict[str, Any] = {"filter": filters}
        if must:
            bool_query["must"] = must
        if should:
            bool_query["should"] = should
            if not must:
                bool_query["minimum_should_match"] = 1
        if not must and not should and not filters:
            query: dict[str, Any] = {"match_all": {}}
        else:
            query = {"bool": bool_query}

        return {
            "size": size,
            "track_total_hits": True,
            "query": query,
            "highlight": {
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fields": {
                    "title": {"number_of_fragments": 0},
                    "body": {"fragment_size": 160, "number_of_fragments": 1},
                    "anchor_text": {"fragment_size": 120, "number_of_fragments": 1},
                },
            },
        }

    def search_doc_ids(self, parsed: ParsedQuery, size: int) -> ElasticRecall:
        if not self.available():
            return ElasticRecall([], 0, False)
        try:
            body = self.build_query(parsed, size=min(size, MAX_ES_RECALL))
            body.pop("highlight", None)
            body["_source"] = False
            body["stored_fields"] = []
            response = self.client.options(request_timeout=max(self.timeout, 30)).search(
                index=self.index_name,
                body=body,
            )
            body = response.body if hasattr(response, "body") else response
            hits = body.get("hits", {})
            total = hits.get("total", 0)
            if isinstance(total, dict):
                total_value = int(total.get("value", 0))
            else:
                total_value = int(total)
            doc_ids = [str(hit.get("_id")) for hit in hits.get("hits", []) if hit.get("_id")]
            return ElasticRecall(doc_ids, total_value, True)
        except Exception:
            self._available = False
            return ElasticRecall([], 0, False)

    def rebuild(self, index: SearchIndex) -> int:
        if not self.available():
            raise RuntimeError(f"Elasticsearch is not available at {self.url}")
        admin = self.client.options(request_timeout=max(self.timeout, 60))
        admin.indices.delete(index=self.index_name, ignore_unavailable=True)
        admin.indices.create(index=self.index_name, mappings=self.mapping(), settings=self.settings())
        actions = (
            {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": row["id"],
                "_source": self.document_source(Document.from_dict(row)),
            }
            for row in index.documents
        )
        ok, _ = helpers.bulk(
            self.client.options(request_timeout=max(self.timeout, 120)),
            actions,
            chunk_size=500,
            raise_on_error=False,
        )
        admin.indices.put_settings(index=self.index_name, settings={"index": {"refresh_interval": "1s"}})
        admin.indices.refresh(index=self.index_name)
        return int(ok)

    @staticmethod
    def document_source(doc: Document) -> dict[str, Any]:
        return {
            "url": doc.url,
            "url_text": doc.url,
            "title": doc.title,
            "body": doc.body,
            "anchor_text": doc.anchor_text,
            "all_text": " ".join([doc.title, doc.anchor_text, doc.body, doc.url]),
            "host": doc.host,
            "doc_type": doc.doc_type,
            "snapshot_path": doc.snapshot_path,
            "attachment_url": doc.attachment_url,
            "pagerank": doc.pagerank,
            "inlinks_count": doc.inlinks_count,
            "crawled_at": doc.crawled_at,
            "tags": doc.tags,
        }

    @staticmethod
    def settings() -> dict[str, Any]:
        return {
            "number_of_replicas": 0,
            "refresh_interval": "-1",
            "analysis": {
                "analyzer": {
                    "nku_text": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    }
                }
            }
        }

    @staticmethod
    def mapping() -> dict[str, Any]:
        text_field = {
            "type": "text",
            "analyzer": "nku_text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            "copy_to": "all_text",
        }
        return {
            "properties": {
                "url": {"type": "keyword"},
                "url_text": {"type": "text", "analyzer": "nku_text", "copy_to": "all_text"},
                "title": text_field,
                "body": {"type": "text", "analyzer": "nku_text", "copy_to": "all_text"},
                "anchor_text": {"type": "text", "analyzer": "nku_text", "copy_to": "all_text"},
                "all_text": {"type": "text", "analyzer": "nku_text"},
                "host": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "snapshot_path": {"type": "keyword"},
                "attachment_url": {"type": "keyword"},
                "pagerank": {"type": "float"},
                "inlinks_count": {"type": "integer"},
                "crawled_at": {"type": "date", "ignore_malformed": True},
                "tags": {"type": "keyword"},
            }
        }
