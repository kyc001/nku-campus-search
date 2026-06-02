from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import CODE_ROOT
from .storage import load_documents


def _register_font() -> str:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    ]
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("CNFont", str(path)))
                return "CNFont"
            except Exception:
                continue
    return "Helvetica"


def build_report(student_id: str = "学号", name: str = "姓名") -> Path:
    output_dir = CODE_ROOT.parent / "说明文档"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{student_id}_{name}_hw4.pdf"
    font = _register_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CNTitle", parent=styles["Title"], fontName=font, fontSize=20, leading=28))
    styles.add(ParagraphStyle(name="CNHeading", parent=styles["Heading2"], fontName=font, fontSize=14, leading=20, spaceBefore=12))
    styles.add(ParagraphStyle(name="CNBody", parent=styles["BodyText"], fontName=font, fontSize=10.5, leading=16))
    styles.add(ParagraphStyle(name="CNCode", parent=styles["Code"], fontName=font, fontSize=8.5, leading=12))

    docs = load_documents()
    doc_count = len(docs)
    html_count = sum(1 for doc in docs if doc.doc_type == "html")
    file_count = doc_count - html_count
    hosts = sorted({doc.host for doc in docs})

    story = [
        Paragraph("南开校内 Web 搜索引擎说明文档", styles["CNTitle"]),
        Paragraph(f"{student_id} {name}", styles["CNBody"]),
        Spacer(1, 0.3 * cm),
        Paragraph("1. 项目背景与主题", styles["CNHeading"]),
        Paragraph(
            "本项目面向南开大学校内资源构建垂直 Web 搜索引擎，主题为“综合性 + 附件友好”的南开资源检索。"
            "系统覆盖新闻、学校主页、学院通知、教务、图书馆、就业和社团等资源类型，并对 PDF、DOCX、XLSX 附件建立统一索引。",
            styles["CNBody"],
        ),
        Paragraph("2. 系统架构", styles["CNHeading"]),
        Paragraph(
            "系统由离线抓取与在线查询两部分组成。离线部分包括礼貌爬虫、HTML/附件解析、网页快照、倒排索引构建和 PageRank 链接分析；"
            "在线部分使用 Flask 提供 Web 界面、用户系统、查询日志、搜索建议、快照查看和个性化排序。",
            styles["CNBody"],
        ),
        Paragraph("3. 抓取与数据规模", styles["CNHeading"]),
        Paragraph(
            f"当前随包演示数据包含 {doc_count} 条文档，其中 HTML {html_count} 条，附件 {file_count} 条，覆盖站点: {', '.join(hosts)}。"
            "真实提交前可在校内网络执行 pixi run crawl -- --max-pages 100000 --delay 1.0 扩展到 10 万页面，爬虫遵守 robots.txt 并限制单域访问频率。",
            styles["CNBody"],
        ),
        Paragraph("4. 索引设计", styles["CNHeading"]),
        Paragraph(
            "索引字段包括 title、url、host、body、anchor_text、doc_type、attachment_text、outlinks、inlinks_count、pagerank、snapshot_path。"
            "中文分词采用 jieba 搜索模式，并加入南开、八里台、津南、信息检索、PageRank、计网等自定义词。",
            styles["CNBody"],
        ),
        Paragraph("5. 查询服务六项功能", styles["CNHeading"]),
    ]
    feature_rows = [
        ["功能", "实现方式", "示例"],
        ["站内查询", "解析 site: 或站点输入框并按 host 过滤", "人工智能 site:news.nankai.edu.cn"],
        ["文档查询", "解析 filetype: 或文件类型下拉框", "信息检索 filetype:pdf"],
        ["短语查询", "双引号/中文引号触发邻接短语匹配", "\"南开 大学\""],
        ["通配查询", "支持 *、? 和 /regex/ 正则", "温*、计?"],
        ["查询日志", "SQLite 保存登录用户历史，首页展示最近查询", "登录后搜索自动记录"],
        ["网页快照", "抓取时保存 gzip HTML，结果页提供快照入口", "点击结果中的“快照”"],
    ]
    table = Table(feature_rows, colWidths=[3 * cm, 8 * cm, 5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ]
        )
    )
    story.extend(
        [
            table,
            Paragraph("6. 排序算法", styles["CNHeading"]),
            Paragraph(
            "基础相关性采用向量空间模型（VSM）：对查询和文档字段使用 TF-IDF ltc 加权，并计算余弦相似度；"
                "链接分析使用 PageRank 迭代计算，并通过 log(1 + pagerank) 作为排序增益。",
            styles["CNBody"],
        ),
            Paragraph("7. 用户系统与个性化", styles["CNHeading"]),
            Paragraph(
                "系统支持注册、登录、角色和兴趣标签。排序阶段根据用户兴趣标签、角色、历史点击和当前查询进行轻量级 rerank，"
                "使本科生更容易看到教务通知，教师更容易看到 PDF/DOCX 等学术文档。",
                styles["CNBody"],
            ),
            Paragraph("8. 个性化推荐", styles["CNHeading"]),
            Paragraph(
                "推荐功能采用搜索联想与内容推荐：输入框通过 /api/suggest 返回标题和高频词建议；结果页根据当前查询词、用户兴趣和 PageRank 展示相关资源。",
                styles["CNBody"],
            ),
            Paragraph("9. 运行方式", styles["CNHeading"]),
            Paragraph(
                "进入“代码”目录后执行 pixi run init-demo 初始化演示数据，pixi run serve 启动 Web 界面，"
                "也可以执行 pixi run search -- \"信息检索 filetype:pdf\" 使用命令行搜索。",
                styles["CNBody"],
            ),
            Paragraph("10. 不足与改进", styles["CNHeading"]),
            Paragraph(
                "随包数据用于功能演示，真实评分前应在校内网络按要求完成 10 万级抓取并替换数据文件。后续可接入 Elasticsearch IK 分词器、"
                "增量抓取调度和更完整的附件解析兜底服务。",
                styles["CNBody"],
            ),
        ]
    )
    pdf = SimpleDocTemplate(str(output), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm)
    pdf.build(story)
    return output
