from __future__ import annotations

import re

from .models import ParsedQuery
from .text import tokenize

PHRASE_RE = re.compile(r'"([^"]+)"|“([^”]+)”')
SITE_RE = re.compile(r"\bsite:([A-Za-z0-9_.:-]+)")
FILETYPE_RE = re.compile(r"\bfiletype:(pdf|doc|docx|xls|xlsx|html)\b", re.I)
REGEX_RE = re.compile(r"/([^/\n]{1,80})/")
WILDCARD_RE = re.compile(r"(?<!\S)([^\s\"“”/]*[*?][^\s\"“”/]*)")


def parse_query(raw: str, site: str = "", filetype: str = "") -> ParsedQuery:
    text = raw or ""
    phrases = [m.group(1) or m.group(2) for m in PHRASE_RE.finditer(text)]
    text = PHRASE_RE.sub(" ", text)

    site_match = SITE_RE.search(text)
    query_site = site or (site_match.group(1) if site_match else "")
    text = SITE_RE.sub(" ", text)

    filetype_match = FILETYPE_RE.search(text)
    query_filetype = (filetype or (filetype_match.group(1) if filetype_match else "")).lower()
    text = FILETYPE_RE.sub(" ", text)

    regex_match = REGEX_RE.search(text)
    regex = regex_match.group(1) if regex_match else ""
    text = REGEX_RE.sub(" ", text)

    wildcard_match = WILDCARD_RE.search(text)
    wildcard = wildcard_match.group(1) if wildcard_match else ""
    text = WILDCARD_RE.sub(" ", text)

    terms = tokenize(" ".join([text] + phrases))
    return ParsedQuery(
        raw=raw,
        terms=terms,
        phrases=phrases,
        site=query_site.lower(),
        filetype=query_filetype,
        wildcard=wildcard,
        regex=regex,
    )
