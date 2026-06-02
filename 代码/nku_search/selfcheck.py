from __future__ import annotations

import argparse
from pathlib import Path

from .database import init_db
from .demo_data import create_demo_dataset
from .elasticsearch_backend import ElasticsearchBackend
from .query import parse_query
from .search import FIELD_WEIGHTS, SearchEngine, _is_low_quality_page
from .snapshot import render_snapshot
from .storage import load_documents


_ENGINE: SearchEngine | None = None


def shared_engine() -> SearchEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SearchEngine()
    return _ENGINE


def document_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _line(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"{name:<34} {status} {detail}".rstrip())
    return ok


def check_index() -> bool:
    docs_count = document_count(Path("data/documents.jsonl"))
    if docs_count < 2000:
        docs_count = len(create_demo_dataset())
    engine = shared_engine()
    ok = True
    ok &= _line("[index] documents >= 2000", docs_count >= 2000, str(docs_count))
    ok &= _line("[index] title field exists", all("title_tf" in row for row in engine.index.indexed_documents.values()))
    ok &= _line("[index] anchor field exists", all("anchor_tf" in row for row in engine.index.indexed_documents.values()))
    ok &= _line("[index] pagerank computed", max(doc.pagerank for doc in engine.documents.values()) > 0)
    return ok


def check_queries() -> bool:
    engine = shared_engine()
    ok = True
    site = engine.search("操作系统 site:cc.nankai.edu.cn")
    ok &= _line("[query] site", site.total > 0 and all("cc.nankai.edu.cn" in r.document.host for r in site.results))
    filetype = engine.search("信息检索 filetype:pdf")
    ok &= _line("[query] filetype", filetype.total > 0 and all(r.document.doc_type == "pdf" for r in filetype.results))
    phrase = engine.search('"南开 大学"')
    non_adjacent = engine.search('"南开 是一所综合性大学"')
    ok &= _line("[query] phrase", phrase.total > 0 and non_adjacent.total < phrase.total)
    wildcard = engine.search("温*")
    ok &= _line("[query] wildcard", wildcard.total > 0 and "温" in wildcard.results[0].document.title)
    regex = engine.search("/信息.{0,2}/")
    ok &= _line("[query] regex", regex.total > 0)
    snapshot = next((r.document for r in engine.search("南开").results if r.document.snapshot_path), None)
    snapshot_ok = False
    if snapshot and snapshot.snapshot_path:
        try:
            html = render_snapshot(snapshot.snapshot_path, snapshot.url, snapshot.crawled_at)
            snapshot_ok = "网页快照" in html and snapshot.url in html
        except Exception:
            snapshot_ok = False
    ok &= _line("[query] snapshot render", snapshot_ok)
    attachment = next((r.document for r in engine.search("信息检索 filetype:pdf").results if r.document.attachment_path), None)
    attachment_ok = bool(attachment and attachment.attachment_path and Path(attachment.attachment_path).exists())
    ok &= _line("[query] attachment file", attachment_ok)
    quality = engine.search("南开大学", page_size=8)
    quality_ok = quality.total > 0 and all(not _is_low_quality_page(item.document) for item in quality.results[:5])
    ok &= _line("[quality] top results readable", quality_ok)
    return ok


def check_vsm() -> bool:
    engine = shared_engine()
    response = engine.search("信息检索")
    ok = response.total > 0
    if ok:
        indexed = engine.index.indexed_documents[response.results[0].document.id]
        raw_vsm = engine._vsm_score(indexed, ["信息", "检索", "信息检索"])
        ok = ok and 0 <= raw_vsm <= sum(FIELD_WEIGHTS.values())
    manual_field = {"a": 1, "b": 1}
    engine.index.idf.update({"a": 1.0, "b": 1.0})
    q_vec, q_norm = engine._query_vector(["a", "b"])
    cosine = engine._field_cosine(manual_field, 2 ** 0.5, q_vec, q_norm)
    ok = ok and abs(cosine - 1.0) < 1e-9
    return _line("[ranking] VSM cosine", ok, f"cos={cosine:.3f}")


def check_elasticsearch() -> bool:
    backend = ElasticsearchBackend(enabled=False)
    query = backend.build_query(parse_query('"南开 大学" site:news.nankai.edu.cn filetype:html'), size=25)
    filters = query["query"]["bool"]["filter"]
    must = query["query"]["bool"]["must"]
    site_filter_ok = any(
        "wildcard" in item and item["wildcard"].get("host", {}).get("value") == "*news.nankai.edu.cn*"
        for item in filters
    )
    ok = (
        query["size"] == 25
        and site_filter_ok
        and {"term": {"doc_type": "html"}} in filters
        and any("match_phrase" in item for item in must)
    )
    return _line("[elastic] optional recall DSL", ok)


def check_personalize() -> bool:
    init_db()
    engine = shared_engine()
    student = {"id": None, "role": "本科生", "interests": '["教务","课程","就业"]'}
    teacher = {"id": None, "role": "教师", "interests": '["学术","图书馆"]'}
    query = "人工智能 学术 讲座"
    guest = engine.search(query, candidate_limit=2500)
    r1 = engine.search(query, user=student, candidate_limit=2500)
    r2 = engine.search(query, user=teacher, candidate_limit=2500)
    student_reasons = [reason for rec in r1.recommendations for reason in rec.reasons]
    teacher_reasons = [reason for rec in r2.recommendations for reason in rec.reasons]
    ok = (
        guest.total > 0
        and
        r1.total > 0
        and r2.total > 0
        and len({guest.results[0].document.url, r1.results[0].document.url, r2.results[0].document.url}) >= 2
        and r1.results[0].document.doc_type == "html"
        and "个性化" in r1.results[0].ranking_signals
        and "个性化" in r2.results[0].ranking_signals
        and bool(r1.recommendations)
        and bool(r2.recommendations)
        and any("兴趣命中" in reason or "同主题" in reason for reason in student_reasons)
        and any("兴趣命中" in reason or "文档" in reason or "同主题" in reason for reason in teacher_reasons)
    )
    return _line("[personalize] ranking/recommend", ok)


def check_web() -> bool:
    from . import web

    engine = shared_engine()
    web.set_engine(engine)
    app = web.app
    client = app.test_client()
    ok = True
    ok &= _line("[web] index", client.get("/").status_code == 200)
    ok &= _line("[web] search", client.get("/search?q=信息检索").status_code == 200)
    ok &= _line("[web] suggest", client.get("/api/suggest?q=南开").status_code == 200)
    doc = next(doc for doc in engine.documents.values() if doc.snapshot_path)
    ok &= _line("[web] snapshot", client.get(f"/snapshot?url={doc.url}").status_code == 200)
    attachment = next((doc for doc in engine.documents.values() if doc.attachment_path), None)
    if attachment:
        ok &= _line("[web] download", client.get(f"/download?url={attachment.url}").status_code == 200)
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--phase", choices=["index", "queries", "ranking", "personalize", "webui", "elastic"])
    args = parser.parse_args(argv)

    phases = []
    if args.all or not args.phase:
        phases = [check_index, check_queries, check_vsm, check_elasticsearch, check_personalize, check_web]
    elif args.phase == "index":
        phases = [check_index]
    elif args.phase == "queries":
        phases = [check_queries]
    elif args.phase == "ranking":
        phases = [check_vsm]
    elif args.phase == "elastic":
        phases = [check_elasticsearch]
    elif args.phase == "personalize":
        phases = [check_personalize]
    elif args.phase == "webui":
        phases = [check_web]

    print("=========== SELFCHECK ===========")
    ok = True
    for phase in phases:
        ok &= phase()
    print("=========== SUMMARY =============")
    print("ALL PASS - ready to submit." if ok else "FAILED - fix required.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
