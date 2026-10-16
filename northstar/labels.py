"""Evaluation annotations (suggested questions + evaluation CSV).

Labels are used only for scoring. They never influence enforcement: no code path reads
them before or during inspection.
"""

from __future__ import annotations

import csv
import io
import json
from importlib import resources
from typing import Optional


def load_suggestions() -> list[dict]:
    raw = resources.files("northstar.data").joinpath("suggestions.json").read_text(encoding="utf-8")
    return json.loads(raw)


def evaluation_csv_text() -> str:
    return resources.files("northstar.data").joinpath("evaluation_questions.csv").read_text(encoding="utf-8")


def load_evaluation_rows() -> list[dict]:
    return list(csv.DictReader(io.StringIO(evaluation_csv_text(), newline="")))


class LabelIndex:
    def __init__(self, suggestions: list[dict], evaluation_rows: list[dict]) -> None:
        self._index: dict[str, dict] = {}
        for row in evaluation_rows:
            self._index[row["customer_query"]] = {
                "case_id": row["test_id"],
                "expected": row["expected_action"],
                "source": "evaluation",
                "title": row["category"],
            }
        # Suggested questions take precedence for display titles.
        for s in suggestions:
            self._index[s["message"]] = {
                "case_id": s["id"],
                "expected": s["expected"],
                "source": "suggestion",
                "title": s["title"],
            }

    def lookup(self, question: str) -> Optional[dict]:
        """Exact match only (surrounding whitespace ignored). Edited text is unlabelled."""
        found = self._index.get(question.strip())
        return dict(found) if found else None

    @classmethod
    def default(cls) -> "LabelIndex":
        return cls(load_suggestions(), load_evaluation_rows())
