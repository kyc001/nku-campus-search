from __future__ import annotations

import html
import math
import re
from collections import Counter
from pathlib import Path

import jieba

from .config import CUSTOM_DICT_PATH

TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]+")
MARK_RE = re.compile(r"<[^>]+>")
MOJIBAKE_MARK_RE = re.compile(r"[\u0080-\u009f]|(?:[\u00c0-\u00ff][\u0080-\u00bf])|ï»¿|ã")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")
BOILERPLATE_WORDS = (
    "首页",
    "当前位置",
    "您当前的位置",
    "通知公告",
    "新闻动态",
    "学院新闻",
    "南开要闻",
    "媒体南开",
    "版权所有",
    "Copyright",
    "地址：",
    "邮编",
    "联系我们",
    "技术支持",
    "站点地图",
    "登录",
    "MENU",
    "Language",
)
NAV_MENU_WORDS = (
    "实习实践",
    "语言文字",
    "教材建设",
    "常用表格",
    "本科招生",
    "专业介绍",
    "教学运行",
    "选课管理",
    "四六级考试",
    "转专业",
    "助教管理",
    "学籍及毕业",
    "教学督导",
    "智慧书院",
    "办事流程",
    "招聘职位",
    "招聘信息",
    "招聘日历",
    "选调生",
    "国际组织",
    "宣讲会",
    "就业政策",
    "毕业填报",
    "下载专区",
)
CONTENT_ANCHOR_WORDS = (
    "发布时间",
    "发布日期",
    "日期：",
    "日期:",
    "时间：",
    "时间:",
    "地点：",
    "地点:",
    "浏览量",
    "人气：",
    "主题：",
    "主题:",
    "主讲人：",
    "主讲人:",
    "Abstract",
    "尊敬的",
    "为深入",
    "一、",
    "附件：",
    "附件:",
)
SECTION_TITLE_WORDS = (
    "新闻详细页",
    "通知公告",
    "工作动态",
    "双选会",
    "学术讲座",
    "活动预告",
)


def load_user_dict(path: Path = CUSTOM_DICT_PATH) -> None:
    if path.exists():
        jieba.load_userdict(str(path))


def normalize_text(text: str) -> str:
    text = repair_mojibake(text or "")
    text = html.unescape(text)
    text = MARK_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def repair_mojibake(text: str) -> str:
    """Repair common UTF-8-as-Latin-1 mojibake found in crawled legacy pages."""
    if not text:
        return ""
    sample = text[:4000]
    if not _looks_mojibake(sample):
        return text
    try:
        repaired = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
    if _repair_gain(text, repaired) <= 0:
        return text
    return repaired


def _looks_mojibake(text: str) -> bool:
    if not text:
        return False
    latin_noise = sum(1 for ch in text if 0x80 <= ord(ch) <= 0xFF)
    c1_controls = sum(1 for ch in text if 0x80 <= ord(ch) <= 0x9F)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    marker_hits = len(MOJIBAKE_MARK_RE.findall(text))
    return marker_hits >= 2 and latin_noise >= 4 and cjk < latin_noise


def _repair_gain(original: str, repaired: str) -> int:
    original_cjk = sum(1 for ch in original[:4000] if "\u4e00" <= ch <= "\u9fff")
    repaired_cjk = sum(1 for ch in repaired[:4000] if "\u4e00" <= ch <= "\u9fff")
    original_noise = len(MOJIBAKE_MARK_RE.findall(original[:4000]))
    repaired_noise = len(MOJIBAKE_MARK_RE.findall(repaired[:4000]))
    return (repaired_cjk - original_cjk) + (original_noise - repaired_noise)


def tokenize(text: str) -> list[str]:
    text = normalize_text(text).lower()
    tokens: list[str] = []
    for part in TOKEN_RE.findall(text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            tokens.extend(tok.strip().lower() for tok in jieba.lcut_for_search(part) if tok.strip())
        else:
            tokens.append(part)
    return [tok for tok in tokens if tok and not tok.isspace()]


def term_counter(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def cosine_score(query_tf: Counter[str], doc_tf: Counter[str], idf: dict[str, float]) -> float:
    if not query_tf or not doc_tf:
        return 0.0
    q_norm = 0.0
    d_norm = 0.0
    dot = 0.0
    for term, q_count in query_tf.items():
        weight = idf.get(term, 0.0)
        q_weight = (1.0 + math.log(q_count)) * weight
        q_norm += q_weight * q_weight
        if term in doc_tf:
            d_weight = (1.0 + math.log(doc_tf[term])) * weight
            dot += q_weight * d_weight
    for term, d_count in doc_tf.items():
        weight = idf.get(term, 0.0)
        d_weight = (1.0 + math.log(d_count)) * weight
        d_norm += d_weight * d_weight
    if q_norm == 0.0 or d_norm == 0.0:
        return 0.0
    return dot / math.sqrt(q_norm * d_norm)


def phrase_matches(text: str, phrase: str) -> bool:
    terms = [p for p in re.split(r"\s+", phrase.strip()) if p]
    if not terms:
        return True
    normalized = normalize_text(text).lower()
    pattern = r"[\s,，。；;：:、\-_/]*".join(re.escape(term.lower()) for term in terms)
    return re.search(pattern, normalized) is not None


def wildcard_to_regex(pattern: str) -> str:
    escaped = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return escaped


def highlight_terms(snippet: str, query_terms: list[str]) -> str:
    terms = sorted({term for term in query_terms if term}, key=len, reverse=True)
    if not terms:
        return html.escape(snippet)
    lowered = snippet.lower()
    spans: list[tuple[int, int]] = []
    for term in terms:
        needle = term.lower()
        start = 0
        while True:
            pos = lowered.find(needle, start)
            if pos < 0:
                break
            spans.append((pos, pos + len(term)))
            start = pos + max(len(term), 1)
    if not spans:
        return html.escape(snippet)
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    merged: list[tuple[int, int]] = []
    cursor = -1
    for start, end in spans:
        if start < cursor:
            continue
        merged.append((start, end))
        cursor = end
    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.append(html.escape(snippet[cursor:start]))
        parts.append(f"<mark>{html.escape(snippet[start:end])}</mark>")
        cursor = end
    parts.append(html.escape(snippet[cursor:]))
    return "".join(parts)


def _find_term_hits(lowered: str, query_terms: list[str]) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    seen_term: set[str] = set()
    for term in query_terms:
        needle = (term or "").lower()
        if not needle or needle in seen_term:
            continue
        seen_term.add(needle)
        start = 0
        while True:
            pos = lowered.find(needle, start)
            if pos < 0:
                break
            spans.append((pos, pos + len(needle), needle))
            start = pos + max(len(needle), 1)
    spans.sort(key=lambda item: item[0])
    return spans


def _snippet_terms(query_terms: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in query_terms:
        clean = normalize_text(term).lower()
        if not clean or clean in seen:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]", clean):
            continue
        seen.add(clean)
        terms.append(clean)
    return terms


def _boilerplate_penalty(text: str) -> float:
    lowered = text.lower()
    penalty = 0.0
    for word in BOILERPLATE_WORDS:
        if word.lower() in lowered:
            penalty += 1.4
    menu_hits = sum(1 for word in NAV_MENU_WORDS if word in text[:260])
    if menu_hits >= 5:
        penalty += 7.5
    elif menu_hits >= 3:
        penalty += 3.5
    short_tokens = re.findall(r"(?<![A-Za-z0-9])[\u4e00-\u9fffA-Za-z]{2,6}(?![A-Za-z0-9])", text[:140])
    if len(short_tokens) >= 12 and "。" not in text[:140]:
        penalty += 3.0
    if re.search(r"(上一页|下一页|尾页|第\s*\d+\s*页)", text[:180]):
        penalty += 2.0
    if _nav_density(text[:220]) >= 0.22:
        penalty += 4.0
    return penalty


def _nav_density(text: str) -> float:
    if not text:
        return 0.0
    hits = sum(1 for word in NAV_MENU_WORDS if word in text)
    short_tokens = re.findall(r"[\u4e00-\u9fffA-Za-z]{2,8}", text)
    if not short_tokens:
        return 0.0
    return hits / max(len(short_tokens), 1)


def _find_content_anchor_starts(text: str, length: int) -> list[int]:
    starts: list[int] = []
    scan_limit = min(len(text), 5000)
    for marker in CONTENT_ANCHOR_WORDS:
        for match in re.finditer(re.escape(marker), text[:scan_limit], flags=re.IGNORECASE):
            start = max(0, match.start() - min(96, length // 2))
            starts.append(_trim_structural_start(text, start, match.start()))
    for marker in SECTION_TITLE_WORDS:
        for match in re.finditer(re.escape(marker), text[:scan_limit], flags=re.IGNORECASE):
            starts.append(_trim_structural_start(text, match.start(), match.start()))
    return sorted(set(starts))


def _trim_structural_start(text: str, start: int, anchor: int) -> int:
    prefix = text[start:anchor]
    if not prefix:
        return start
    # If the anchor is preceded by a dense menu trail, jump to the last visible
    # section marker instead of showing the whole navigation bar.
    marker_pos = -1
    for marker in SECTION_TITLE_WORDS:
        pos = prefix.rfind(marker)
        if pos > marker_pos:
            marker_pos = pos
    if marker_pos >= 0 and (_nav_density(prefix[:marker_pos]) >= 0.12 or len(prefix) > 70):
        return start + marker_pos
    return start


def _trim_boilerplate_prefix(text: str) -> str:
    snippet = text.strip()
    if len(snippet) < 40:
        return snippet
    prefix = snippet[:260]
    location = re.search(r"(?:您当前的位置|当前位置)\s*[：:]", prefix)
    if location:
        cut_region = prefix[location.start() :]
        markers = [m.end() for m in re.finditer(r">>|＞|>", cut_region)]
        if markers:
            snippet = cut_region[markers[-1] :].strip()
        else:
            snippet = cut_region[location.end() - location.start() :].strip()
    while snippet.startswith((">", "＞", "»", "：", ":", "-", "—")):
        snippet = snippet[1:].strip()
    return snippet


def _first_meaningful_passage(text: str, length: int) -> str:
    passages = [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    for passage in passages:
        if len(passage) < 12:
            continue
        if _boilerplate_penalty(passage[: min(len(passage), length)]) >= 4.0:
            continue
        return _fit_snippet(passage, length)
    return _fit_snippet(text, length)


def _fit_snippet(text: str, length: int) -> str:
    text = _trim_boilerplate_prefix(text)
    if len(text) <= length:
        return text
    cut = text[:length].rstrip()
    boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind(";"), cut.rfind("，"), cut.rfind(","))
    if boundary >= max(30, int(length * 0.45)):
        cut = cut[: boundary + 1]
    return cut.rstrip() + "..."


def _candidate_windows(text: str, hits: list[tuple[int, int, str]], length: int) -> list[tuple[str, bool]]:
    windows: list[tuple[str, bool]] = []
    text_len = len(text)
    for pos, _, _ in hits:
        start = max(0, pos - length // 3)
        end = min(text_len, start + length)
        start = max(0, end - length)
        left_boundary = max(text.rfind("。", 0, pos), text.rfind("；", 0, pos), text.rfind("!", 0, pos), text.rfind("?", 0, pos))
        right_candidates = [idx for idx in (text.find("。", pos), text.find("；", pos), text.find("!", pos), text.find("?", pos)) if idx >= 0]
        if left_boundary >= 0 and pos - left_boundary < length:
            start = left_boundary + 1
        if right_candidates:
            right_boundary = min(right_candidates) + 1
            if right_boundary - start <= length:
                end = right_boundary
        window = text[start:end].strip()
        if start > 0:
            window = "..." + window
        if end < text_len:
            window = window + "..."
        windows.append((window, start == 0))
    for start in _find_content_anchor_starts(text, length):
        end = min(text_len, start + length)
        window = text[start:end].strip()
        if start > 0:
            window = "..." + window
        if end < text_len:
            window = window + "..."
        window_lowered = window.lower()
        if any(term in window_lowered for _, _, term in hits):
            windows.append((window, start == 0))
    return windows


def _score_snippet_candidate(candidate: str, terms: list[str], starts_at_head: bool) -> float:
    lowered = candidate.lower()
    unique = {term for term in terms if term in lowered}
    hits = sum(lowered.count(term) for term in unique)
    score = len(unique) * 6.0 + hits * 1.5
    if len(unique) >= min(2, len(terms)):
        score += 2.0
    if any(anchor.lower() in lowered for anchor in CONTENT_ANCHOR_WORDS):
        score += 3.5
    if any(marker in candidate for marker in SECTION_TITLE_WORDS):
        score += 1.2
    if starts_at_head:
        score -= 1.0
    score -= _boilerplate_penalty(candidate)
    if len(candidate) < 30:
        score -= 1.0
    return score


def _best_window(
    text: str,
    hits: list[tuple[int, int, str]],
    length: int,
    nav_zone: int = 120,
) -> tuple[int, int]:
    """返回 hit 密度最高的窗口 [start, end)。

    评分：窗口内不同查询词数 ×3 + 命中次数 ×1，落在文档头部"导航区"扣 1.5 分，
    避开仅在菜单里出现一次的情况。
    """
    if not hits:
        return 0, min(length, len(text))
    best_score = -1.0
    best_start = max(0, hits[0][0] - length // 3)
    text_len = len(text)
    for anchor_pos, _, _ in hits:
        start = max(0, anchor_pos - length // 3)
        end = min(text_len, start + length)
        start = max(0, end - length)
        unique_terms: set[str] = set()
        total = 0
        for pos, end_pos, term in hits:
            if pos >= start and end_pos <= end:
                unique_terms.add(term)
                total += 1
            elif pos >= end:
                break
        score = len(unique_terms) * 3.0 + total
        if start < nav_zone:
            score -= 1.5
        if score > best_score:
            best_score = score
            best_start = start
    return best_start, min(text_len, best_start + length)


def make_snippet(text: str, query_terms: list[str], length: int = 180) -> str:
    text = normalize_text(text)
    if not text:
        return ""
    terms = _snippet_terms(query_terms)
    if not terms:
        return highlight_terms(_first_meaningful_passage(text, length), terms)
    lowered = text.lower()
    hits = _find_term_hits(lowered, terms)
    if not hits:
        return highlight_terms(_first_meaningful_passage(text, length), terms)
    candidates = _candidate_windows(text, hits, length)
    snippet = max(candidates, key=lambda item: _score_snippet_candidate(item[0], terms, item[1]))[0]
    snippet = _fit_snippet(snippet, length + 12)
    return highlight_terms(snippet, terms)
