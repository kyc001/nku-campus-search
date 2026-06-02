# Search Performance And UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce query latency and improve the search UI without changing the homework-visible feature set.

**Architecture:** Keep Elasticsearch as the default retrieval layer and VSM + PageRank as the ranking layer. Optimize repeated per-candidate work by preparing query-level state once, shrinking ES recall where safe, and making the frontend suggestion/results interactions cheaper.

**Tech Stack:** Python 3.12, Flask, pytest, Elasticsearch Python client, vanilla JS/CSS.

---

### Task 1: Query Context And Pattern Filters

**Files:**
- Modify: `tests/test_search.py`
- Modify: `nku_search/search.py`

- [ ] Write tests for compiled query context and local regex/wildcard candidate narrowing.
- [ ] Run `python -m pytest tests/test_search.py -q` and confirm the new tests fail before implementation.
- [ ] Add query-level compiled patterns and use them in `_passes_filters`, `_pattern_field_score`, and title boost checks.
- [ ] Run `python -m pytest tests/test_search.py -q` and confirm the tests pass.

### Task 2: ES Recall Strategy

**Files:**
- Modify: `tests/test_elasticsearch_backend.py`
- Modify: `nku_search/elasticsearch_backend.py`
- Modify: `nku_search/search.py`

- [ ] Write tests for adaptive recall size and source-free ES search body.
- [ ] Run `python -m pytest tests/test_elasticsearch_backend.py -q` and confirm failures.
- [ ] Add adaptive recall limits and graceful total handling when exact totals are disabled.
- [ ] Run `python -m pytest tests/test_elasticsearch_backend.py -q`.

### Task 3: Frontend Suggest And Results Polish

**Files:**
- Modify: `static/app.js`
- Modify: `templates/search.html`
- Modify: `static/style.css`

- [ ] Add cheap client-side suggest behavior: minimum length, abort stale requests, keyboard navigation, and cached responses.
- [ ] Reduce visual noise in result cards while keeping VSM/PageRank evidence visible.
- [ ] Verify templates render with Flask selfcheck.

### Task 4: Verification

**Files:**
- Run-only verification.

- [ ] Run `python -m py_compile nku_search/search.py nku_search/elasticsearch_backend.py nku_search/web.py`.
- [ ] Run `python -m pytest tests/ -q`.
- [ ] Run `python -m nku_search.selfcheck --all`.
- [ ] Run a small benchmark comparing common queries after optimization.
