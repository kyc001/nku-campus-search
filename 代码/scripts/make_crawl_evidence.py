from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CODE_ROOT = ROOT / "代码"
DATA_DIR = CODE_ROOT / "data"
OUT_DIR = ROOT / "说明文档" / "抓取证据"


def load_docs() -> list[dict]:
    index_path = DATA_DIR / "search_index.json"
    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("documents", [])


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def draw_host_distribution(host_counts: Counter[str]) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return

    items = host_counts.most_common(30)
    width, height = 1200, 780
    margin_l, margin_r, margin_t, margin_b = 300, 50, 60, 60
    bar_h = 18
    gap = 6
    max_count = max((count for _, count in items), default=1)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("msyh.ttc", 18)
        title_font = ImageFont.truetype("msyh.ttc", 28)
    except Exception:
        font = ImageFont.load_default()
        title_font = font

    draw.text((margin_l, 18), "Top 30 hosts by crawled documents", fill=(30, 45, 65), font=title_font)
    x0 = margin_l
    x1 = width - margin_r
    y = margin_t
    for host, count in items:
        bar_w = int((x1 - x0) * count / max_count)
        draw.text((20, y - 2), host[:38], fill=(30, 45, 65), font=font)
        draw.rectangle((x0, y, x0 + bar_w, y + bar_h), fill=(55, 105, 160))
        draw.text((x0 + bar_w + 8, y - 2), str(count), fill=(30, 45, 65), font=font)
        y += bar_h + gap

    image.save(OUT_DIR / "host_distribution.png")
    image.save(OUT_DIR / "host-distribution.png")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    docs = load_docs()
    type_counts = Counter((doc.get("doc_type") or "unknown").lower() for doc in docs)
    host_counts = Counter((doc.get("host") or "unknown").lower() for doc in docs)
    snapshot_count = sum(1 for doc in docs if doc.get("snapshot_path"))
    attachment_count = sum(1 for doc in docs if doc.get("attachment_path") or doc.get("attachment_url"))
    external_count = sum(1 for doc in docs if "nankai.edu.cn" not in (doc.get("host") or "").lower())
    docs_path = DATA_DIR / "documents.jsonl"
    index_path = DATA_DIR / "search_index.json"

    stats_lines = [
        "NKU Web Search Engine crawl evidence",
        "",
        f"documents: {len(docs)}",
        f"external_count: {external_count}",
        f"hosts: {len(host_counts)}",
        f"html_snapshots: {snapshot_count}",
        f"attachments_or_attachment_urls: {attachment_count}",
        f"documents_jsonl_bytes: {docs_path.stat().st_size if docs_path.exists() else 0}",
        f"search_index_json_bytes: {index_path.stat().st_size if index_path.exists() else 0}",
        "",
        "doc_type_distribution:",
    ]
    stats_lines.extend(f"  {doc_type}: {count}" for doc_type, count in type_counts.most_common())
    write_text(OUT_DIR / "stats.txt", "\n".join(stats_lines) + "\n")

    host_lines = [f"{count}\t{host}" for host, count in host_counts.most_common(30)]
    write_text(OUT_DIR / "host_top30.txt", "\n".join(host_lines) + "\n")

    logs = sorted(
        [*DATA_DIR.glob("crawl-*.log"), *DATA_DIR.glob("targeted-crawl-*.log")],
        key=lambda path: path.stat().st_mtime,
    )
    if logs:
        latest = logs[-1]
        lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()
        sample = "\n".join(lines[-200:])
        write_text(OUT_DIR / "crawl_log_sample.txt", sample + "\n")

    draw_host_distribution(host_counts)
    print(f"wrote crawl evidence to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
