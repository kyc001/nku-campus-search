#set page(width: 16in, height: 9in, margin: 0.45in)
#set text(font: ("Microsoft YaHei", "SimHei", "Arial"), size: 22pt)
#set par(justify: false, leading: 1.08em)

#let slide(title, body) = {
  rect(width: 100%, height: 100%, inset: 28pt, stroke: none)[
    #text(size: 34pt, weight: "bold", fill: rgb("#123c69"))[#title]
    #v(16pt)
    #body
  ]
}

#let bullets(items) = {
  list(..items.map(item => [#item]))
}

#let ph(title) = rect(
  width: 100%,
  height: 3.1in,
  stroke: 1.2pt + rgb("#789"),
  fill: rgb("#f4f7fa"),
  radius: 8pt,
  inset: 16pt,
)[#align(center + horizon)[
  #text(size: 24pt, weight: "bold", fill: rgb("#456"))[#title]\
  #text(size: 15pt, fill: gray)[运行证据见报告与说明文档]
]]

#let shot(path) = image(path, width: 100%, height: 3.2in, fit: "contain")
#let bigshot(path) = image(path, width: 100%, height: 5.9in, fit: "contain")

#slide("南开校内 Web 搜索引擎")[
  #text(size: 26pt)[HW4 - Information Retrieval]\
  #v(12pt)
  面向南开校内资源的垂直搜索系统\
  Elasticsearch 召回 + 本地 VSM + PageRank + Flask\
  #v(20pt)
  #shot("./img/evidence/web-home.png")
]

#pagebreak()

#slide("作业要求对齐")[
  #bullets((
    [南开校内资源抓取，目标规模不少于 10 万页],
    [多字段文本索引：标题、URL、正文、锚文本、附件文本],
    [基于向量空间模型，结合链接分析排序],
    [六项查询：站内、文档、短语、通配、日志、快照],
    [登录用户个性化排序和个性化推荐],
  ))
]

#pagebreak()

#slide("总体架构")[
  #bullets((
    [检索层：Elasticsearch 召回候选，或本地倒排兜底],
    [排序层：VSM + PageRank + 新鲜度 + 个性化],
    [ES 不直接决定最终排序，避免默认 BM25 取代作业要求的 VSM],
  ))
  #v(10pt)
  #table(
    columns: (1.2fr, 2fr, 2fr),
    inset: 7pt,
    [阶段], [模块], [产物],
    [抓取], [`crawler.py`], [HTML、附件、快照],
    [索引], [`indexer.py` + ES], [本地索引、ES 索引],
    [排序], [`search.py`], [VSM + PageRank],
    [Web], [`web.py`], [查询、日志、快照、推荐],
  )
]

#pagebreak()

#slide("抓取与快照")[
  #bullets((
    [`*.nankai.edu.cn` 白名单],
    [遵守 `robots.txt`，按主机限速并支持断点续爬],
    [HTML 原文 gzip 保存为网页快照],
    [已抓取 132296 条文档，外链 0 条，覆盖 356 个南开主机],
    [本轮定向新增 32052 条高质量 HTML 页面，frontier 扩展到 384801 条],
    [PDF/DOC/DOCX/XLS/XLSX 附件解析入索引],
  ))
  #shot("./img/evidence/host-distribution.png")
]

#pagebreak()

#slide("索引与 VSM 排序")[
  #bullets((
    [分词：jieba 搜索模式 + 南开自定义词典],
    [ES 与本地索引共用 title、anchor、body、attachment],
    [ES 负责候选召回，未连接时自动本地兜底],
    [主排序：TF-IDF 余弦相似度],
    [链接分析：PageRank 作为排序增益],
    [主题意图 + 多词覆盖 + 标题质量修正],
    [结果去重 + 主机多样性，避免列表页霸屏],
  ))
  #v(10pt)
  $"score" = (sum_f w_f dot "sim"_f(q, d_f)) dot (1 + 0.5 log(1 + "PR"(d))) + 0.1 dot "fresh"(d)$
]

#pagebreak()

#slide("六项查询功能")[
  #table(
    columns: (1.4fr, 3.2fr),
    inset: 7pt,
    [功能], [示例],
    [站内查询], [`就业 实习 双选会 site:career.nankai.edu.cn`],
    [文档查询], [`国家级 实验教学示范中心 年度报告 filetype:pdf`],
    [站点查询], [`CNKI site:lib.nankai.edu.cn`],
    [通配查询], [`温*`, `计?`, `/信息.{0,2}/`],
    [查询日志], [登录后自动保存历史],
    [网页快照], [结果页点击“快照”],
  )
]

#pagebreak()

#slide("文档查询效果")[
  #bigshot("./img/evidence/web-filetype.png")
]

#pagebreak()

#slide("站内查询与摘要")[
  #bigshot("./img/evidence/web-employment.png")
]

#pagebreak()

#slide("个性化与推荐")[
  #bullets((
    [注册时选择角色和兴趣标签],
    [本科生/研究生偏 HTML 教务通知],
    [教师偏 PDF/DOCX/XLSX 学术文档],
    [`人工智能 学术 讲座` case 展示三类画像 Top1 差异],
    [搜索联想来自标题和高频词],
    [相关推荐显示兴趣命中、同主题、文档资源等推荐理由],
  ))
  #shot("./img/evidence/personalization-demo.png")
]

#pagebreak()

#slide("结果质量优化")[
  #bullets((
    [低质量页：CAS/登录/跳转、URL 标题、空正文页面自动降权],
    [摘要显示：按命中句子选段，跳过导航、版权和列表噪声],
    [文档查询：不可读 PDF 文件名优先回退到报告/通知类正文标题],
    [编码修复：自动修复 UTF-8 被误读造成的 CNKI 等乱码结果],
    [查询意图：就业、教务、招生、图书馆、科研等主题信号参与重排],
    [内容签名：`title + body[:200]` 合并重复导航/列表页],
    [前 60 条窗口内每个 host 最多 3 条，提升结果多样性],
    [摘要选择命中密度最高窗口，避开正文开头导航菜单],
  ))
]

#pagebreak()

#slide("Web 与 CLI 演示")[
  #bullets((
    [`pixi run selfcheck` 在 132296 条真实文档上自动验收],
    [`pixi run targeted-crawl -- --dry-run` 先检查定向增量 frontier],
    [`pixi run targeted-crawl -- --target-new 30000` 可在现有 frontier 上继续增量维护],
    [本机已有 ES 服务时，`pixi run build-es-index` 写入 ES 索引],
    [`pixi run search -- "国家级 实验教学示范中心 年度报告 filetype:pdf"` 命令行搜索],
    [`pixi run serve` 启动 Flask Web],
  ))
]

#pagebreak()

#slide("自检结果")[
  #shot("./img/evidence/selfcheck-pass.png")
  #v(8pt)
  132296 条文档上已覆盖：索引、六项查询、VSM、个性化、Web 路由。
]

#pagebreak()

#slide("提交材料与验证")[
  #bullets((
    [报告、PPT、讲解稿和抓取证据已放入 `说明文档/`],
    [保留 132296 条抓取统计、主机分布和 selfcheck 输出作为证据],
    [代码压缩包排除超大语料，报告与视频证明真实规模],
    [演示视频按 15 分钟以内脚本录制],
    [最终提交前用真实学号姓名重新运行 `pixi run package`],
  ))
]
