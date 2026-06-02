from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from .config import ALLOWED_DOMAIN_SUFFIX, CODE_ROOT, INTERESTS, NKU_SEARCH_BACKEND_DEFAULT, ROLES
from .database import (
    clear_history,
    create_user,
    get_user,
    init_db,
    log_click,
    log_query,
    query_history,
    query_history_count,
    recent_queries,
    verify_user,
)
from .demo_data import create_demo_dataset
from .indexer import build_index, load_index
from .search import SearchEngine
from .search import _has_weak_title, _is_low_quality_page, _is_noisy_url, _is_readable_title
from .snapshot import render_snapshot

app = Flask(
    __name__,
    template_folder=str(CODE_ROOT / "templates"),
    static_folder=str(CODE_ROOT / "static"),
)
app.secret_key = "nku-ir-hw4-dev-secret"
engine: SearchEngine | None = None
_stats_cache: dict | None = None
SUPPORTED_FILETYPES = {"html", "pdf", "doc", "docx", "xls", "xlsx"}


def get_engine() -> SearchEngine:
    global engine
    if engine is None:
        engine = SearchEngine(load_index(), backend=os.environ.get("NKU_SEARCH_BACKEND", NKU_SEARCH_BACKEND_DEFAULT))
    return engine


def set_engine(instance: SearchEngine) -> None:
    global engine, _stats_cache
    engine = instance
    _stats_cache = None


def current_user() -> dict | None:
    return get_user(session.get("user_id"))


def engine_stats(force: bool = False) -> dict:
    global _stats_cache
    current_engine = get_engine()
    es_available = current_engine.es_backend.available(force=force)
    if current_engine.backend_mode == "local":
        backend_label = "本地倒排"
        backend_detail = "已手动选择本地索引召回"
    elif es_available:
        backend_label = "Elasticsearch"
        backend_detail = "ES 在线，候选召回走 Elasticsearch"
    else:
        backend_label = "本地倒排"
        backend_detail = "ES 不可用，候选召回自动回退到本地索引"
    if _stats_cache is not None and not force:
        _stats_cache.update(
            {
                "es_available": es_available,
                "backend_label": backend_label,
                "backend_detail": backend_detail,
            }
        )
        return _stats_cache
    docs = list(current_engine.documents.values())
    type_counts = Counter(doc.doc_type for doc in docs)
    host_counts = Counter(doc.host for doc in docs)
    tag_counts: Counter[str] = Counter()
    for doc in docs:
        tag_counts.update(doc.tags)
    noise_pages = sum(1 for doc in docs if _is_noisy_url(doc))
    weak_titles = sum(1 for doc in docs if _has_weak_title(doc))
    low_quality_pages = sum(1 for doc in docs if _is_low_quality_page(doc))
    readable_docs = max(len(docs) - noise_pages, 0)
    quality_ratio = readable_docs / max(len(docs), 1)
    _stats_cache = {
        "documents": len(docs),
        "hosts": len({doc.host for doc in docs}),
        "snapshots": sum(1 for doc in docs if doc.snapshot_path),
        "attachments": sum(1 for doc in docs if doc.attachment_path),
        "readable_docs": readable_docs,
        "noise_pages": noise_pages,
        "weak_titles": weak_titles,
        "low_quality_pages": low_quality_pages,
        "quality_ratio": quality_ratio,
        "type_counts": dict(sorted(type_counts.items())),
        "top_hosts": host_counts.most_common(8),
        "top_tags": tag_counts.most_common(8),
        "backend_mode": current_engine.backend_mode,
        "es_available": es_available,
        "es_url": current_engine.es_backend.url,
        "es_index": current_engine.es_backend.index_name,
        "backend_label": backend_label,
        "backend_detail": backend_detail,
    }
    return _stats_cache


@app.context_processor
def inject_globals() -> dict:
    return {"user": current_user(), "interests": INTERESTS, "roles": ROLES, "search_stats": engine_stats()}


@app.get("/")
def index() -> str:
    quick_queries = [
        ("教务选课", "选课 site:jwc.nankai.edu.cn"),
        ("课程考试", "操作系统 课程 考试 site:cc.nankai.edu.cn"),
        ("就业招聘", "就业 实习 双选会 site:career.nankai.edu.cn"),
        ("图书资源", "图书馆 数据库 CNKI"),
        ("PDF 文档", "实验 教学 filetype:pdf"),
        ("短语检索", '"南开 大学"'),
    ]
    return render_template("index.html", history=recent_queries(session.get("user_id"), 10), quick_queries=quick_queries)


def query_warnings(raw_query: str, site: str = "", filetype: str = "") -> list[str]:
    warnings: list[str] = []
    text = raw_query or ""
    for value in re.findall(r"\bfiletype:([A-Za-z0-9_+-]+)", text, flags=re.I):
        if value.lower() not in SUPPORTED_FILETYPES:
            warnings.append("只支持 html/pdf/doc/docx/xls/xlsx 文件类型。")
            break
    chosen_type = (filetype or "").lower()
    if chosen_type and chosen_type not in SUPPORTED_FILETYPES:
        warnings.append("只支持 html/pdf/doc/docx/xls/xlsx 文件类型。")

    sites = [site] if site else []
    sites.extend(re.findall(r"\bsite:([A-Za-z0-9_.:-]+)", text, flags=re.I))
    for host in sites:
        clean = (host or "").lower().split(":")[0]
        if clean and clean != "nankai.edu.cn" and not clean.endswith(ALLOWED_DOMAIN_SUFFIX):
            warnings.append("本系统仅索引 nankai.edu.cn 及其子域名。")
            break
    return list(dict.fromkeys(warnings))


@app.get("/search")
def search() -> str:
    q = request.args.get("q", "")
    page = int(request.args.get("page", "1") or "1")
    site = request.args.get("site", "")
    filetype = request.args.get("filetype", "")
    backend = request.args.get("backend", "auto")
    response = get_engine().search(q, page=page, site=site, filetype=filetype, user=current_user(), backend=backend)
    if q.strip():
        log_query(session.get("user_id"), q, response.total)
    return render_template(
        "search.html",
        q=q,
        site=response.parsed.site,
        filetype=response.parsed.filetype,
        backend=backend,
        response=response,
        warnings=query_warnings(q, site=site, filetype=filetype),
    )


@app.get("/snapshot")
def snapshot() -> Response | str:
    url = request.args.get("url", "")
    doc = get_engine().document_by_url(url)
    if not doc or not doc.snapshot_path:
        return render_template("message.html", title="快照不可用", message="该结果没有可展示的 HTML 快照。"), 404
    html = render_snapshot(doc.snapshot_path, doc.url, doc.crawled_at)
    return Response(html, mimetype="text/html")


@app.get("/download")
def download() -> Response:
    url = request.args.get("url", "")
    doc = get_engine().document_by_url(url)
    if not doc or not doc.attachment_path:
        return Response("attachment not found", status=404)
    return send_file(Path(doc.attachment_path), as_attachment=True)


@app.get("/api/suggest")
def suggest() -> Response:
    q = request.args.get("q", "")
    user_id = session.get("user_id")
    history_items: list[str] = []
    if user_id:
        history_items = [row["query"] for row in recent_queries(user_id, limit=20) if row.get("query")]
    return jsonify(get_engine().suggest(q, history=history_items))


@app.get("/history")
def history_page() -> str:
    user_id = session.get("user_id")
    keyword = request.args.get("q", "").strip()
    try:
        page = max(int(request.args.get("page", "1") or "1"), 1)
    except ValueError:
        page = 1
    page_size = 30
    total = query_history_count(user_id, keyword=keyword)
    offset = (page - 1) * page_size
    rows = query_history(user_id, limit=page_size, offset=offset, keyword=keyword)
    return render_template(
        "history.html",
        rows=rows,
        keyword=keyword,
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get("/api/stats")
def stats() -> Response:
    return jsonify(engine_stats())


@app.get("/personalization-demo")
def personalization_demo() -> str:
    q = request.args.get("q", "课程").strip() or "课程"
    responses = get_engine().compare_personalization(q)
    case_queries = ["课程", "就业 实习 双选会", "图书馆 CNKI", "人工智能 学术 讲座"]
    profiles = {
        "guest": ("访客", "VSM + PageRank + 新鲜度", ["通用排序", "质量降权", "站点多样性"]),
        "student": ("本科生 / 教务兴趣", "提升教务、课程、就业和网页通知", ["教务", "课程", "HTML 通知"]),
        "teacher": ("教师 / 学术兴趣", "提升学术、图书馆和可下载文档", ["学术", "图书馆", "文档资源"]),
    }
    guest_top_id = responses["guest"].results[0].document.id if responses.get("guest") and responses["guest"].results else ""
    panels = []
    for key, response in responses.items():
        label, note, tags = profiles[key]
        clean_results = [item for item in response.results if displayable_demo_title(item.document)]
        clean_recommendations = [item for item in response.recommendations if displayable_demo_title(item.document)]
        seen_ids = {item.document.id for item in clean_results}
        fallback_results = list(clean_results)
        for item in clean_recommendations:
            if len(fallback_results) >= 2:
                break
            if item.document.id in seen_ids:
                continue
            fallback_results.append(item)
            seen_ids.add(item.document.id)
        html_top = sum(1 for item in response.results[:10] if item.document.doc_type == "html")
        doc_top = sum(1 for item in response.results[:10] if item.document.doc_type != "html")
        top_total = max(html_top + doc_top, 1)
        top_item = clean_results[0] if clean_results else (response.results[0] if response.results else None)
        top_changed = bool(top_item and guest_top_id and key != "guest" and top_item.document.id != guest_top_id)
        panels.append(
            {
                "key": key,
                "label": label,
                "note": note,
                "tags": tags,
                "response": response,
                "results": fallback_results[:2],
                "recommendations": [item for item in clean_recommendations if item.document.id not in seen_ids][:3],
                "html_top": html_top,
                "doc_top": doc_top,
                "html_percent": round(html_top * 100 / top_total),
                "doc_percent": round(doc_top * 100 / top_total),
                "focus": "HTML 通知" if html_top >= doc_top else "文档资源",
                "top_changed": top_changed,
                "delta_label": "Top1 已因画像改变" if top_changed else ("通用基线" if key == "guest" else "Top1 与访客相同"),
            }
        )
    return render_template("personalization.html", q=q, panels=panels, case_queries=case_queries)


def displayable_demo_title(doc) -> bool:
    title = (doc.title or "").strip()
    if not _is_readable_title(title):
        return False
    if not re.search(r"[\u4e00-\u9fff]", title):
        return False
    if len(title) > 70 and doc.doc_type != "html":
        return False
    if re.fullmatch(r"[A-Za-z0-9_-]{18,}", title):
        return False
    return True


@app.post("/api/click")
def click() -> Response:
    data = request.get_json(silent=True) or request.form
    log_click(session.get("user_id"), data.get("query", ""), data.get("url", ""))
    return jsonify({"ok": True})


@app.route("/register", methods=["GET", "POST"])
def register() -> str | Response:
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "")
        role = request.form.get("role", "访客")
        selected = request.form.getlist("interests")
        if not username or not password:
            flash("用户名和密码不能为空")
        else:
            try:
                user_id = create_user(username, password, email=email, role=role, interests=selected)
                session["user_id"] = user_id
                return redirect(url_for("index"))
            except Exception:
                flash("用户名已存在，请换一个")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login() -> str | Response:
    if request.method == "POST":
        user = verify_user(request.form.get("username", ""), request.form.get("password", ""))
        if user:
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("用户名或密码错误")
    return render_template("login.html")


@app.get("/logout")
def logout() -> Response:
    session.clear()
    return redirect(url_for("index"))


@app.post("/history/clear")
def clear_query_history() -> Response:
    clear_history(session.get("user_id"))
    return redirect(url_for("index"))


@app.post("/admin/rebuild-demo")
def rebuild_demo() -> Response:
    create_demo_dataset()
    build_index()
    get_engine().reload()
    engine_stats(force=True)
    flash("演示数据和索引已重建")
    return redirect(url_for("index"))


def main() -> None:
    init_db()
    current_engine = get_engine()
    if not current_engine.documents:
        create_demo_dataset()
        current_engine.reload()
    debug = os.environ.get("FLASK_DEBUG") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    main()
