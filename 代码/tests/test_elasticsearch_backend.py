from nku_search.elasticsearch_backend import ElasticsearchBackend
from nku_search.indexer import SearchIndex
from nku_search.models import Document
from nku_search.query import parse_query
from nku_search.search import SearchEngine


def test_es_query_builds_filters_and_phrase() -> None:
    backend = ElasticsearchBackend(enabled=False)
    query = backend.build_query(parse_query('"南开 大学" site:news.nankai.edu.cn filetype:html'), size=25)

    assert query["size"] == 25
    filters = query["query"]["bool"]["filter"]
    assert any(
        "wildcard" in item and item["wildcard"].get("host", {}).get("value") == "*news.nankai.edu.cn*"
        for item in filters
    )
    assert {"term": {"doc_type": "html"}} in filters
    assert any("match_phrase" in item for item in query["query"]["bool"]["must"])


def test_es_site_filter_matches_subdomain_substring() -> None:
    backend = ElasticsearchBackend(enabled=False)
    query = backend.build_query(parse_query("操作系统 site:nankai.edu.cn"), size=10)
    filters = query["query"]["bool"]["filter"]
    assert any(
        "wildcard" in item and item["wildcard"].get("host", {}).get("value") == "*nankai.edu.cn*"
        for item in filters
    )


def test_search_falls_back_when_es_unavailable() -> None:
    doc = Document(
        id="1",
        url="https://news.nankai.edu.cn/demo",
        title="南开大学新闻",
        body="南开 大学 新闻",
        host="news.nankai.edu.cn",
        doc_type="html",
        snapshot_path="data/snapshots/demo.html.gz",
    )
    index = SearchIndex(
        documents=[doc.to_dict()],
        indexed_documents={
            "1": {
                "id": "1",
                "tf": {"南开": 2, "大学": 1, "新闻": 1},
                "title_tf": {"南开": 1, "大学": 1, "新闻": 1},
                "anchor_tf": {},
                "body_tf": {"南开": 1, "大学": 1, "新闻": 1},
                "attachment_tf": {},
                "weighted_tf": {"南开": 2, "大学": 2, "新闻": 2},
                "length": 3,
                "title_norm": 1.0,
                "anchor_norm": 0.0,
                "body_norm": 1.0,
                "attachment_norm": 0.0,
            }
        },
        idf={"南开": 1.0, "大学": 1.0, "新闻": 1.0},
        avg_len=3.0,
        suggestions=["南开大学新闻"],
        term_docs={"南开": ["1"], "大学": ["1"], "新闻": ["1"]},
    )

    response = SearchEngine(index=index, backend="es").search("南开")

    assert response.total >= 1
    assert response.backend == "local"


def test_es_recall_size_is_adaptive() -> None:
    index = SearchIndex(documents=[], indexed_documents={}, idf={}, avg_len=1.0, suggestions=[], term_docs={})
    engine = SearchEngine(index=index, backend="auto")

    assert engine.es_recall_size(parse_query("\u5357\u5f00")) == 1200
    assert engine.es_recall_size(parse_query("\u4fe1\u606f\u68c0\u7d22 filetype:pdf")) == 2000
    assert engine.es_recall_size(parse_query("\u64cd\u4f5c\u7cfb\u7edf site:cc.nankai.edu.cn")) == 2000
    assert engine.es_recall_size(parse_query("\u6e29*")) == 2000
    assert engine.es_recall_size(parse_query('"\u5357\u5f00 \u5927\u5b66"')) == 2500
    assert engine.es_recall_size(parse_query("\u8bfe\u7a0b"), user={"id": None, "role": "\u6559\u5e08"}) == 5000
