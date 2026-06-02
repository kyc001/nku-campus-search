from __future__ import annotations

from collections import defaultdict

from .models import Document


def compute_pagerank(documents: list[Document], iterations: int = 30, damping: float = 0.85) -> dict[str, float]:
    urls = {doc.url for doc in documents}
    if not urls:
        return {}
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = defaultdict(set)
    for doc in documents:
        outs = {url for url in doc.outlinks if url in urls and url != doc.url}
        outgoing[doc.url] = outs
        for dst in outs:
            incoming[dst].add(doc.url)
    n = len(urls)
    ranks = {url: 1.0 / n for url in urls}
    base = (1.0 - damping) / n
    for _ in range(iterations):
        new_ranks = {url: base for url in urls}
        dangling = sum(ranks[url] for url, outs in outgoing.items() if not outs)
        dangling_share = damping * dangling / n
        for url in urls:
            new_ranks[url] += dangling_share
            for src in incoming[url]:
                out_degree = max(len(outgoing[src]), 1)
                new_ranks[url] += damping * ranks[src] / out_degree
        ranks = new_ranks
    max_rank = max(ranks.values()) if ranks else 1.0
    return {url: (rank / max_rank if max_rank else 0.0) for url, rank in ranks.items()}


def apply_link_analysis(documents: list[Document]) -> list[Document]:
    ranks = compute_pagerank(documents)
    inlinks: dict[str, int] = defaultdict(int)
    urls = {doc.url for doc in documents}
    for doc in documents:
        for out in doc.outlinks:
            if out in urls:
                inlinks[out] += 1
    for doc in documents:
        doc.pagerank = round(ranks.get(doc.url, 0.0), 6)
        doc.inlinks_count = inlinks.get(doc.url, 0)
    return documents
