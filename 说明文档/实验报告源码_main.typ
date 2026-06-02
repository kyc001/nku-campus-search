#import "template.typ": project, indent

#show: project.with(
  course: "信息检索",
  lab_name: "HW4 - NKU Web Search Engine",
  stu_name: "姓名",
  stu_num: "学号",
  major: "专业",
  department: "学院",
  date: (2026, 5, 21),
  show_content_figure: false,
  watermark: "NKU",
)

#let evidence_image(path, title) = figure(
  image(path, width: 96%),
  caption: [#title],
)

= 项目背景与目标

本实验依据助教发布的《HW4 - NKU Web Search Engine》要求，面向#strong[南开大学校内资源]构建 Web 搜索引擎。系统目标包括网页抓取、文本索引、查询服务、个性化查询、Web 界面与个性化推荐。按照原文要求，查询排序以#strong[向量空间模型（VSM）]为核心，并融合链接分析结果。

本项目选择“综合性 + 附件友好”的南开校内资源搜索主题，覆盖南开新闻网、学校主页、计算机学院、教务、图书馆、学生就业、数学学院和 12 Club 等资源类型。助教鼓励复用成熟包，因此系统新增 Elasticsearch 作为可选查询召回后端，用于候选检索、过滤、短语和通配匹配；最终排序仍在应用层采用 TF-IDF 余弦 VSM、PageRank 和个性化重排。本地倒排索引作为可复现兜底，使未启动 ES 时也能完成演示。

#evidence_image("./img/evidence/web-home.png", "系统首页真实截图")

== 与作业要求的对应关系

#table(
  columns: (2.2fr, 4.8fr, 1.4fr),
  inset: 6pt,
  [作业要求], [本项目实现], [状态],
  [网页抓取], [礼貌爬虫，遵守 robots.txt，限制访问频率，保存 HTML 快照并解析 PDF/DOC/DOCX/XLS/XLSX 附件。当前真实语料已抓取 132296 条南开域名文档，本轮定向新增 32052 条高质量 HTML 页面。], [完成],
  [文本索引], [构建 title、url、body、anchor_text、doc_type、attachment_text 等多字段索引，并聚合入链锚文本。], [完成],
  [VSM + 链接分析], [使用 TF-IDF ltc 加权和余弦相似度作为主排序，融合 PageRank 和时间新鲜度。], [完成],
  [六项查询服务], [站内查询、文档查询、短语查询、通配查询、查询日志、网页快照全部实现。], [完成],
  [个性化查询], [注册/登录、角色、兴趣标签、查询历史和点击日志参与排序修正。], [完成],
  [个性化推荐], [实现搜索联想和结果页相关推荐。], [完成],
)

= 系统总体设计

系统分为离线处理和在线服务两部分。离线部分完成抓取、解析、快照保存、本地倒排索引构建、Elasticsearch 批量索引、锚文本聚合和 PageRank 计算；在线部分通过 Flask 提供 Web 页面、用户系统、查询接口、搜索建议、日志和快照查看。搜索时 ES 或本地索引先召回候选，再复用同一套 VSM 排序逻辑重排。

为充分利用成熟工具并满足作业的理论要求，本系统采用#strong[两阶段检索架构]：#strong[检索层（Retrieval）]默认采用助教鼓励使用的 Elasticsearch 完成倒排索引、分词、多字段 query DSL、短语、通配与过滤召回；同时保留纯 Python 本地倒排索引作为不依赖外部服务的降级路径。#strong[排序层（Ranking）]手实现向量空间模型（VSM），采用 ltc 加权 TF-IDF 与余弦相似度度量内容相关性，并与 PageRank、新鲜度、个性化信号联合产生最终打分。之所以不直接使用 ES 默认 BM25 作为最终排序，是因为 BM25 属概率检索模型，与作业明确要求的 VSM 不符；二阶段架构使系统同时具备 ES 的工程优势与 VSM 的理论合规性。

#figure(
  table(
    columns: (1.35fr, 2.2fr, 2.2fr),
    inset: 7pt,
    [阶段], [核心模块], [输出],
    [离线抓取], [`crawler.py` / `parser.py` / `snapshot.py`], [南开 HTML、附件文本、网页快照],
    [离线索引], [`indexer.py` / `pagerank.py` / `elasticsearch_backend.py`], [本地倒排索引、PageRank、可选 ES 索引],
    [在线检索], [`search.py` / `query.py`], [候选召回、VSM 重排、摘要和推荐],
    [Web 服务], [`web.py` / SQLite / templates], [搜索页面、登录、日志、快照、下载],
  ),
  caption: [系统架构与数据流],
)

核心目录结构如下：

```text
代码/
├── nku_search/
│   ├── crawler.py      礼貌爬虫与附件抓取
│   ├── parser.py       HTML/PDF/DOCX/XLSX 解析
│   ├── indexer.py      多字段索引和 IDF 统计
│   ├── elasticsearch_backend.py  ES 召回与批量索引
│   ├── search.py       ES/本地召回 + VSM 重排
│   ├── database.py     用户、查询日志、点击日志
│   ├── web.py          Flask Web 应用
│   └── selfcheck.py    自动验收脚本
├── templates/          页面模板
├── static/             样式和前端脚本
└── data/               文档、索引、快照、附件
```

= 网页抓取与数据准备

爬虫模块限定深入 `*.nankai.edu.cn`，使用 `RobotFileParser` 检查 `robots.txt`，通过 `delay` 参数限制同一主机的请求间隔，并设置课程作业专用 User-Agent。HTML 页面被解析出标题、正文、链接和锚文本；HTML 原文以 gzip 形式存入 `data/snapshots/`，作为网页快照来源。

附件抓取根据 URL 后缀或 Content-Type 判断类型，支持 PDF、DOC、DOCX、XLS、XLSX。PDF 使用 `pypdf` 提取文本，DOCX 使用 `python-docx`，XLSX 使用 `openpyxl`。解析后的附件文本与普通网页一起进入统一索引，从而支持文档查询。

#evidence_image("./img/evidence/host-distribution.png", "抓取主机分布证据")

当前真实抓取结果已经达到并超过助教要求的 10 万级规模。`data/documents.jsonl` 中共有 132296 条唯一文档，全部 URL 均位于南开域名内，涉及 356 个主机；其中 HTML 124844 条、PDF 3902 条、DOCX 1417 条、DOC 1411 条、XLSX 547 条、XLS 175 条。HTML 快照共 124844 份，附件或附件 URL 共 7452 条，索引文件 `data/search_index.json` 约 1.98 GB。本轮按用户要求完成定向补爬，新增 32052 条高质量 HTML 页面，frontier 继续扩展到 384801 条候选 URL，优先覆盖教务、招生、就业、图书馆、学院和科研相关站点。

为避免项目目录移动后旧绝对路径失效，读取文档元数据时会自动将 `data/snapshots/` 和 `data/attachments/` 下的历史路径重定位到当前代码目录。这样 `documents.jsonl` 与 `search_index.json` 即使在不同机器或不同课程目录中复制，网页快照和附件下载仍然能够正常打开。

大规模抓取不再只追求“再多几万条”，而是先做定向 frontier 预检。预检会合并核心站点种子、过滤 CAS/登录/跳转噪声 URL，并按主机配额重排队列，避免新增 3 万条集中来自单一 WebPlus 站点。本轮实际补爬时关闭附件下载，只抓取 HTML 正文页，避免 `_upload` 附件队列吞噬爬取预算：

```powershell
cd 代码
pixi run targeted-crawl -- --dry-run
pixi run targeted-crawl -- --target-new 30000
pixi run build-index
pixi run build-es-index
```

若需要继续维护语料，可在当前 132296 条基础上再次执行定向预检与增量抓取；若只需复现本轮流程，可执行：

```powershell
.\.pixi\envs\default\python.exe .\scripts\crawl_to_100k.py
.\.pixi\envs\default\python.exe -m nku_search.cli build-index
```

= 文本索引设计

索引字段包括：

- `title`：网页标题，权重最高；
- `body`：清洗后的网页正文；
- `anchor_text`：指向当前页面的入链锚文本；
- `url` 与 `host`：用于站内过滤和展示；
- `doc_type`：区分 html、pdf、docx、xlsx；
- `snapshot_path`：快照文件位置；
- `pagerank` 与 `inlinks_count`：链接分析特征。

中文分词采用 `jieba.lcut_for_search`，并加入南开、南开大学、八里台、津南、伯苓班、信息检索、向量空间模型、PageRank、计网、计算机网络等自定义词。索引构建阶段统计每个词的 df，保存平滑 IDF：

$
"idf"_t = log frac(N + 1, "df"_t + 1) + 1
$

在线服务可选择两种召回路径。本地路径直接使用 `term_docs` 倒排候选；Elasticsearch 路径将 `title`、`body`、`anchor_text`、`url`、`host`、`doc_type`、`snapshot_path`、`pagerank` 等字段批量写入 ES，通过 `multi_match`、`match_phrase`、通配和过滤 DSL 召回 top-K，再交给同一 VSM 函数重排。这样利用成熟查询组件降低高级检索复杂度，同时保留作业要求的 VSM 主排序可解释性。

= VSM 排序与链接分析

助教要求明确写出“基于向量空间模型，结合链接分析结果对查询结果排序”。因此本系统主排序采用 VSM，而不是把 BM25 作为核心模型。对查询和文档字段使用 ltc 风格的 TF-IDF：

$
w_(t,d) = (1 + log "tf"_(t,d)) dot log frac(N, "df"_t)
$

查询向量与文档字段向量的相似度使用余弦相似度：

$
"sim"(q,d_f) = frac(bold(q) dot bold(d_f), ||bold(q)|| ||bold(d_f)||)
$

多字段融合时，标题、锚文本、正文、附件文本分别设置权重：

$
S_"vsm"(q,d) = sum_f w_f dot "sim"_f(q,d)
$

链接分析使用 PageRank。抓取阶段记录页面出链，离线迭代得到归一化 PageRank。最终排序公式为：

$
"score"(q,d) = S_"vsm"(q,d) dot (1 + alpha log(1 + hat("PR"(d)))) + beta dot "fresh"(d) + gamma dot "pers"(u,d)
$

其中默认参数为 $w_"title"=4$、$w_"anchor"=3$、$w_"attachment"=1.5$、$w_"body"=1$、$alpha=0.5$、$beta=0.1$、$gamma=0.3$。`fresh(d)` 是抓取时间的新鲜度，`pers(u,d)` 是登录用户偏好带来的轻量修正。ES 召回返回的候选文档不会直接使用 ES 分数作为最终排名，而是进入上述 VSM + PageRank 公式重新打分。新版排序还增加查询意图、精确短语、多词覆盖和标题质量修正信号：例如“就业”“选课”“图书馆”等查询会提升对应主题页面；CAS 登录页、URL 标题页和空正文页被降权；不可读文件名的 PDF 会优先用正文首个有效句子作为展示标题。

#figure(
  table(
    columns: (1.2fr, 2.7fr, 2.2fr),
    inset: 7pt,
    [排序信号], [实现位置], [作用],
    [VSM], [`search.py` 中 `_vsm_score`、`_field_cosine`], [TF-IDF 余弦相似度，作为主相关性分数],
    [PageRank], [`pagerank.py` 离线计算，`search.py` 融合], [结合链接分析结果提升权威页面],
    [新鲜度], [`search.py` 中 `_freshness_boost`], [轻量提升较新页面],
    [个性化], [`database.py` + `search.py`], [按角色、兴趣和点击历史微调排序],
    [多样性], [`search.py` 中 `_apply_result_diversity`], [合并重复列表页，限制单 host 霸屏],
    [质量修正], [`search.py` 中 `_is_low_quality_page`、`_term_coverage`], [压低登录页与弱标题，突出多词覆盖和主题匹配],
  ),
  caption: [VSM + PageRank 排序证据],
)

= 检索质量优化

大规模校内站点中存在三个影响演示体验的问题：一是部分 WebPlus 站点会生成大量标题相同、正文前缀几乎一致的导航页；二是网页正文开头常包含“首页、学院概况、通知公告”等菜单文本，传统从第一次命中位置截取摘要时，结果页容易显示无关导航内容；三是登录跳转页、CAS 回调页、URL 标题页和编码文件名附件会进入索引，如果不处理，即使抓取 10 万甚至更多页面，也很难形成有效检索。

为此，排序后增加了结果级去重和主机多样性约束。系统使用 `title + body[:200]` 的 MD5 作为内容签名，相同签名只保留当前排序分最高的一条；随后在前 60 条候选窗口中限制同一 host 最多出现 3 条，超过部分并不删除，而是顺延到窗口之后。这样既保留完整召回，又避免某一个站点的列表页占满首页。

摘要生成也由“第一次命中”改为“命中密度最高窗口”。系统扫描全部查询词出现位置，以每个命中点为锚生成候选窗口，按“窗口内不同查询词数 ×3 + 命中总次数”打分，并对文档前 120 字符的典型导航区扣分。最终摘要更容易展示正文中的有效信息，页面中仍用 `<mark>` 高亮查询词。新版结果页会直接展示 VSM、PageRank、主题匹配、精确匹配、多词覆盖、个性化和标题质量修正等排序信号，便于解释为什么某条结果靠前。

= 六项查询服务实现

== 站内查询

站内查询解析 `site:` 语法或页面中的站点输入框。例如：

```text
就业 实习 双选会 site:career.nankai.edu.cn
```

后端将 `site:` 后的 host 作为过滤条件，只保留对应站点的结果，再对剩余 query 走 VSM 排序。

== 文档查询

文档查询解析 `filetype:` 语法或类型下拉框。例如：

```text
国家级 实验教学示范中心 年度报告 filetype:pdf
```

系统根据 `doc_type` 字段过滤 PDF/DOCX/XLSX/HTML，并在结果页展示文件类型徽标和下载入口。

== 短语查询

短语查询支持英文双引号和中文引号。例如：

```text
"南开 大学"
```

系统要求短语中的 term 在文本中保持邻接关系，因此 `"南开 大学"` 与 `"南开 是一所综合性大学"` 会被区别对待。

== 通配查询

通配查询支持 `*`、`?` 和正则语法。例如：

```text
温*
计?
/信息.{0,2}/
```

通配符会被转换成正则表达式，并在标题、正文、锚文本和 URL 中匹配，命中标题的结果获得更高排序信号。

== 查询日志

用户登录后，每次搜索会写入 SQLite 的 `query_log` 表。首页展示最近查询历史，并提供清空历史按钮。点击搜索结果时，前端通过 `/api/click` 写入点击日志，为后续个性化排序提供依据。

== 网页快照

抓取时保存 HTML 原文至 `snapshots/{md5(url)}.html.gz`。搜索结果页提供“快照”按钮，后端读取本地快照，注入顶部横幅展示抓取时间和原始 URL，并重写相对链接为绝对链接。

下图选用 `就业 实习 双选会 site:career.nankai.edu.cn` 作为更显著的展示 case。首位结果直接命中“南开大学2026年就业实习双选会”，摘要展示时间、地点和正文说明，三个查询词全部高亮；site 过滤、快照入口、VSM + PageRank、多词覆盖和列表页降权信号都能在结果卡片中直接观察。

#evidence_image("./img/evidence/web-employment.png", "就业双选会站内查询与摘要优化截图")

#evidence_image("./img/evidence/web-filetype.png", "PDF 文档查询与摘要优化截图")

#evidence_image("./img/evidence/web-phrase.png", "CNKI 站点检索与乱码修复截图")

= 用户系统、个性化与推荐

系统提供注册、登录、退出功能。注册时用户选择角色（本科生、研究生、教师、校友、访客）和兴趣标签（新闻、教务、学术、招聘、文体、院系、图书馆、计算机）。排序阶段根据以下因素修正：

- 兴趣标签命中文档标签或标题正文时上提；
- 本科生和研究生更偏 HTML 教务通知；
- 教师更偏 PDF/DOCX/XLSX 学术与文档资源；
- 历史点击过的 URL 轻量上提。

个性化推荐包含两部分：输入框搜索联想来自标题和高频词；结果页相关推荐根据当前查询词、用户兴趣、角色偏好、资源类型和 PageRank 选取相关文档，并显示“兴趣命中、同主题、文档资源、站内权威”等推荐理由。演示页使用 `人工智能 学术 讲座` 等 case 对比访客、本科生和教师画像，可以看到同一查询下三类画像的 Top1、Top10 类型分布和相关推荐均出现可解释差异。

#evidence_image("./img/evidence/personalization-demo.png", "个性化排序与推荐演示截图")

#evidence_image("./img/evidence/web-snapshot.png", "网页快照真实截图")

= Web 界面与 CLI

Web 界面以功能为主，包含首页、结果页、快照页、登录页、注册页和接口路由。主要路由如下：

#table(
  columns: (2fr, 1.4fr, 4fr),
  inset: 6pt,
  [路由], [方法], [说明],
  [`/`], [GET], [搜索首页和查询历史],
  [`/search`], [GET], [搜索结果页],
  [`/snapshot`], [GET], [网页快照],
  [`/api/suggest`], [GET], [搜索联想],
  [`/api/stats`], [GET], [语料规模与后端状态],
  [`/personalization-demo`], [GET], [访客、学生、教师三类画像排序对比],
  [`/api/click`], [POST], [点击日志],
  [`/login`, `/register`, `/logout`], [GET/POST], [用户系统],
)

命令行入口由 `python -m nku_search.cli` 提供，pixi 中封装了常用任务：

```powershell
pixi run init-demo
pixi run selfcheck
pixi run search -- "国家级 实验教学示范中心 年度报告 filetype:pdf"
pixi run serve
// 已有本机 ES 服务时，再执行下面的导入命令
pixi run build-es-index
.\.pixi\envs\default\python.exe .\scripts\crawl_to_100k.py
```

= 自检结果

项目提供 `selfcheck.py` 自动验收脚本，覆盖索引、六项查询、VSM、个性化和 Web 路由。当前自检输出如下：

```text
[index] documents >= 2000          PASS 132296
[query] site                       PASS
[query] filetype                   PASS
[query] phrase                     PASS
[query] wildcard                   PASS
[query] regex                      PASS
[query] snapshot render            PASS
[query] attachment file            PASS
[ranking] VSM cosine               PASS cos=1.000
[elastic] optional recall DSL      PASS
[personalize] ranking/recommend    PASS
[web] index                        PASS
[web] search                       PASS
[web] suggest                      PASS
[web] snapshot                     PASS
[web] download                     PASS
ALL PASS - ready to submit.
```

#evidence_image("./img/evidence/selfcheck-pass.png", "selfcheck 全部通过截图")

= 不足与后续改进

第一，当前系统已经完成 132296 条真实南开文档抓取，并额外完成 32052 条高质量 HTML 定向补爬；最终提交时应保留抓取统计、自检输出和 Web 页面截图作为评分证据。第二，当前 ES 召回使用内置 analyzer 即可演示；后续若追求更好的中文召回质量，可以接入 IK 分词器、completion suggester 和查询缓存。第三，当前附件解析覆盖 PDF/DOC/DOCX/XLS/XLSX，旧版 Office 文档的文本抽取质量仍可通过 Apache Tika 或 LibreOffice 进一步增强。

总体而言，系统已按助教原文完成核心模块：礼貌抓取、多字段索引、VSM + PageRank 排序、六项查询服务、个性化查询、Web 界面和个性化推荐。
