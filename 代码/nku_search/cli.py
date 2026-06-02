from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from .config import CODE_ROOT, DOCUMENTS_PATH, INDEX_PATH, SEEDS_PATH
from .crawler import crawl_from_file
from .database import init_db
from .demo_data import create_demo_dataset
from .elasticsearch_backend import ElasticsearchBackend
from .frontier import expand_frontier, read_frontier
from .indexer import build_index, load_index
from .report import build_report
from .search import SearchEngine


def copy_report_artifacts(target_dir: Path, student: str) -> Path | None:
    report_dir = CODE_ROOT.parent / "report"
    copied_pdf: Path | None = None
    artifacts = [
        ("main.pdf", f"{student}.pdf"),
        ("main.typ", "实验报告源码_main.typ"),
        ("ppt.pdf", f"{student}_ppt.pdf"),
        ("ppt.typ", "PPT源码_ppt.typ"),
        ("讲解稿.md", "讲解稿.md"),
    ]
    for src_name, dst_name in artifacts:
        src = report_dir / src_name
        if src.exists():
            dst = target_dir / dst_name
            shutil.copy2(src, dst)
            if src_name == "main.pdf":
                copied_pdf = dst
    return copied_pdf


def copy_dir_contents(src_dir: Path, dst_dir: Path, ignore=None) -> None:
    if not src_dir.exists():
        return
    for item in src_dir.iterdir():
        target = dst_dir / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if item.is_dir():
            shutil.copytree(item, target, ignore=ignore)
        else:
            shutil.copy2(item, target)


def init_demo(_: argparse.Namespace) -> int:
    docs = create_demo_dataset()
    init_db()
    print(f"已生成演示数据 {len(docs)} 条，索引文件: {INDEX_PATH}")
    return 0


def rebuild_index(_: argparse.Namespace) -> int:
    index = build_index()
    print(f"索引完成: {len(index.documents)} 条文档，平均长度 {index.avg_len:.1f}")
    return 0


def do_search(args: argparse.Namespace) -> int:
    engine = SearchEngine(backend=args.backend)
    query = " ".join(args.query) if args.query else input("Query: ")
    response = engine.search(query, page=args.page, filetype=args.filetype, site=args.site, backend=args.backend)
    print(f"命中 {response.total} 条，用时 {response.elapsed_ms:.1f} ms，召回后端 {response.backend}")
    for idx, result in enumerate(response.results, start=1):
        doc = result.document
        print(f"{idx}. [{doc.doc_type}] {doc.title} ({result.score:.3f})")
        print(f"   {doc.url}")
        print(f"   {result.snippet.replace('<mark>', '[').replace('</mark>', ']')}")
    return 0


def build_es_index(_: argparse.Namespace) -> int:
    index = load_index()
    backend = ElasticsearchBackend(enabled=True)
    count = backend.rebuild(index)
    print(f"Elasticsearch 索引完成: {count} 条文档 -> {backend.url}/{backend.index_name}")
    return 0


def do_crawl(args: argparse.Namespace) -> int:
    seed_file = Path(args.seeds)
    if not seed_file.exists():
        print(f"种子文件不存在: {seed_file}", file=sys.stderr)
        return 2
    docs = crawl_from_file(
        seed_file,
        max_pages=args.max_pages,
        delay=args.delay,
        flush_every=args.flush_every,
        workers=args.workers,
        timeout=args.timeout,
    )
    build_index()
    print(f"抓取完成，本次新增/更新 {len(docs)} 条。数据文件: {DOCUMENTS_PATH}")
    return 0


def do_expand_frontier(args: argparse.Namespace) -> int:
    added = expand_frontier(limit=args.limit)
    print(f"frontier 定向扩容完成，新增候选 URL {added} 条")
    return 0


def count_document_lines(path: Path = DOCUMENTS_PATH) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def do_targeted_crawl(args: argparse.Namespace) -> int:
    frontier_limit = args.frontier_limit
    if args.dry_run:
        frontier_limit = min(frontier_limit, 10_000)
    added = expand_frontier(limit=frontier_limit, fast=args.dry_run)
    if args.dry_run:
        total = len(read_frontier())
        print(f"定向抓取预检完成：新增候选 {added} 条，frontier 当前 {total} 条。")
        print("确认网络环境后可去掉 --dry-run，或运行：pixi run targeted-crawl -- --target-new 30000")
        return 0
    current_total = count_document_lines()
    target_total = current_total + max(args.target_new, 1)
    seed_file = Path(args.seeds)
    docs = crawl_from_file(
        seed_file,
        max_pages=target_total,
        delay=args.delay,
        flush_every=args.flush_every,
        workers=args.workers,
        timeout=args.timeout,
        crawl_attachments=args.crawl_attachments,
        max_host_active=args.max_host_active,
    )
    build_index()
    if args.build_es:
        build_es_index(args)
    print(f"定向增量抓取完成，frontier 新增候选 {added} 条，本次返回 {len(docs)} 条。")
    return 0


def do_report(args: argparse.Namespace) -> int:
    output = build_report(student_id=args.student_id, name=args.name)
    print(f"说明文档已生成: {output}")
    return 0


def package_submit(args: argparse.Namespace) -> int:
    student = f"{args.student_id}_{args.name}_hw4"
    root = CODE_ROOT.parent
    package_dir = root / student
    if package_dir.exists():
        resolved_root = root.resolve()
        resolved_package = package_dir.resolve()
        if resolved_root not in resolved_package.parents:
            raise RuntimeError(f"refuse to remove unexpected path: {resolved_package}")
        shutil.rmtree(package_dir)
    (package_dir / "代码").mkdir(parents=True)
    (package_dir / "说明文档").mkdir(parents=True)
    (package_dir / "演示视频").mkdir(parents=True)
    ignore = shutil.ignore_patterns(
        ".pixi",
        ".pytest_cache",
        "tmp",
        "__pycache__",
        "*.pyc",
        "*.sqlite3-journal",
        "*.tmp",
        "documents.jsonl",
        "links.tsv",
        "nku_search.sqlite3",
        "search_index.json",
        "snapshots",
        "attachments",
        "crawl-*.log",
        "*.err.log",
        "web.log",
    )
    skip_root = {".pixi", ".pytest_cache", "tmp"}
    for item in CODE_ROOT.iterdir():
        if item.name in skip_root:
            continue
        target = package_dir / "代码" / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=ignore)
        else:
            shutil.copy2(item, target)
    copy_dir_contents(root / "说明文档", package_dir / "说明文档")
    copy_dir_contents(root / "演示视频", package_dir / "演示视频")
    copied_pdf = copy_report_artifacts(package_dir / "说明文档", student)
    if student != "学号_姓名_hw4":
        for stale_name in ("学号_姓名_hw4.pdf", "学号_姓名_hw4_ppt.pdf"):
            stale = package_dir / "说明文档" / stale_name
            if stale.exists():
                stale.unlink()
    if copied_pdf is None:
        report_path = build_report(student_id=args.student_id, name=args.name)
        shutil.copy2(report_path, package_dir / "说明文档" / f"{student}.pdf")
    readme_video = package_dir / "演示视频" / "视频录制说明.txt"
    readme_video.write_text(
        "请按 README.md 中的 15 分钟脚本录制演示视频，并将视频文件放在本目录后再提交。\n",
        encoding="utf-8",
    )
    zip_path = root / f"{student}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in package_dir.rglob("*"):
            zf.write(file, file.relative_to(package_dir))
    print(f"提交压缩包已生成: {zip_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="南开校内 Web 搜索引擎 HW4")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-demo").set_defaults(func=init_demo)
    sub.add_parser("build-index").set_defaults(func=rebuild_index)
    sub.add_parser("build-es-index").set_defaults(func=build_es_index)

    search = sub.add_parser("search")
    search.add_argument("query", nargs="*")
    search.add_argument("--site", default="")
    search.add_argument("--filetype", default="")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--backend", choices=["auto", "local", "es"], default="auto")
    search.set_defaults(func=do_search)

    crawl = sub.add_parser("crawl")
    crawl.add_argument("--seeds", default=str(SEEDS_PATH))
    crawl.add_argument("--max-pages", type=int, default=1000)
    crawl.add_argument("--delay", type=float, default=1.0)
    crawl.add_argument("--flush-every", type=int, default=50)
    crawl.add_argument("--workers", type=int, default=8)
    crawl.add_argument("--timeout", type=float, default=10.0)
    crawl.set_defaults(func=do_crawl)

    expand = sub.add_parser("expand-frontier")
    expand.add_argument("--limit", type=int, default=100000)
    expand.set_defaults(func=do_expand_frontier)

    targeted = sub.add_parser("targeted-crawl")
    targeted.add_argument("--seeds", default=str(SEEDS_PATH))
    targeted.add_argument("--target-new", type=int, default=30_000)
    targeted.add_argument("--frontier-limit", type=int, default=120_000)
    targeted.add_argument("--delay", type=float, default=0.12)
    targeted.add_argument("--flush-every", type=int, default=200)
    targeted.add_argument("--workers", type=int, default=96)
    targeted.add_argument("--timeout", type=float, default=2.5)
    targeted.add_argument("--max-host-active", type=int, default=3)
    targeted.add_argument("--crawl-attachments", action="store_true")
    targeted.add_argument("--build-es", action="store_true")
    targeted.add_argument("--dry-run", action="store_true")
    targeted.set_defaults(func=do_targeted_crawl)

    report = sub.add_parser("build-report")
    report.add_argument("--student-id", default="学号")
    report.add_argument("--name", default="姓名")
    report.set_defaults(func=do_report)

    package = sub.add_parser("package-submit")
    package.add_argument("--student-id", default="学号")
    package.add_argument("--name", default="姓名")
    package.set_defaults(func=package_submit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
