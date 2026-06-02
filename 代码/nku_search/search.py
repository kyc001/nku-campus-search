from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any

from .database import clicked_urls, user_profile
from .elasticsearch_backend import ElasticsearchBackend
from .config import NKU_SEARCH_BACKEND_DEFAULT
from .indexer import SearchIndex, document_lookup, load_index
from .models import Document, ParsedQuery, Recommendation, SearchResult
from .query import FILETYPE_RE, REGEX_RE, SITE_RE, WILDCARD_RE, parse_query
from .text import make_snippet, repair_mojibake, term_counter, wildcard_to_regex

FIELD_WEIGHTS = {
    "title_tf": 4.0,
    "anchor_tf": 3.0,
    "body_tf": 1.0,
    "attachment_tf": 1.5,
}
MAX_CANDIDATES = 30_000
DEDUP_SIGNATURE_LEN = 200
PER_HOST_LIMIT = 3
DIVERSITY_WINDOW = 60

STUDENT_ROLE_PREFIXES = ("本", "研", "硕", "博")
STUDENT_KEYWORDS = ("教务", "选课", "课程", "通知")
TEACHER_TAGS = ("学术", "图书馆", "院系")
PROFILE_KEYWORDS = {
    "新闻": ("新闻", "要闻", "媒体南开", "通知", "公告"),
    "教务": ("教务", "选课", "课程", "考试", "成绩", "培养", "教学", "本科生", "研究生"),
    "课程": ("课程", "选课", "考试", "教学", "培养", "教材", "课堂"),
    "学术": ("学术", "讲座", "报告", "论坛", "论文", "科研", "项目", "基金", "实验室"),
    "招聘": ("招聘", "就业", "实习", "宣讲", "双选", "岗位", "用人单位", "毕业生"),
    "就业": ("就业", "招聘", "实习", "宣讲", "双选", "岗位", "用人单位", "毕业生"),
    "文体": ("文体", "活动", "比赛", "竞赛", "社团", "体育", "文化"),
    "院系": ("学院", "院系", "实验室", "中心", "专业", "学科"),
    "图书馆": ("图书馆", "数据库", "馆藏", "借阅", "资源", "检索", "CNKI", "知网"),
    "计算机": ("计算机", "软件", "人工智能", "网络", "数据", "信息安全", "算法"),
}
ROLE_KEYWORDS = {
    "本科生": ("教务", "选课", "课程", "考试", "成绩", "奖学金", "实习", "就业"),
    "研究生": ("研究生", "培养", "学位", "论文", "科研", "学术", "奖学金"),
    "教师": ("科研", "学术", "项目", "基金", "论文", "图书馆", "数据库", "实验室"),
    "校友": ("校友", "就业", "招聘", "活动", "捐赠", "基金"),
}
LOW_QUALITY_HOST_MARKERS = (
    "iam.nankai.edu.cn",
    "authserver.nankai.edu.cn",
    "ids.nankai.edu.cn",
    "sso.nankai.edu.cn",
)
LOW_QUALITY_PATH_MARKERS = (
    "/login",
    "/cas/",
    "caslogin",
    "do_caslogin",
    "oauth",
    "sso",
)
NAVIGATION_TITLE_WORDS = {
    "首页",
    "通知公告",
    "新闻动态",
    "学院新闻",
    "综合新闻",
    "信息公开",
    "部门概况",
    "机构设置",
}
LISTING_TITLE_WORDS = {
    "选课管理",
    "招聘信息",
    "招聘会信息",
    "活动预告",
    "文件下载",
    "自购数据库",
    "试用数据库",
    "数据库讲座",
}
LISTING_PATH_RE = re.compile(r"(?:^|/)(?:list|index)\.(?:jsp|psp|s?html?)$", re.I)
TITLE_LIKE_WORDS = (
    "通知",
    "公告",
    "公示",
    "报告",
    "年度报告",
    "办法",
    "细则",
    "指南",
    "简章",
    "方案",
    "安排",
    "名单",
    "手册",
    "说明",
    "申请表",
    "审批表",
    "课程",
)
BAD_BODY_TITLE_PREFIXES = ("附件解析失败", "版权所有", "Copyright", "首页", "当前位置", "浏览次数", "更新时间")
BODY_TITLE_PREFIX_RE = re.compile(
    r"^(?:附件\s*\d*\s*)?(?:批准)?立项年份\s*\d{4}\s*(?:通过验收年份\s*\d{0,4})?\s*"
)
INTENT_KEYWORDS = {
    "教务": ("教务", "选课", "课程", "培养", "考试", "成绩", "教学"),
    "招生": ("招生", "本科招生", "研究生招生", "推免", "录取", "报考"),
    "就业": ("就业", "招聘", "实习", "宣讲", "双选", "岗位"),
    "科研": ("科研", "学术", "讲座", "论文", "项目", "基金", "实验室"),
    "图书馆": ("图书馆", "数据库", "馆藏", "借阅", "资源", "检索"),
    "计算机": ("计算机", "软件", "人工智能", "网络", "数据", "信息安全"),
    "国际": ("国际", "留学", "交流", "合作", "外事", "英文"),
}
UGLY_TITLE_RE = re.compile(
    r"^(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){4}[0-9a-f]{12}|(?:[0-9a-f]{2}_){6,}[0-9a-f]{2}|[0-9a-f]{16,}|[A-Fa-f0-9]{8,}(?:[_-][A-Fa-f0-9]{4,})+)$"
)
URL_HEX_TITLE_RE = re.compile(r"(?:[A-Fa-f0-9]{2}[_-]){4,}[A-Fa-f0-9]{2}")
SLUG_TITLE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{4,49}")


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _content_signature(doc: "Document") -> str:
    # title + body 头部足以识别站点上反复出现的导航/列表页（它们标题一致、正文也是同一份菜单）
    body_head = (doc.body or "")[:DEDUP_SIGNATURE_LEN]
    payload = ((doc.title or "").strip() + "\n" + body_head).encode("utf-8", errors="ignore")
    return hashlib.md5(payload).hexdigest()


def _apply_result_diversity(
    scored: list[tuple[float, "Document", list[str], list[str]]],
    per_host_limit: int = PER_HOST_LIMIT,
    window: int = DIVERSITY_WINDOW,
) -> list[tuple[float, "Document", list[str], list[str]]]:
    """合并重复内容、限制单一主机在结果窗口内的占比。

    - 内容签名相同时只保留分数最高（即排序后首次出现）的一条；
    - 在前 ``window`` 条内，单个 host 至多保留 ``per_host_limit`` 条，
      多出的并不丢弃，而是顺延到窗口之后，避免列表页霸占首页。
    """
    seen_sig: set[str] = set()
    deduped: list[tuple[float, "Document", list[str], list[str]]] = []
    for tup in scored:
        sig = _content_signature(tup[1])
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        deduped.append(tup)
    primary: list[tuple[float, "Document", list[str], list[str]]] = []
    overflow: list[tuple[float, "Document", list[str], list[str]]] = []
    host_count: dict[str, int] = {}
    for tup in deduped:
        host = tup[1].host
        if len(primary) < window and host_count.get(host, 0) >= per_host_limit:
            overflow.append(tup)
            continue
        primary.append(tup)
        host_count[host] = host_count.get(host, 0) + 1
    return primary + overflow


def _is_readable_title(title: str) -> bool:
    cleaned = (title or "").strip()
    if not cleaned:
        return False
    if len(cleaned) < 2:
        return False
    lowered = cleaned.lower()
    if "%" in cleaned or "_upload/" in lowered or "/_upload" in lowered:
        return False
    if URL_HEX_TITLE_RE.search(cleaned):
        return False
    if not re.search(r"[\u4e00-\u9fff]", cleaned) and SLUG_TITLE_RE.fullmatch(cleaned):
        return False
    if cleaned.count("_") >= 4 and re.fullmatch(r"[A-Fa-f0-9_]+", cleaned):
        return False
    if UGLY_TITLE_RE.match(lowered):
        return False
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", cleaned):
        return False
    alpha_num = sum(ch.isalnum() for ch in cleaned)
    if alpha_num and alpha_num / max(len(cleaned), 1) < 0.2 and "_" in cleaned:
        return False
    return True


def _display_title(doc: "Document") -> str:
    title = repair_mojibake(doc.title or "").strip()
    if _is_readable_title(title):
        return title
    body = repair_mojibake(doc.body or "").strip()
    body_title = _title_from_body(body)
    if body_title:
        return body_title
    for part in re.split(r"[。！？!?；;\n]", body):
        part = part.strip()
        if 8 <= len(part) <= 90 and re.search(r"[\u4e00-\u9fff]", part):
            if not part.startswith(BAD_BODY_TITLE_PREFIXES):
                return part
    parsed = urlparse(doc.url)
    filename = unquote(parsed.path.rstrip("/").split("/")[-1] or parsed.netloc)
    filename = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    if filename and re.search(r"[\u4e00-\u9fffA-Za-z]", filename):
        return filename[:80]
    return parsed.netloc or doc.url


def _title_from_body(body: str) -> str:
    if not body:
        return ""
    head = re.sub(r"\s+", " ", body[:2500]).strip()
    candidates: list[str] = []
    patterns = [
        r"(?:南开大学)?[\u4e00-\u9fffA-Za-z0-9（）()《》“”、：:\-\s]{0,36}(?:年度报告|通知|公告|公示|简章|办法|说明|手册|指南|安排|名单|方案|申请表|审批表)[\u4e00-\u9fffA-Za-z0-9（）()《》“”、：:\-\s]{0,36}",
        r"(?:数据库名称|实验教学中心名称|中心名称|课程名称)[：:]\s*[\u4e00-\u9fffA-Za-z0-9（）()《》“”、\-\s]{4,72}",
    ]
    for pattern in patterns:
        candidates.extend(match.group(0) for match in re.finditer(pattern, head))
    candidates.extend(part.strip() for part in re.split(r"[。！？!?；;\n]", head) if part.strip())

    best = ""
    best_score = -1.0
    for candidate in candidates:
        cleaned = _clean_body_title(candidate)
        if not (8 <= len(cleaned) <= 90):
            continue
        if cleaned.startswith(BAD_BODY_TITLE_PREFIXES):
            continue
        if not re.search(r"[\u4e00-\u9fff]", cleaned):
            continue
        score = 0.0
        score += sum(2.0 for word in TITLE_LIKE_WORDS if word in cleaned)
        if "南开大学" in cleaned:
            score += 1.0
        if "年度报告" in cleaned:
            score += 2.0
        if "名称：" in cleaned or "名称:" in cleaned:
            score -= 1.0
        if re.search(r"^\d{4}\s*年", cleaned):
            score -= 1.5
        if re.search(r"第\s*\d+\s*条|共\s*\d+\s*条|上一页|下一页", cleaned):
            score -= 3.0
        if score > best_score:
            best_score = score
            best = cleaned
    return best if best_score >= 1.0 else ""


def _clean_body_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ：:，,。；;、-—")
    for prefix in ("数据库名称", "实验教学中心名称", "中心名称", "课程名称"):
        value = re.sub(rf"^{prefix}\s*[：:]\s*", "", value)
    value = BODY_TITLE_PREFIX_RE.sub("", value).strip(" ：:，,。；;、-—")
    value = re.sub(r"^\d{8,}\s*", "", value).strip()
    value = value.replace("国 家级", "国家级").replace("教 学", "教学")
    return value[:90].strip()


def _is_low_quality_page(doc: "Document") -> bool:
    if _is_noisy_url(doc):
        return True
    title = (doc.title or "").strip()
    if title.startswith(("http://", "https://")):
        return True
    if not _is_readable_title(title):
        if doc.doc_type != "html" and len((doc.body or "").strip()) >= 80:
            return False
        return True
    body = (doc.body or "").strip()
    if doc.doc_type == "html" and len(body) < 80 and not doc.anchor_text:
        return True
    return False


def _is_noisy_url(doc: "Document") -> bool:
    url = (doc.url or "").lower()
    parsed = urlparse(doc.url)
    if any(marker in parsed.netloc.lower() for marker in LOW_QUALITY_HOST_MARKERS):
        return True
    if any(marker in parsed.path.lower() or marker in url for marker in LOW_QUALITY_PATH_MARKERS):
        return True
    if parsed.query and {"next", "service", "redirect", "redirect_uri"} & set(parse_qs(parsed.query).keys()):
        return True
    return False


def _has_weak_title(doc: "Document") -> bool:
    return not _is_readable_title(doc.title)


def _title_quality_multiplier(doc: "Document") -> float:
    if _is_low_quality_page(doc):
        return 0.08
    if doc.doc_type != "html" and not _is_readable_title(doc.title) and len((doc.body or "").strip()) >= 80:
        return 0.75
    title = (doc.title or "").strip()
    if title in NAVIGATION_TITLE_WORDS:
        return 0.35
    if len(title) <= 4 and doc.doc_type == "html":
        return 0.55
    return 1.0


def _is_listing_page(doc: "Document") -> bool:
    if doc.doc_type != "html":
        return False
    parsed = urlparse(doc.url)
    path = parsed.path.lower().rstrip("/")
    title = repair_mojibake(doc.title or "").strip()
    title_core = title.split("|", 1)[0].split("-", 1)[0].strip()
    body = repair_mojibake(doc.body or "")[:1400]
    if LISTING_PATH_RE.search(path):
        return True
    if title_core in LISTING_TITLE_WORDS:
        return True
    date_hits = len(re.findall(r"20\d{2}[-/.年]\d{1,2}", body))
    page_markers = sum(1 for marker in ("上一页", "下一页", "共", "条", "当前位置", "首页") if marker in body)
    repeated_title = bool(title_core and len(title_core) >= 3 and body.count(title_core) >= 2)
    return (date_hits >= 3 and page_markers >= 2) or (repeated_title and date_hits >= 2)


def _listing_quality_multiplier(doc: "Document", parsed: ParsedQuery) -> float:
    if not _is_listing_page(doc):
        return 1.0
    specificity = 0
    if parsed.site:
        specificity += 1
    if parsed.filetype or parsed.phrases or parsed.wildcard or parsed.regex:
        specificity += 1
    specificity += min(len({term for term in parsed.terms if len(term) >= 2}), 4)
    if specificity >= 4:
        return 0.42
    if specificity >= 2:
        return 0.58
    return 0.75


def _query_intents(parsed: ParsedQuery) -> list[str]:
    haystack = " ".join([parsed.raw, *parsed.terms, *parsed.phrases]).lower()
    intents = []
    for label, keywords in INTENT_KEYWORDS.items():
        if any(word.lower() in haystack for word in keywords):
            intents.append(label)
    return intents


def _profile_terms(profile: dict[str, Any]) -> list[str]:
    role = profile.get("role") or ""
    interests = profile.get("interests") or []
    terms: list[str] = []
    for interest in interests:
        terms.append(str(interest))
        terms.extend(PROFILE_KEYWORDS.get(str(interest), ()))
    for prefix, keywords in ROLE_KEYWORDS.items():
        if role.startswith(prefix):
            terms.extend(keywords)
    return _dedup_keep_order([term for term in terms if term])


def _matched_terms(text: str, terms: list[str], limit: int = 6) -> list[str]:
    lowered = (text or "").lower()
    matches: list[str] = []
    for term in terms:
        clean = (term or "").strip()
        if clean and clean.lower() in lowered:
            matches.append(clean)
    return _dedup_keep_order(matches)[:limit]


def _query_anchor_terms(parsed: ParsedQuery) -> list[str]:
    core = _clean_core_query(parsed.raw)
    anchors: list[str] = []
    for part in re.split(r"\s+", core):
        clean = part.strip("，。；;：:、()（）[]【】")
        if len(clean) >= 2:
            anchors.append(clean)
    for phrase in parsed.phrases:
        clean = phrase.strip()
        if len(clean) >= 2:
            anchors.append(clean)
    for term in parsed.terms:
        if len(term) >= 3 or re.search(r"[A-Za-z0-9]", term):
            anchors.append(term)
    return _dedup_keep_order(anchors)


def _intent_boost(doc: "Document", intents: list[str]) -> float:
    if not intents:
        return 0.0
    searchable = f"{doc.title} {' '.join(doc.tags)} {doc.host} {doc.url} {doc.body[:800]}".lower()
    boost = 0.0
    for intent in intents:
        keywords = INTENT_KEYWORDS[intent]
        if intent in doc.tags:
            boost += 0.18
        if any(word.lower() in searchable for word in keywords):
            boost += 0.12
    return min(boost, 0.45)


def _term_coverage(indexed: dict[str, Any], query_terms: list[str]) -> float:
    unique_terms = {term for term in query_terms if len(term) >= 2}
    if not unique_terms:
        return 1.0
    doc_terms = indexed.get("tf", {})
    hits = sum(1 for term in unique_terms if doc_terms.get(term, 0) > 0)
    return hits / len(unique_terms)


def _clean_core_query(raw_query: str) -> str:
    text = SITE_RE.sub(" ", raw_query or "")
    text = FILETYPE_RE.sub(" ", text)
    text = REGEX_RE.sub(" ", text)
    text = WILDCARD_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().strip('"“”')


def _recommendation_query(raw_query: str, parsed: ParsedQuery) -> str:
    parts = [raw_query or ""]
    lowered = (raw_query or "").lower()
    if parsed.site and "site:" not in lowered:
        parts.append(f"site:{parsed.site}")
    if parsed.filetype and "filetype:" not in lowered:
        parts.append(f"filetype:{parsed.filetype}")
    return " ".join(part for part in parts if part).strip()


def _exact_query_boost(doc: "Document", raw_query: str) -> float:
    core = _clean_core_query(raw_query).lower()
    if len(core) < 2:
        return 0.0
    title = (doc.title or "").lower()
    body = (doc.body or "").lower()
    anchor = (doc.anchor_text or "").lower()
    boost = 0.0
    if core in title:
        boost += 0.35
    if core in anchor:
        boost += 0.18
    if core in body[:2000]:
        boost += 0.15
    return min(boost, 0.45)


@dataclass
class SearchResponse:
    results: list[SearchResult]
    total: int
    page: int
    page_size: int
    elapsed_ms: float
    parsed: ParsedQuery
    recommendations: list[Recommendation]
    backend: str = "local"
    candidate_total: int = 0


@dataclass
class QueryRuntime:
    q_vec: dict[str, float]
    q_norm: float
    phrase_res: list[re.Pattern[str]] = field(default_factory=list)
    pattern_re: re.Pattern[str] | None = None
    pattern_error: bool = False
    snippet_terms: list[str] = field(default_factory=list)


class SearchEngine:
    def __init__(self, index: SearchIndex | None = None, backend: str = NKU_SEARCH_BACKEND_DEFAULT):
        self.index = index or load_index()
        self.documents = document_lookup(self.index)
        self.documents_by_url = {doc.url: doc for doc in self.documents.values()}
        self.backend_mode = backend
        self.es_backend = ElasticsearchBackend(enabled=backend in {"auto", "es"})
        self._freshness_cache: dict[str, float] = {}

    def parse(self, raw_query: str, site: str = "", filetype: str = "") -> ParsedQuery:
        return parse_query(raw_query, site=site, filetype=filetype)

    def reload(self) -> None:
        self.index = load_index()
        self.documents = document_lookup(self.index)
        self.documents_by_url = {doc.url: doc for doc in self.documents.values()}
        self._freshness_cache.clear()

    def document_by_url(self, url: str) -> Document | None:
        return self.documents_by_url.get(url)

    def prepare_runtime(self, parsed: ParsedQuery) -> QueryRuntime:
        q_vec, q_norm = self._query_vector(parsed.terms)
        phrase_res: list[re.Pattern[str]] = []
        separator = r"[\s,，。；;：:、\-_\/]*"
        for phrase in parsed.phrases:
            terms = [part for part in re.split(r"\s+", phrase.strip().lower()) if part]
            if terms:
                phrase_res.append(re.compile(separator.join(re.escape(term) for term in terms), flags=re.I))

        pattern_re: re.Pattern[str] | None = None
        pattern_error = False
        pattern = ""
        if parsed.wildcard:
            pattern = wildcard_to_regex(parsed.wildcard.lower())
        elif parsed.regex:
            pattern = parsed.regex
        if pattern:
            try:
                pattern_re = re.compile(pattern, flags=re.I)
            except re.error:
                pattern_error = True

        snippet_terms = [term for term in parsed.terms if term]
        if parsed.wildcard:
            snippet_terms.append(parsed.wildcard.replace("*", "").replace("?", ""))
        if parsed.regex:
            snippet_terms.extend(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", parsed.regex))
        return QueryRuntime(q_vec, q_norm, phrase_res, pattern_re, pattern_error, [term for term in snippet_terms if term])

    @staticmethod
    def _haystack(doc: Document) -> str:
        return f"{doc.title}\n{doc.body}\n{doc.anchor_text}\n{doc.url}"

    def _passes_filters(self, doc: Document, parsed: ParsedQuery, runtime: QueryRuntime | None = None) -> bool:
        if parsed.site and parsed.site not in doc.host.lower():
            return False
        if parsed.filetype and doc.doc_type.lower() != parsed.filetype:
            return False
        if not parsed.phrases and not parsed.wildcard and not parsed.regex:
            return True
        runtime = runtime or self.prepare_runtime(parsed)
        if runtime.pattern_error:
            return False
        haystack = self._haystack(doc).lower()
        for phrase_re in runtime.phrase_res:
            if not phrase_re.search(haystack):
                return False
        if parsed.wildcard or parsed.regex:
            if runtime.pattern_re is None or not runtime.pattern_re.search(haystack):
                return False
        return True

    def _pattern_field_score(self, doc: Document, parsed: ParsedQuery, runtime: QueryRuntime | None = None) -> float:
        runtime = runtime or self.prepare_runtime(parsed)
        if not (parsed.wildcard or parsed.regex) or runtime.pattern_re is None:
            return 0.0
        fields = [
            (doc.title, 24.0),
            (doc.body, 2.0),
            (doc.anchor_text, 1.0),
            (doc.url, 0.5),
        ]
        score = 0.0
        for text, weight in fields:
            if runtime.pattern_re.search(text or ""):
                score += weight
        return score

    def _personal_boost(
        self,
        doc: Document,
        user: dict[str, Any] | None,
        query: str,
        profile: dict[str, Any] | None = None,
        clicked: set[str] | None = None,
    ) -> float:
        if not user:
            return 0.0
        profile = profile or user_profile(user)
        clicked = clicked or set()
        interests = profile["interests"]
        role = profile["role"] or ""
        boost = 0.0
        tag_text = " ".join(doc.tags)
        for interest in interests:
            if interest and (interest in tag_text or interest in doc.title or interest in doc.body[:500]):
                boost += 0.35
                related_terms = PROFILE_KEYWORDS.get(str(interest), ())
                related_hits = _matched_terms(doc.title + tag_text + doc.body[:800], list(related_terms), limit=5)
                if related_hits:
                    boost += min(0.18 * len(related_hits), 0.90)

        is_student = role.startswith(STUDENT_ROLE_PREFIXES)
        is_teacher = bool(role) and not is_student

        if is_student and any(word in doc.title + doc.body[:300] for word in STUDENT_KEYWORDS):
            boost += 1.00
        if is_student and any(word in doc.title + doc.body[:600] + tag_text for word in PROFILE_KEYWORDS["就业"]):
            boost += 1.15
        if is_student and doc.doc_type == "html":
            boost += 5.00
        if is_student and doc.doc_type != "html":
            boost -= 0.95
        if is_teacher and doc.doc_type in {"pdf", "docx", "xlsx"}:
            boost += 5.00
        if is_teacher and doc.doc_type == "html":
            boost -= 0.90
        if is_teacher and any(word in tag_text for word in TEACHER_TAGS):
            boost += 0.60
        if doc.url in clicked:
            boost += 0.30
        if query and query in doc.title:
            boost += 0.05
        return boost

    def _tfidf(self, tf: float, term: str) -> float:
        if tf <= 0:
            return 0.0
        return (1.0 + math.log(tf)) * self.index.idf.get(term, 0.0)

    def _query_vector(self, terms: list[str]) -> tuple[dict[str, float], float]:
        q_tf = term_counter(" ".join(terms))
        q_vec = {term: self._tfidf(tf, term) for term, tf in q_tf.items()}
        q_norm = math.sqrt(sum(weight * weight for weight in q_vec.values()))
        return q_vec, q_norm

    def _field_cosine(self, field_tf: dict[str, int], field_norm: float, q_vec: dict[str, float], q_norm: float) -> float:
        if not field_tf or field_norm <= 0.0 or q_norm <= 0.0:
            return 0.0
        dot = 0.0
        for term, q_weight in q_vec.items():
            tf = field_tf.get(term, 0)
            if not tf:
                continue
            weight = self._tfidf(tf, term)
            dot += weight * q_weight
        return dot / (field_norm * q_norm)

    def _vsm_score(
        self,
        indexed: dict[str, Any],
        query_terms: list[str],
        q_vec: dict[str, float] | None = None,
        q_norm: float | None = None,
    ) -> float:
        if q_vec is None or q_norm is None:
            q_vec, q_norm = self._query_vector(query_terms)
        if q_norm <= 0.0:
            return 0.0
        score = 0.0
        for field, weight in FIELD_WEIGHTS.items():
            norm_key = field.replace("_tf", "_norm")
            score += weight * self._field_cosine(indexed.get(field, {}), indexed.get(norm_key, 0.0), q_vec, q_norm)
        return score

    def _pattern_candidate_doc_ids(self, parsed: ParsedQuery, max_terms: int = 2000) -> set[str] | None:
        source = parsed.wildcard or parsed.regex
        if not source or not re.search(r"[A-Za-z0-9_\u4e00-\u9fff]", source):
            return None
        pattern = wildcard_to_regex(parsed.wildcard.lower()) if parsed.wildcard else parsed.regex
        try:
            pattern_re = re.compile(pattern, flags=re.I)
        except re.error:
            return set()
        doc_ids: set[str] = set()
        matched_terms = 0
        for term, ids in self.index.term_docs.items():
            if pattern_re.search(term):
                matched_terms += 1
                doc_ids.update(ids)
                if matched_terms >= max_terms:
                    break
        return doc_ids or None

    def _local_candidate_doc_ids(self, parsed: ParsedQuery, limit: int = MAX_CANDIDATES) -> list[str]:
        if parsed.terms:
            ids: set[str] = set()
            required_hits: dict[str, int] = {}
            for term in set(parsed.terms):
                term_ids = self.index.term_docs.get(term, [])
                ids.update(term_ids)
                for doc_id in term_ids:
                    required_hits[doc_id] = required_hits.get(doc_id, 0) + 1
            if ids:
                candidates = list(ids)
                if len(parsed.terms) >= 2:
                    candidates.sort(
                        key=lambda doc_id: (
                            required_hits.get(doc_id, 0),
                            _title_quality_multiplier(self.documents[doc_id]),
                            self.documents[doc_id].pagerank,
                        ),
                        reverse=True,
                    )
            else:
                candidates = list(self.index.indexed_documents)
        elif parsed.wildcard or parsed.regex:
            pattern_ids = self._pattern_candidate_doc_ids(parsed)
            candidates = list(pattern_ids) if pattern_ids is not None else list(self.index.indexed_documents)
        else:
            candidates = list(self.index.indexed_documents)
        if parsed.site:
            candidates = [doc_id for doc_id in candidates if parsed.site in self.documents[doc_id].host.lower()]
        if parsed.filetype:
            candidates = [doc_id for doc_id in candidates if self.documents[doc_id].doc_type.lower() == parsed.filetype]
        limit = max(1, min(limit, MAX_CANDIDATES))
        if len(candidates) > limit:
            candidates.sort(
                key=lambda doc_id: (
                    _title_quality_multiplier(self.documents[doc_id]),
                    self.documents[doc_id].pagerank,
                ),
                reverse=True,
            )
            candidates = candidates[:limit]
        return candidates

    def _candidate_doc_ids(self, parsed: ParsedQuery, limit: int = MAX_CANDIDATES) -> list[str]:
        return self._local_candidate_doc_ids(parsed, limit=limit)

    def es_recall_size(self, parsed: ParsedQuery, user: dict[str, Any] | None = None) -> int:
        if user:
            return 5000
        if parsed.phrases:
            return 2500
        if parsed.site or parsed.filetype or parsed.wildcard or parsed.regex:
            return 2000
        return 1200

    def _candidate_doc_ids_for_search(
        self,
        parsed: ParsedQuery,
        backend: str | None = None,
        user: dict[str, Any] | None = None,
        limit: int = MAX_CANDIDATES,
    ) -> tuple[list[str], int, str]:
        mode = backend or self.backend_mode
        if mode in {"auto", "es"}:
            recall = self.es_backend.search_doc_ids(parsed, self.es_recall_size(parsed, user=user))
            if recall.available:
                ids = [doc_id for doc_id in recall.doc_ids if doc_id in self.documents]
                if ids or recall.total == 0:
                    return ids, recall.total, "elasticsearch"
            if mode == "es":
                # ES was explicitly requested but is not reachable; use local recall so
                # demos and selfcheck stay usable on machines without a running service.
                pass
        ids = self._local_candidate_doc_ids(parsed, limit=limit)
        return ids, len(ids), "local"

    def _freshness(self, doc: Document) -> float:
        if doc.id in self._freshness_cache:
            return self._freshness_cache[doc.id]
        freshness = 0.0
        if not doc.crawled_at:
            self._freshness_cache[doc.id] = freshness
            return freshness
        try:
            crawled = datetime.fromisoformat(doc.crawled_at.replace("Z", "+00:00"))
            if crawled.tzinfo is None:
                crawled = crawled.replace(tzinfo=timezone.utc)
            days = max((datetime.now(timezone.utc) - crawled).total_seconds() / 86400.0, 0.0)
            freshness = math.exp(-days / 365.0)
        except ValueError:
            freshness = 0.0
        self._freshness_cache[doc.id] = freshness
        return freshness

    def search(
        self,
        raw_query: str,
        page: int = 1,
        page_size: int = 10,
        site: str = "",
        filetype: str = "",
        user: dict[str, Any] | None = None,
        backend: str | None = None,
        candidate_limit: int = MAX_CANDIDATES,
    ) -> SearchResponse:
        started = time.perf_counter()
        parsed = self.parse(raw_query, site=site, filetype=filetype)
        query_terms = parsed.terms
        runtime = self.prepare_runtime(parsed)
        profile = user_profile(user)
        clicked = set(clicked_urls(user.get("id") if user and user.get("id") else None)) if user else set()
        query_intents = _query_intents(parsed)
        scored: list[tuple[float, Document, list[str], list[str]]] = []

        candidate_ids, candidate_total, backend_used = self._candidate_doc_ids_for_search(
            parsed,
            backend=backend,
            user=user,
            limit=candidate_limit,
        )
        for doc_id in candidate_ids:
            indexed = self.index.indexed_documents.get(doc_id)
            if not indexed:
                continue
            doc = self.documents[doc_id]
            if not self._passes_filters(doc, parsed, runtime):
                continue
            content_score = self._vsm_score(indexed, query_terms, q_vec=runtime.q_vec, q_norm=runtime.q_norm)
            if not query_terms and (parsed.wildcard or parsed.regex):
                content_score = self._pattern_field_score(doc, parsed, runtime) / 5.0
            if not query_terms and not parsed.wildcard and not parsed.regex:
                content_score = 0.1
            link_boost = 1.0 + 0.5 * math.log1p(max(doc.pagerank, 0.0))
            freshness = 0.1 * self._freshness(doc)
            personal_signal = self._personal_boost(doc, user, raw_query, profile=profile, clicked=clicked)
            personal_boost = 1.0 + personal_signal
            intent_signal = _intent_boost(doc, query_intents)
            exact_signal = _exact_query_boost(doc, raw_query)
            coverage = _term_coverage(indexed, query_terms)
            quality_multiplier = _title_quality_multiplier(doc)
            listing_multiplier = _listing_quality_multiplier(doc, parsed)
            score = (content_score * link_boost + freshness) * personal_boost + 0.25 * personal_signal
            score *= 1.0 + intent_signal + exact_signal
            if query_terms:
                score *= 0.55 + 0.45 * coverage
            if not parsed.filetype and not user:
                if doc.doc_type == "html":
                    score *= 1.8
                else:
                    score *= 0.7
            if parsed.phrases:
                score *= 1.2
            if (parsed.wildcard or parsed.regex) and runtime.pattern_re and runtime.pattern_re.search(doc.title or ""):
                score += 5.0
            if score <= 0 and (parsed.wildcard or parsed.regex or parsed.site or parsed.filetype):
                score = 0.05 * link_boost * personal_boost
            score *= quality_multiplier * listing_multiplier
            if score <= 0:
                continue
            features = []
            if parsed.site:
                features.append("site")
            if parsed.filetype:
                features.append("filetype")
            if parsed.phrases:
                features.append("phrase")
            if parsed.wildcard:
                features.append("wildcard")
            if parsed.regex:
                features.append("regex")
            signals = ["VSM", "PageRank"]
            if self._freshness(doc) > 0:
                signals.append("新鲜度")
            if intent_signal > 0:
                signals.append("主题匹配")
            if exact_signal > 0:
                signals.append("精确匹配")
            if coverage >= 0.99 and len(query_terms) >= 2:
                signals.append("多词覆盖")
            if personal_signal > 0:
                signals.append("个性化")
            if quality_multiplier < 1.0 and _is_low_quality_page(doc):
                signals.append("低质量页降权")
            elif quality_multiplier < 1.0:
                signals.append("标题质量修正")
            if listing_multiplier < 1.0:
                signals.append("列表页降权")
            if doc.doc_type != "html":
                signals.append("文档检索")
            scored.append((score, doc, features, signals))

        scored.sort(key=lambda item: item[0], reverse=True)
        scored = _apply_result_diversity(scored)
        total = len(scored)
        page = max(page, 1)
        start = (page - 1) * page_size
        paged_raw = scored[start : start + page_size]
        paged = [
            SearchResult(
                document=doc,
                score=score,
                snippet=make_snippet(doc.body or doc.anchor_text or _display_title(doc), runtime.snippet_terms),
                matched_features=features,
                ranking_signals=signals,
                display_title=_display_title(doc),
            )
            for score, doc, features, signals in paged_raw
        ]
        exclude_ids = {doc.id for _, doc, _, _ in paged_raw}
        recommendations = self.recommend(_recommendation_query(raw_query, parsed), user=user, exclude=exclude_ids, limit=5)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return SearchResponse(paged, total, page, page_size, elapsed_ms, parsed, recommendations, backend_used, candidate_total)

    def suggest(self, prefix: str, limit: int = 10, history: list[str] | None = None) -> list[str]:
        prefix = (prefix or "").lower().strip()
        history_clean: list[str] = []
        if history:
            seen: set[str] = set()
            for item in history:
                value = (item or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                if not prefix or prefix in value.lower():
                    history_clean.append(value)
                if len(history_clean) >= limit:
                    break
        if not prefix:
            base = list(self.index.suggestions[: max(limit - len(history_clean), 0)])
            return _dedup_keep_order(history_clean + base)[:limit]
        matched = [s for s in self.index.suggestions if prefix in s.lower()]
        merged = _dedup_keep_order(history_clean + matched)
        return merged[:limit]

    def _recommendation_profile_reason(self, doc: Document, profile: dict[str, Any], clicked: set[str]) -> tuple[float, list[str], list[str]]:
        text = f"{doc.title} {' '.join(doc.tags)} {doc.host} {doc.url} {doc.body[:900]}"
        reasons: list[str] = []
        matched: list[str] = []
        score = 0.0

        interest_matches = _matched_terms(text, _profile_terms(profile))
        if interest_matches:
            matched.extend(interest_matches)
            score += 1.25 + 0.28 * len(interest_matches)
            reasons.append("兴趣命中：" + "、".join(interest_matches[:3]))

        role = profile.get("role") or ""
        is_student = role.startswith(STUDENT_ROLE_PREFIXES)
        is_teacher = bool(role) and not is_student and role != "访客"
        role_text = doc.title + doc.body[:500] + " ".join(doc.tags)
        if is_student:
            if any(word in role_text for word in STUDENT_KEYWORDS):
                score += 1.4
                reasons.append("本科生常用教务信息")
            if doc.doc_type == "html":
                score += 0.6
                reasons.append("网页通知便于直接查看")
        if is_teacher:
            if doc.doc_type in {"pdf", "docx", "xlsx"}:
                score += 1.2
                reasons.append("教师画像偏好文档资源")
            if any(word in role_text for word in TEACHER_TAGS + ("科研", "讲座", "项目", "论文")):
                score += 1.1
                reasons.append("学术/科研信号强")

        if doc.url in clicked:
            score += 1.8
            reasons.append("来自最近点击记录")

        return score, reasons, matched

    def _recommendation_category(self, doc: Document, reasons: list[str], intents: list[str]) -> str:
        if any("最近点击" in reason or "兴趣命中" in reason for reason in reasons):
            if doc.doc_type != "html":
                return "个性化文档"
            if any("同主题" in reason or "意图匹配" in reason for reason in reasons):
                return "画像同主题"
            return "画像探索"
        if doc.doc_type != "html":
            return "文档资源"
        if intents:
            return "同主题延伸"
        return "相关资源"

    def recommend(
        self,
        query: str,
        user: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
        limit: int = 5,
    ) -> list[Recommendation]:
        exclude = exclude or set()
        parsed = parse_query(query)
        terms = set(parsed.terms)
        profile = user_profile(user)
        intents = _query_intents(parsed)
        clicked = set(clicked_urls(user.get("id") if user and user.get("id") else None)) if user else set()
        candidates: list[Recommendation] = []
        candidate_ids = self._recommendation_candidate_doc_ids(parsed, profile, intents, limit=3200)
        query_terms = [term for term in parsed.terms if term]
        anchor_terms = _query_anchor_terms(parsed)
        seen_signatures: set[str] = set()
        for doc_id in candidate_ids:
            doc = self.documents.get(doc_id)
            if not doc:
                continue
            if doc.id in exclude:
                continue
            if _is_low_quality_page(doc):
                continue
            signature = _content_signature(doc)
            if signature in seen_signatures:
                continue
            if not _is_readable_title(doc.title) and doc.doc_type == "html":
                continue
            strong_topic_text = f"{_display_title(doc)} {doc.title} {doc.host} {doc.url}"
            topic_text = strong_topic_text if doc.doc_type == "html" else f"{strong_topic_text} {doc.body[:1200]}"
            text = f"{doc.title} {' '.join(doc.tags)} {doc.host} {doc.url} {doc.body[:900]}"
            query_matches = _matched_terms(topic_text, list(terms), limit=5)
            anchor_matches = _matched_terms(topic_text, anchor_terms, limit=4)
            overlap = len(query_matches)
            profile_score, reasons, profile_matches = self._recommendation_profile_reason(doc, profile, clicked)
            intent = _intent_boost(doc, intents) * 2.2
            has_query_anchor = bool(anchor_matches)
            if query_terms and not has_query_anchor:
                continue
            query_relevance = overlap * 2.2 + len(anchor_matches) * 2.8 + intent * 1.35
            if query_terms:
                profile_component = profile_score * 0.48
            else:
                profile_component = profile_score
            score = query_relevance + profile_component + doc.pagerank * 0.45
            if query_matches:
                reasons.append("同主题：" + "、".join(query_matches[:3]))
            elif anchor_matches:
                reasons.append("同主题：" + "、".join(anchor_matches[:3]))
            if intent > 0 and intents:
                reasons.append("意图匹配：" + "、".join(intents[:2]))
            if doc.pagerank >= 1.0:
                reasons.append("站内链接权威较高")
            if doc.doc_type != "html":
                reasons.append(f"{doc.doc_type.upper()} 文档可下载")
            if _is_listing_page(doc):
                score *= 0.62
                reasons.append("列表页已降权")
            score *= _title_quality_multiplier(doc)
            if score > 0:
                seen_signatures.add(signature)
                matched_terms = _dedup_keep_order(anchor_matches + query_matches + profile_matches)[:6]
                snippet_terms = matched_terms or query_terms or _profile_terms(profile)[:4]
                candidates.append(
                    Recommendation(
                        document=doc,
                        score=score,
                        reasons=_dedup_keep_order(reasons)[:4],
                        matched_terms=matched_terms,
                        category=self._recommendation_category(doc, reasons, intents),
                        snippet=make_snippet(doc.body or doc.anchor_text or _display_title(doc), snippet_terms, length=120),
                        display_title=_display_title(doc),
                    )
                )
        candidates.sort(key=lambda item: item.score, reverse=True)
        diverse: list[Recommendation] = []
        seen_hosts: dict[str, int] = {}
        for item in candidates:
            host = item.document.host
            if seen_hosts.get(host, 0) >= 2 and len(diverse) < limit:
                continue
            diverse.append(item)
            seen_hosts[host] = seen_hosts.get(host, 0) + 1
            if len(diverse) >= limit:
                break
        return diverse

    def _recommendation_candidate_doc_ids(
        self,
        parsed: ParsedQuery,
        profile: dict[str, Any],
        intents: list[str],
        limit: int = 3200,
    ) -> list[str]:
        weighted: dict[str, float] = {}

        def add_ids(terms: list[str], weight: float, cap_per_term: int) -> None:
            for term in terms:
                clean = (term or "").lower()
                if not clean:
                    continue
                for doc_id in self.index.term_docs.get(clean, [])[:cap_per_term]:
                    weighted[doc_id] = weighted.get(doc_id, 0.0) + weight

        add_ids(parsed.terms, 3.0, 1600)
        add_ids(_profile_terms(profile), 1.5, 800)
        for intent in intents:
            add_ids(list(INTENT_KEYWORDS.get(intent, ())), 1.1, 500)

        if not weighted:
            for doc_id in self._candidate_doc_ids(parsed, limit=limit)[:limit]:
                weighted[doc_id] = 0.1

        ordered = sorted(
            weighted,
            key=lambda doc_id: (
                weighted[doc_id],
                _title_quality_multiplier(self.documents[doc_id]),
                self.documents[doc_id].pagerank,
            ),
            reverse=True,
        )
        if parsed.site:
            ordered = [doc_id for doc_id in ordered if parsed.site in self.documents[doc_id].host.lower()]
        if parsed.filetype:
            ordered = [doc_id for doc_id in ordered if self.documents[doc_id].doc_type.lower() == parsed.filetype]
        return ordered[:limit]

    def compare_personalization(self, query: str) -> dict[str, SearchResponse]:
        profiles = {
            "guest": None,
            "student": {"id": None, "role": "本科生", "interests": '["教务","课程","就业"]'},
            "teacher": {"id": None, "role": "教师", "interests": '["学术","图书馆"]'},
        }
        # The demo renders three profiles side-by-side. A compact candidate
        # window keeps the page responsive and makes profile-specific reranking
        # visible instead of letting broad, generic pages dominate all panels.
        return {name: self.search(query, user=user, candidate_limit=2500) for name, user in profiles.items()}
