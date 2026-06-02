from nku_search.indexer import SearchIndex
from nku_search.config import DATA_DIR, DOCUMENTS_PATH
from nku_search.models import Document
from nku_search.search import SearchEngine, _display_title, _is_listing_page, _is_low_quality_page, _is_readable_title
from nku_search.demo_data import create_demo_dataset
from nku_search.text import make_snippet


def has_enough_documents(minimum: int = 2000) -> bool:
    if not DOCUMENTS_PATH.exists():
        return False
    count = 0
    with DOCUMENTS_PATH.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                count += 1
                if count >= minimum:
                    return True
    return False


def setup_module() -> None:
    if not has_enough_documents():
        create_demo_dataset()


def tiny_engine() -> SearchEngine:
    docs = [
        Document(
            id="1",
            url="https://news.nankai.edu.cn/wen",
            title="温家宝访问南开",
            body="温家宝校友回到南开大学。",
            host="news.nankai.edu.cn",
            doc_type="html",
        ),
        Document(
            id="2",
            url="https://cc.nankai.edu.cn/course",
            title="操作系统课程",
            body="计算机学院课程资料。",
            host="cc.nankai.edu.cn",
            doc_type="html",
        ),
        Document(
            id="3",
            url="https://jwc.nankai.edu.cn/xk",
            title="本科生课程选课通知",
            body=(
                "教务部发布本科生课程选课与考试安排通知。"
                "本次选课面向全校本科生，包含专业必修课、通识选修课和考试时间说明。"
                "请学生在规定时间登录系统完成课程确认。"
                "如遇课程容量、退补选或培养方案问题，请及时联系所在学院教学办公室。"
            ),
            host="jwc.nankai.edu.cn",
            doc_type="html",
            tags=["教务"],
            pagerank=1.0,
        ),
        Document(
            id="4",
            url="https://lib.nankai.edu.cn/cnki.pdf",
            title="中国知网 CNKI 数据库使用指南",
            body="图书馆数据库资源检索指南，面向教师科研与学术论文写作。",
            host="lib.nankai.edu.cn",
            doc_type="pdf",
            tags=["图书馆", "学术"],
            pagerank=1.2,
        ),
    ]
    index = SearchIndex(
        documents=[doc.to_dict() for doc in docs],
        indexed_documents={
            "1": {
                "id": "1",
                "tf": {"温家宝": 2, "南开": 1, "大学": 1},
                "title_tf": {"温家宝": 1, "南开": 1},
                "anchor_tf": {},
                "body_tf": {"温家宝": 1, "南开": 1, "大学": 1},
                "attachment_tf": {},
                "weighted_tf": {"温家宝": 2, "南开": 2, "大学": 1},
                "length": 4,
                "title_norm": 1.0,
                "anchor_norm": 0.0,
                "body_norm": 1.0,
                "attachment_norm": 0.0,
            },
            "2": {
                "id": "2",
                "tf": {"操作系统": 1, "课程": 2},
                "title_tf": {"操作系统": 1, "课程": 1},
                "anchor_tf": {},
                "body_tf": {"课程": 1},
                "attachment_tf": {},
                "weighted_tf": {"操作系统": 4, "课程": 2},
                "length": 3,
                "title_norm": 1.0,
                "anchor_norm": 0.0,
                "body_norm": 1.0,
                "attachment_norm": 0.0,
            },
            "3": {
                "id": "3",
                "tf": {"本科生": 1, "选课": 2, "通知": 1, "课程": 1, "考试": 1, "教务": 1},
                "title_tf": {"本科生": 1, "课程": 1, "选课": 1, "通知": 1},
                "anchor_tf": {},
                "body_tf": {"教务": 1, "本科生": 1, "课程": 1, "选课": 1, "考试": 1, "通知": 1},
                "attachment_tf": {},
                "weighted_tf": {"本科生": 4, "选课": 5, "通知": 4, "课程": 1, "考试": 1, "教务": 1},
                "length": 7,
                "title_norm": 1.0,
                "anchor_norm": 0.0,
                "body_norm": 1.0,
                "attachment_norm": 0.0,
            },
            "4": {
                "id": "4",
                "tf": {"中国": 1, "知网": 1, "cnki": 1, "数据库": 2, "图书馆": 1, "科研": 1, "学术": 1, "论文": 1},
                "title_tf": {"中国": 1, "知网": 1, "cnki": 1, "数据库": 1, "指南": 1},
                "anchor_tf": {},
                "body_tf": {"图书馆": 1, "数据库": 1, "资源": 1, "检索": 1, "教师": 1, "科研": 1, "学术": 1, "论文": 1},
                "attachment_tf": {"数据库": 1, "科研": 1, "学术": 1},
                "weighted_tf": {"中国": 4, "知网": 4, "cnki": 4, "数据库": 6, "图书馆": 1, "科研": 2, "学术": 2, "论文": 1},
                "length": 9,
                "title_norm": 1.0,
                "anchor_norm": 0.0,
                "body_norm": 1.0,
                "attachment_norm": 1.0,
            },
        },
        idf={
            "温家宝": 1.0,
            "南开": 1.0,
            "大学": 1.0,
            "操作系统": 1.0,
            "课程": 1.0,
            "本科生": 1.0,
            "选课": 1.0,
            "通知": 1.0,
            "考试": 1.0,
            "教务": 1.0,
            "中国": 1.0,
            "知网": 1.0,
            "cnki": 1.0,
            "数据库": 1.0,
            "图书馆": 1.0,
            "科研": 1.0,
            "学术": 1.0,
            "论文": 1.0,
        },
        avg_len=3.5,
        suggestions=["温家宝访问南开", "操作系统课程", "本科生选课通知", "中国知网 CNKI 数据库使用指南"],
        term_docs={
            "温家宝": ["1"],
            "南开": ["1"],
            "大学": ["1"],
            "操作系统": ["2"],
            "课程": ["2", "3"],
            "本科生": ["3"],
            "选课": ["3"],
            "通知": ["3"],
            "考试": ["3"],
            "教务": ["3"],
            "中国": ["4"],
            "知网": ["4"],
            "cnki": ["4"],
            "数据库": ["4"],
            "图书馆": ["4"],
            "科研": ["4"],
            "学术": ["4"],
            "论文": ["4"],
        },
    )
    return SearchEngine(index=index, backend="local")


def test_site_search() -> None:
    response = SearchEngine().search("操作系统 site:cc.nankai.edu.cn")
    assert response.total >= 1
    assert all("cc.nankai.edu.cn" in item.document.host for item in response.results)


def test_filetype_search() -> None:
    response = SearchEngine().search("信息检索 filetype:pdf")
    assert response.total >= 1
    assert response.results[0].document.doc_type == "pdf"


def test_phrase_search() -> None:
    response = SearchEngine().search('"南开 大学"')
    assert response.total >= 1


def test_wildcard_search() -> None:
    response = SearchEngine().search("温*")
    assert response.total >= 1
    assert "温" in response.results[0].document.title


def test_query_context_precompiles_patterns() -> None:
    engine = tiny_engine()
    parsed = engine.parse("\u6e29*")
    runtime = engine.prepare_runtime(parsed)

    assert runtime.pattern_re is not None
    assert runtime.pattern_re.search("\u6e29\u5bb6\u5b9d\u8bbf\u95ee\u5357\u5f00")


def test_local_wildcard_candidates_are_narrowed() -> None:
    engine = tiny_engine()
    parsed = engine.parse("\u6e29*")
    candidates = engine._local_candidate_doc_ids(parsed)

    assert candidates == ["1"]


def test_anonymous_search_has_no_personal_boost() -> None:
    engine = tiny_engine()
    doc = engine.documents["1"]

    assert engine._personal_boost(doc, None, doc.title) == 0.0


def test_document_lookup_by_url_is_constant_time_api() -> None:
    engine = tiny_engine()

    assert engine.document_by_url("https://news.nankai.edu.cn/wen").id == "1"
    assert engine.document_by_url("https://news.nankai.edu.cn/missing") is None


def test_recommendation_titles_filter_encoded_ids() -> None:
    assert _is_readable_title("计算机学院关于操作系统课程考试安排的通知")
    assert not _is_readable_title("7209350f-00bb-49da-9da3-5ba7d3c3b9e9")
    assert not _is_readable_title("E5_8D_97_E5_85_9A_E3_80_942025_E3_80_9530")
    assert not _is_readable_title(
        "E6_A0_A1_E9_95_BF_E5_8A_9E_E5_85_AC_E4_BC_9A_E8_AE_AE_E7_BA_AA_E8_A6_812023-07_E7_AC_AC_E5_8D_81_E6_AC_A1"
    )
    assert not _is_readable_title("course-plan")
    assert not _is_readable_title("jobfair")


def test_low_quality_login_pages_are_detected() -> None:
    doc = Document(
        id="login",
        url="https://iam.nankai.edu.cn/login?next=%2Fapi%2Fcas%2Flogin",
        title="https://iam.nankai.edu.cn/login?next=%2Fapi%2Fcas%2Flogin",
        body="",
        host="iam.nankai.edu.cn",
        doc_type="html",
    )

    assert _is_low_quality_page(doc)


def test_search_results_expose_ranking_signals() -> None:
    response = tiny_engine().search("课程")

    assert response.results
    assert "VSM" in response.results[0].ranking_signals
    assert "PageRank" in response.results[0].ranking_signals


def test_recommendations_explain_personalized_reasons() -> None:
    user = {"id": None, "role": "教师", "interests": '["学术","图书馆"]'}
    recommendations = tiny_engine().recommend("数据库", user=user)

    assert recommendations
    first = recommendations[0]
    assert first.document.id == "4"
    assert first.category == "个性化文档"
    assert first.reasons
    assert any("兴趣命中" in reason or "教师画像" in reason for reason in first.reasons)
    assert first.matched_terms
    assert first.snippet


def test_student_and_teacher_profiles_get_different_recommendations() -> None:
    engine = tiny_engine()
    student = {"id": None, "role": "本科生", "interests": '["教务","课程"]'}
    teacher = {"id": None, "role": "教师", "interests": '["学术","图书馆"]'}

    student_first = engine.recommend("课程", user=student)[0]
    teacher_first = engine.recommend("数据库", user=teacher)[0]

    assert student_first.document.id == "3"
    assert teacher_first.document.id == "4"
    assert any("本科生" in reason or "兴趣命中" in reason for reason in student_first.reasons)
    assert any("教师" in reason or "学术" in reason for reason in teacher_first.reasons)


def test_search_candidate_limit_bounds_local_recall() -> None:
    response = tiny_engine().search("课程", candidate_limit=1)

    assert response.candidate_total == 1


def test_unreadable_file_title_falls_back_to_body_sentence() -> None:
    docs = [
        Document(
            id="pdf",
            url="https://jwc.nankai.edu.cn/upload/ir_homework.pdf",
            title="7209350f-00bb-49da-9da3-5ba7d3c3b9e9",
            body="信息检索课程作业说明。请完成向量空间模型与网页快照。",
            host="jwc.nankai.edu.cn",
            doc_type="pdf",
        )
    ]
    index = SearchIndex(
        documents=[doc.to_dict() for doc in docs],
        indexed_documents={
            "pdf": {
                "id": "pdf",
                "tf": {"信息": 1, "检索": 1, "课程": 1},
                "title_tf": {},
                "anchor_tf": {},
                "body_tf": {"信息": 1, "检索": 1, "课程": 1},
                "attachment_tf": {"信息": 1, "检索": 1, "课程": 1},
                "weighted_tf": {"信息": 1, "检索": 1, "课程": 1},
                "length": 3,
                "title_norm": 0.0,
                "anchor_norm": 0.0,
                "body_norm": 1.0,
                "attachment_norm": 1.0,
            }
        },
        idf={"信息": 1.0, "检索": 1.0, "课程": 1.0},
        avg_len=3.0,
        suggestions=[],
        term_docs={"信息": ["pdf"], "检索": ["pdf"], "课程": ["pdf"]},
    )
    response = SearchEngine(index=index, backend="local").search("信息检索 filetype:pdf")

    assert response.results
    assert response.results[0].display_title.startswith("信息检索课程作业说明")


def test_snippet_prefers_relevant_sentence_over_navigation() -> None:
    text = (
        "首页 南开要闻 媒体南开 南开校史 光影南开 南开故事 通知公告 "
        "当前位置：南开大学 >> 教务部 >> 通知公告 "
        "教务部关于 2026 年夏季学期选课的通知。"
        "本科生和研究生需在规定时间完成专业必修课、通识课和体育课选课。"
    )
    snippet = make_snippet(text, ["选课", "课程"], length=120)

    assert "选课" in snippet
    assert "本科生" in snippet or "教务部关于" in snippet
    assert "首页 南开要闻" not in snippet


def test_snippet_uses_content_anchors_after_dense_menu() -> None:
    text = (
        "首页 学生 招聘信息 招聘日历 招聘会信息 空中双选会 空中宣讲会 活动预告 "
        "生涯指导 政策手续 毕业填报 雇主 院系介绍 生源信息 招聘指南 联系院系 "
        "当前位置： 首页 > 学生 > 双选会 学生 招聘职位 招聘信息 实习信息 招聘日历 "
        "选调生 国际组织 一站式信息 招聘会 双选会 宣讲会 空中双选会 空中宣讲会 "
        "就业相关 活动预告 生涯指导 创业指导 就业政策 毕业填报 意见反馈 下载专区 "
        "今天 一 二 三 四 五 六 日 双选会 南开大学2026年就业实习双选会 "
        "时间：2026-05-15 14:00 地点：南开大学八里台校区 浏览量：6538 "
        "尊敬的用人单位：衷心感谢您对我校毕业生及毕业生就业工作的关爱与支持。"
    )
    snippet = make_snippet(text, ["就业", "实习", "双选会"], length=180)

    assert "时间" in snippet
    assert "地点" in snippet
    assert "就业" in snippet and "实习" in snippet and "双选会" in snippet
    assert "首页 学生 招聘信息" not in snippet


def test_snippet_repairs_mojibake_before_highlighting() -> None:
    text = "ä¸­å½ç¥ç½CNKIçµå­æç®æ»åº è®¿é®å°åï¼ www.cnki.net"
    snippet = make_snippet(text, ["CNKI", "数据库"], length=120)

    assert "中国知网" in snippet
    assert "<mark>CNKI</mark>" in snippet


def test_listing_pages_are_detected_for_soft_demotion() -> None:
    doc = Document(
        id="list",
        url="https://jwc.nankai.edu.cn/_s368/xkgl/list.psp",
        title="选课管理",
        body=(
            "首页 当前位置：教务部 选课管理 选课管理 "
            "南开大学2024-2025学年第二学期本科生选课通知 2024-12-03 "
            "南开大学2024-2025学年第一学期本科生选课通知 2024-08-12 "
            "2021-2022学年度第一学期选课手册 2021-09-10 共20条 上一页 下一页"
        ),
        host="jwc.nankai.edu.cn",
    )

    assert _is_listing_page(doc)


def test_unreadable_pdf_title_uses_report_like_body_title() -> None:
    doc = Document(
        id="pdf-report",
        url="https://cec.nankai.edu.cn/nb2019.pdf",
        title="nb2019",
        body=(
            "立项年份 2006 通过验收年份 2012 "
            "国家级实验教学示范中心年度报告 （2019年 1月 1日——2019年 12月 31日） "
            "实验教学中心名称：化学国家级实验教学示范中心（南开大学）"
        ),
        host="cec.nankai.edu.cn",
        doc_type="pdf",
    )

    assert "年度报告" in _display_title(doc)


def test_stale_data_paths_are_relocated_to_current_checkout() -> None:
    old_snapshot = r"D:\Study\26sp\信息检索\hw4\代码\data\snapshots\demo.html.gz"
    old_attachment = r"D:\Study\26sp\信息检索\hw4\代码\data\attachments\demo.pdf"
    doc = Document.from_dict(
        {
            "id": "stale",
            "url": "https://news.nankai.edu.cn/stale",
            "title": "stale path",
            "body": "demo",
            "host": "news.nankai.edu.cn",
            "snapshot_path": old_snapshot,
            "attachment_path": old_attachment,
        }
    )

    assert doc.snapshot_path == str(DATA_DIR / "snapshots" / "demo.html.gz")
    assert doc.attachment_path == str(DATA_DIR / "attachments" / "demo.pdf")
