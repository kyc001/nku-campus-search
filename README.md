# NKU Campus Search

> Recommended repository name: `nku-campus-search`
>
> GitHub description: A Nankai University campus vertical search engine with polite crawling, TF-IDF/VSM + PageRank ranking, Elasticsearch/local recall, Flask UI, snapshots, query logs, personalization, and recommendations.

NKU Campus Search is a course project for building a vertical search engine over Nankai University resources. It covers the full information retrieval pipeline: campus web crawling, document parsing, indexing, query parsing, ranking, web search UI, query history, snapshots, personalization, and recommendation.

The system can use Elasticsearch as a recall backend, while the final ranking remains in the application layer with TF-IDF vector space similarity, PageRank, freshness, and personalization signals. A local inverted index backend is also available as a fallback.

## Features

- Polite crawler scoped to `*.nankai.edu.cn`, with `robots.txt` checks and configurable request delay.
- HTML and attachment parsing for PDF, DOC, DOCX, XLS, and XLSX documents.
- Local inverted index plus optional Elasticsearch recall.
- TF-IDF/VSM ranking combined with PageRank, freshness, and personalization reranking.
- Advanced query support: `site:`, `filetype:`, phrase query, wildcard query, and regex query.
- Flask web UI with search results, cached snapshots, downloads, user login, query logs, and personalization.
- Recommendation support through query suggestions and profile-aware related results.
- Report and submission packaging scripts for the HW4 deliverables.

## Repository Layout

```text
.
├── 代码/                  # Python project managed by pixi
│   ├── nku_search/        # crawler, parser, indexer, search, web app, CLI
│   ├── templates/         # Flask HTML templates
│   ├── static/            # Web assets
│   ├── tests/             # pytest tests
│   ├── scripts/           # Elasticsearch and crawl helper scripts
│   ├── data/              # local corpus/index files, ignored by Git
│   ├── pixi.toml
│   └── README.md          # detailed Chinese running notes
├── report/                # Typst report and presentation sources
├── 说明文档/               # generated report materials and screenshots
├── 要求.md                 # original assignment requirements
└── README.md
```

## Quick Start

The project uses [pixi](https://pixi.sh/) for the Python environment.

```powershell
cd 代码
$env:PYTHONIOENCODING="utf-8"
pixi install
pixi run init-demo
pixi run selfcheck
pixi run serve
```

Open `http://127.0.0.1:5000` in a browser.

For a personalization demo, open:

```text
http://127.0.0.1:5000/personalization-demo
```

## Elasticsearch Backend

Elasticsearch is optional. When it is unavailable, the app falls back to the local index. On Windows, the helper script can start an existing Elasticsearch distribution or install one if requested.

```powershell
cd 代码
.\scripts\start_es.ps1
pixi run build-es-index
$env:NKU_SEARCH_BACKEND="auto"
pixi run serve
```

If Elasticsearch is not installed locally:

```powershell
.\scripts\start_es.ps1 -InstallIfMissing
```

The default Elasticsearch endpoint is `http://127.0.0.1:9200`, and the default index name is `nku_search_pages`. These can be changed with `NKU_SEARCH_ES_URL` and `NKU_SEARCH_ES_INDEX`.

## CLI Examples

```powershell
cd 代码
pixi run search -- "操作系统 site:cc.nankai.edu.cn"
pixi run search -- "信息检索 filetype:pdf"
pixi run search -- "\"南开 大学\""
pixi run search -- "温*"
pixi run search -- "计?"
pixi run search -- --backend es "信息检索 filetype:pdf"
pixi run search -- --backend local "操作系统 site:cc.nankai.edu.cn"
```

## Crawling And Indexing

The full local corpus and index files are large and are intentionally ignored by Git. Use the demo initializer for a lightweight run, or rebuild the corpus locally when needed.

```powershell
cd 代码
pixi run targeted-crawl -- --dry-run
pixi run targeted-crawl -- --target-new 30000
pixi run build-index
pixi run build-es-index
```

The crawler stores runtime data under `代码/data/`, including:

- `documents.jsonl`
- `search_index.json`
- `links.tsv`
- `frontier.txt`
- `snapshots/`
- `attachments/`
- `nku_search.sqlite3`

These files are excluded from the repository because they can be very large or machine-specific.

## Tests

```powershell
cd 代码
pixi run test
pixi run selfcheck
```

`selfcheck` runs an end-to-end verification over search, snapshots, downloads, personalization, and optional Elasticsearch behavior.

## Reports And Packaging

The report and presentation sources live in `report/`. To generate the assignment package:

```powershell
cd 代码
pixi run report -- --student-id 学号 --name 姓名
pixi run package -- --student-id 学号 --name 姓名
```

The generated package follows the HW4 submission layout:

```text
学号_姓名_hw4.zip
├── 代码/
├── 说明文档/
└── 演示视频/
```

Generated packages and local agent/workspace directories are ignored by Git. Before publishing publicly, check the report, screenshots, and generated materials for personal information.
