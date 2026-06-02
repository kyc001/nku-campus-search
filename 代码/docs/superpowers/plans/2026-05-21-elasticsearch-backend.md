# Elasticsearch Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Elasticsearch as an optional mature retrieval backend while preserving the existing local VSM + PageRank reranking path and current selfcheck behavior.

**Architecture:** Elasticsearch is used for candidate recall, filtering, phrase/wildcard/regex matching, and optional highlight snippets. The application still reranks returned candidates with the existing TF-IDF cosine VSM, PageRank, freshness, and personalization formula so the homework's VSM requirement remains explicit. If Elasticsearch is not installed or not running, the system falls back to the local index automatically.

**Tech Stack:** Python, Flask, pixi, official `elasticsearch` Python client, Elasticsearch REST query DSL, existing local JSON index.

---

### Task 1: Tests

**Files:**
- Modify: `tests/test_search.py`

- [ ] Add tests for Elasticsearch query construction and local fallback:

```python
def test_es_query_builds_filters_and_phrase():
    from nku_search.elasticsearch_backend import ElasticsearchBackend
    from nku_search.query import parse_query

    backend = ElasticsearchBackend(enabled=False)
    query = backend.build_query(parse_query('"南开 大学" site:news.nankai.edu.cn filetype:html'), size=25)
    assert query["size"] == 25
    assert {"term": {"host": "news.nankai.edu.cn"}} in query["query"]["bool"]["filter"]
    assert {"term": {"doc_type": "html"}} in query["query"]["bool"]["filter"]
    assert any("match_phrase" in item for item in query["query"]["bool"]["must"])


def test_search_falls_back_when_es_unavailable():
    from nku_search.search import SearchEngine

    engine = SearchEngine(backend="es")
    response = engine.search("南开")
    assert response.total >= 1
    assert response.backend in {"local", "elasticsearch"}
```

- [ ] Run `python -m pytest tests/test_search.py -q` and verify the first test fails because `nku_search.elasticsearch_backend` does not exist.

### Task 2: Elasticsearch Backend

**Files:**
- Create: `nku_search/elasticsearch_backend.py`
- Modify: `nku_search/config.py`

- [ ] Add config constants `ES_URL`, `ES_INDEX`, `ES_TIMEOUT`.
- [ ] Implement `ElasticsearchBackend` with optional import of the official client, `available()`, `build_query()`, `search_doc_ids()`, and `rebuild()`.
- [ ] Use `helpers.bulk` for indexing local documents into Elasticsearch.

### Task 3: Search Engine Integration

**Files:**
- Modify: `nku_search/search.py`
- Modify: `nku_search/cli.py`

- [ ] Add `backend` and `candidate_total` to `SearchResponse`.
- [ ] Let `SearchEngine(backend="auto")` select Elasticsearch when available, otherwise local.
- [ ] Add CLI commands:
  - `build-es-index`
  - `search --backend auto|local|es`

### Task 4: Web Optimization

**Files:**
- Modify: `nku_search/web.py`
- Modify: `templates/index.html`
- Modify: `templates/search.html`
- Modify: `templates/_search_form.html`
- Modify: `static/style.css`

- [ ] Show backend badge, document count, snapshot count, and file type distribution.
- [ ] Add advanced syntax chips for site/filetype/phrase/wildcard/regex.
- [ ] Display candidate backend and reranking explanation on result pages.
- [ ] Add doc/docx/xls/xlsx to the type selector.

### Task 5: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `../report/main.typ`
- Modify: `../report/ppt.typ`
- Modify: `../report/讲解稿.md`

- [ ] Document Elasticsearch as an optional mature retrieval backend.
- [ ] Rebuild Typst PDFs.
- [ ] Run:

```powershell
python -m pytest tests/test_search.py -q
python -m nku_search.selfcheck --all
typst compile ../report/main.typ ../report/main.pdf
typst compile ../report/ppt.typ ../report/ppt.pdf
```
