"""Deterministic keyword retrieval over the local Northstar support handbook."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Iterable

SOURCE_NAME = "Northstar support handbook"
FALLBACK_ID = "support-scope"
MAX_ARTICLES = 4

# Weights: a term in the title or keyword list is a stronger signal than one in the body,
# and a multi-word keyword phrase found intact in the question earns an extra bonus.
TITLE_WEIGHT = 3
KEYWORD_TERM_WEIGHT = 3
TEXT_WEIGHT = 1
PHRASE_BONUS = 4

STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers herself him himself his how i if in into is it its itself
    just me more most my myself no nor not now of off on once only or other our ours ourselves out
    over own same she should so some such than that the their theirs them themselves then there
    these they this those through to too under until up very was we were what when where which
    while who whom why will with would you your yours yourself yourselves ive im id dont cant
    please hi hello thanks thank also get got still may might must shall us let lets
    """.split()
) | {"northstar"}  # the store name appears everywhere, so it carries no retrieval signal

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def _normalise_phrase(text: str) -> str:
    return " ".join(_TOKEN_RE.findall(text.lower()))


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    keywords: tuple[str, ...]
    text: str
    source: str = SOURCE_NAME

    def evidence(self) -> dict:
        return {"id": self.id, "title": self.title, "source": self.source, "text": self.text}


def load_articles() -> list[Article]:
    raw = resources.files("northstar.data").joinpath("knowledge.json").read_text(encoding="utf-8")
    return [
        Article(
            id=item["id"],
            title=item["title"],
            keywords=tuple(item["keywords"]),
            text=item["text"],
            source=item.get("source", SOURCE_NAME),
        )
        for item in json.loads(raw)
    ]


def score_article(article: Article, question_terms: set[str], question_phrase: str) -> int:
    if not question_terms:
        return 0
    title_terms = set(tokenize(article.title))
    keyword_terms = set(t for k in article.keywords for t in tokenize(k))
    text_terms = set(tokenize(article.text))
    score = 0
    score += TITLE_WEIGHT * len(question_terms & title_terms)
    score += KEYWORD_TERM_WEIGHT * len(question_terms & keyword_terms)
    score += TEXT_WEIGHT * len(question_terms & text_terms)
    padded = f" {question_phrase} "
    for kw in article.keywords:
        phrase = _normalise_phrase(kw)
        if phrase and f" {phrase} " in padded:
            score += PHRASE_BONUS * max(1, len(phrase.split()))
    return score


@dataclass(frozen=True)
class RetrievalResult:
    articles: tuple[Article, ...]
    scores: tuple[int, ...]
    fallback: bool

    def evidence(self) -> list[dict]:
        return [a.evidence() for a in self.articles]


def retrieve(question: str, articles: Iterable[Article], limit: int = MAX_ARTICLES) -> RetrievalResult:
    articles = list(articles)
    terms = set(tokenize(question))
    phrase = _normalise_phrase(question)
    scored = [(score_article(a, terms, phrase), a) for a in articles]
    positive = [(s, a) for s, a in scored if s > 0]
    # Highest score first; ties broken deterministically by article ID.
    positive.sort(key=lambda sa: (-sa[0], sa[1].id))
    chosen = positive[:limit]
    if not chosen:
        fallback = next(a for a in articles if a.id == FALLBACK_ID)
        return RetrievalResult(articles=(fallback,), scores=(0,), fallback=True)
    return RetrievalResult(
        articles=tuple(a for _, a in chosen), scores=tuple(s for s, _ in chosen), fallback=False
    )
