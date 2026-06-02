# 南开校内 Web 搜索引擎 HW4

本项目实现一个面向南开大学校内资源的垂直搜索引擎，覆盖网页抓取、文本索引、查询服务、个性化查询、Web 界面和个性化推荐。系统支持 **Elasticsearch 成熟召回后端**，也保留本地倒排索引兜底；无论候选来自 ES 还是本地索引，最终都由向量空间模型（TF-IDF 余弦相似度）结合 PageRank、新鲜度和个性化信号重排，满足作业对 VSM 与链接分析的要求。

## 环境

本项目使用 pixi 管理环境。

```powershell
cd 代码
$env:PIXI_HOME="C:\Users\kyc\.pixi"   # 如果 pixi 提示全局 config 路径带引号，先执行这一行
$env:PYTHONIOENCODING="utf-8"         # Windows 终端中文输出更稳
pixi install
```

## 快速运行

```powershell
pixi run init-demo
pixi run selfcheck
pixi run serve
```

浏览器打开 `http://127.0.0.1:5000`。

评分演示时可直接打开 `http://127.0.0.1:5000/personalization-demo`，同一查询会并排展示访客、本科生/教务兴趣、教师/学术兴趣三类画像下的排序差异和相关推荐。

## Elasticsearch 召回后端

ES 是可选但推荐的查询召回后端。未启动 ES 时，网站会自动显示“ES 未连接”并回退到本地索引；启动 ES 后，结果页可以切换 `Elasticsearch` 后端查看 ES 召回 + VSM 重排链路。

```powershell
# Windows 原生路径：脚本会查找已安装/已解压的 ES，启动后自动构建 ES 索引
.\scripts\start_es.ps1
pixi run serve
```

若本机尚未安装 ES，可以手动下载 Windows zip 版并设置 `ES_HOME`，或显式让脚本下载到纯英文路径的 `D:\Tools`（不存在时使用用户目录下的 `elastic-tools`）：

```powershell
.\scripts\start_es.ps1 -InstallIfMissing
```

也可以手动启动本机或远程已有的 Elasticsearch 服务后执行：

```powershell
pixi run build-es-index
$env:NKU_SEARCH_BACKEND="auto"
pixi run serve
```

默认地址为 `http://127.0.0.1:9200`，索引名为 `nku_search_pages`。可通过 `NKU_SEARCH_ES_URL`、`NKU_SEARCH_ES_INDEX` 修改。这里 pixi 管理 Python 依赖和 ES 客户端；Elasticsearch 服务本身是独立 Java 服务，可以使用学校机房/本机已安装实例，不依赖容器环境。CLI 也可显式选择后端：

```powershell
pixi run search -- --backend es "信息检索 filetype:pdf"
pixi run search -- --backend local "操作系统 site:cc.nankai.edu.cn"
```

## 命令行检索

```powershell
pixi run search -- "操作系统 site:cc.nankai.edu.cn"
pixi run search -- "信息检索 filetype:pdf"
pixi run search -- "\"南开 大学\""
pixi run search -- "温*"
pixi run search -- "计?"
```

## 校内抓取

当前真实语料已经抓取 132296 条南开域名文档，外链 0 条，覆盖 356 个南开主机。本轮在原有十万级语料基础上定向新增 32052 条高质量 HTML 页面；继续抓取时，不建议只盲目把总量刷到更大，应先补足教务、招生、就业、图书馆、学院和科研站点的覆盖，再重建索引。推荐先做定向 frontier 预检：

```powershell
pixi run targeted-crawl -- --dry-run
```

确认网络环境后可在当前 frontier 基础上继续增量追加：

```powershell
pixi run targeted-crawl -- --target-new 30000
pixi run build-index
pixi run build-es-index
```

普通抓取入口仍可使用：

```powershell
pixi run crawl -- --max-pages 100000 --delay 1.0 --flush-every 50
```

需要优先补足页面规模时可使用已提供的脚本。脚本会先定向扩展 frontier，目标提升到约 13 万条，并降低单主机并发，避免新数据集中在少数 WebPlus 站点：

```powershell
.\.pixi\envs\default\python.exe .\scripts\crawl_to_100k.py
pixi run build-index
pixi run build-es-index
```

爬虫策略：

- 只深入 `*.nankai.edu.cn`。
- 遵守 `robots.txt`。
- 默认单请求间隔 1 秒。
- 保存 HTML 快照到 `data/snapshots/`。
- 下载 PDF/DOCX/XLSX 到 `data/attachments/` 并解析入索引。
- 每抓取 50 条增量落盘一次，长时间抓取中断后不会丢失已保存数据。
- 定向增量会补齐核心站点种子，按主机配额轮转 frontier，并跳过 CAS/登录/跳转噪声 URL。
- ES 索引复用 title、body、anchor_text、URL、host、doc_type、snapshot_path、PageRank 等字段；VSM 重排仍在应用层完成。

## 查询功能对齐

| 作业要求 | 本项目实现 |
| --- | --- |
| 站内查询 | `site:` 语法和站点输入框 |
| 文档查询 | `filetype:` 语法和类型下拉框，支持 pdf/doc/docx/xls/xlsx |
| 短语查询 | `"南开 大学"` 或 `“南开 大学”` |
| 通配查询 | `*`、`?` 和 `/regex/` |
| 查询日志 | SQLite 保存登录用户查询历史 |
| 网页快照 | 搜索结果中的“快照”入口 |
| 个性化查询 | 注册时选择角色和兴趣标签，排序阶段 rerank |
| 个性化推荐 | 搜索联想和结果页相关推荐 |

## 生成说明文档和压缩包

```powershell
pixi run report -- --student-id 学号 --name 姓名
pixi run package -- --student-id 学号 --name 姓名
```

压缩包会按作业要求生成：

```text
学号_姓名_hw4.zip
├── 代码/
├── 说明文档/
└── 演示视频/
```

## 演示视频脚本

建议控制在 15 分钟以内：

| 时间 | 内容 |
| --- | --- |
| 0:00-1:00 | 主题和架构 |
| 1:00-3:00 | 初始化数据、抓取命令和索引文件 |
| 3:00-5:00 | 索引字段、分词、VSM 与 PageRank |
| 5:00-10:00 | 六项查询功能逐一演示 |
| 10:00-12:00 | 注册登录、个性化排序、推荐 |
| 12:00-14:00 | 查询日志、网页快照、附件下载 |
| 14:00-15:00 | 总结和不足 |

## 目录

```text
nku_search/
  crawler.py      礼貌爬虫
  parser.py       HTML/PDF/DOCX/XLSX 解析
  indexer.py      本地倒排索引和字段权重
  elasticsearch_backend.py  ES 召回与批量索引
  search.py       ES/本地召回 + VSM/PageRank/个性化排序
  database.py     用户、日志、点击记录
  web.py          Flask Web 应用
  cli.py          命令行入口
templates/        页面模板
static/           样式和前端脚本
tests/            功能测试
```
