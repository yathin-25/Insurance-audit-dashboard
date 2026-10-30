import io

import pandas as pd
import pytest

from app.config import get_settings
from app.main import csv_safe
from app.metrics import evaluate
from app.recommendations import build_recommendations
from app.validation import UploadValidationError, parse_upload
from scripts.generate_synthetic import AS_OF, generate_claims

S = get_settings()
AS_OF_TS = pd.Timestamp(AS_OF)


def run(df, name="x.csv"):
    parsed = parse_upload(name, df.to_csv(index=False).encode(), S)
    return evaluate(parsed, AS_OF_TS)


def test_clean_synthetic_data_scores_perfect():
    df, _ = generate_claims(300, with_defects=False)
    res = run(df)
    assert res.observations == []
    assert res.overall["score"] == 100
    assert res.overall["caps_applied"] == []
    assert all(m["status"] in ("PASS", "N/A") for m in res.metrics)


def test_each_injected_defect_is_detected():
    df, injected = generate_claims(500, with_defects=True)
    res = run(df)
    flagged = {}
    for o in res.observations:
        flagged.setdefault(o["metric"], set()).add(o["claim_id"])
    for metric, ids in injected.items():
        for cid in ids:
            assert cid in flagged.get(metric, set()), f"{cid} not flagged by {metric}"


def test_average_cannot_hide_critical_failures():
    df, _ = generate_claims(500, with_defects=True)
    res = run(df)
    assert res.overall["weighted_score"] > 90  # plain average looks healthy...
    assert res.overall["score"] <= 59          # ...but critical failures cap it
    assert res.overall["band"] == "Critical issues present"
    assert res.kpis["claims_with_critical_issues"] >= 2


def test_observations_have_traceable_evidence_and_limited_fields():
    df, _ = generate_claims(500, with_defects=True)
    res = run(df)
    pay = [o for o in res.observations if o["metric"] == "payment"][0]
    assert set(pay["evidence"]) == {"claim_amount", "approved_amount", "paid_amount", "status"}
    assert pay["row_number"] >= 2 and pay["severity"] == "critical"


def test_recommendations_prioritised_by_severity():
    df, _ = generate_claims(500, with_defects=True)
    recs = build_recommendations(run(df))
    assert recs[0]["severity"] == "critical"
    assert [r["priority"] for r in recs] == list(range(1, len(recs) + 1))
    assert all(r["requires_human_review"] for r in recs)


def test_not_applicable_is_not_counted_as_pass():
    df, _ = generate_claims(100, with_defects=False)
    df["documents_required"] = 0
    res = run(df)
    doc = next(m for m in res.metrics if m["key"] == "documentation")
    assert doc["score"] is None and doc["status"] == "N/A"


def test_xlsx_upload_parses():
    df, _ = generate_claims(50, with_defects=False)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    parsed = parse_upload("claims.xlsx", buf.getvalue(), S)
    assert parsed.row_count == 50


@pytest.mark.parametrize("name,content,fragment", [
    ("evil.exe", b"MZ....", "Unsupported file type"),
    ("a.csv", b"", "empty"),
    ("a.csv", b"claim_id,status\nA,Paid\n", "Missing required column"),
    ("a.csv", b"\x00\x01\x02binary", "binary"),
    ("a.xlsx", b"not a zip file", "not a valid .xlsx"),
])
def test_structural_validation_errors_are_clear(name, content, fragment):
    with pytest.raises(UploadValidationError) as e:
        parse_upload(name, content, S)
    assert fragment in " ".join(e.value.errors)


def test_row_limit_enforced():
    df, _ = generate_claims(1200, with_defects=False)
    with pytest.raises(UploadValidationError):
        parse_upload("big.csv", df.to_csv(index=False).encode(), S)


def test_csv_formula_injection_neutralised():
    assert csv_safe("=HYPERLINK(...)").startswith("'")
    assert csv_safe("CLM-1") == "CLM-1"
