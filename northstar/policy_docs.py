"""Builds the Policy Studio source-material ZIP (policy draft + evaluation questions only)."""

from __future__ import annotations

import io
import zipfile
from importlib import resources

from .labels import evaluation_csv_text

ZIP_NAME = "northstar-retail-policy-studio.zip"
POLICY_NAME = "retail-customer-support-policy-studio.md"
CSV_NAME = "retail-customer-support-evaluation-questions.csv"


def policy_markdown() -> str:
    return resources.files("northstar.data").joinpath("policy_draft.md").read_text(encoding="utf-8")


def build_zip() -> bytes:
    buf = io.BytesIO()
    fixed_time = (2026, 1, 1, 0, 0, 0)  # deterministic archive bytes
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in ((POLICY_NAME, policy_markdown()), (CSV_NAME, evaluation_csv_text())):
            info = zipfile.ZipInfo(name, date_time=fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            # Plain UTF-8 (no BOM) so the header row is exactly "test_id,...".
            zf.writestr(info, text.encode("utf-8"))
    return buf.getvalue()
