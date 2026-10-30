"""Deterministic, documented evaluation metrics.

Every metric returns:
  applicable : boolean Series - which claims the metric applies to (others are N/A, not "passed")
  failed     : {row_index: reason} - applicable claims that failed

score = 100 * (applicable - failed) / applicable   (None when nothing is applicable)

Overall score = weighted average of applicable metric scores, THEN capped so averages
cannot hide critical failures (see compute_overall).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .validation import ParsedData

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OPEN_STATUSES = {"Submitted", "Under Review", "Approved"}
TERMINAL_STATUSES = {"Rejected", "Paid", "Closed"}
VALID_STATUSES = OPEN_STATUSES | TERMINAL_STATUSES
DECIDED_STATUSES = {"Approved", "Rejected", "Paid", "Closed"}
VALID_CLAIM_TYPES = {"Auto", "Health", "Property", "Life", "Liability", "Travel"}
REQUIRED_FIELDS = ["claim_id", "policy_number", "claim_type", "date_reported", "status", "claim_amount"]

CRITICAL_CAP = 59.0
THRESHOLD_CAP = 79.0


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str
    definition: str
    formula: str
    required_fields: tuple
    threshold: float
    severity: str
    weight: float
    limitations: str
    evidence_fields: tuple


DEFAULT_METRICS: List[MetricDef] = [
    MetricDef(
        "required_fields", "Required-field completeness",
        "Share of claims where every mandatory field is present.",
        "claims with all of claim_id, policy_number, claim_type, date_reported, status, claim_amount "
        "present / all claims. Cells that are present but unparseable are counted under Data validity, not here.",
        tuple(REQUIRED_FIELDS), 98, "medium", 1.0,
        "Checks presence only, not correctness of the value.",
        ("status", "claim_type"),
    ),
    MetricDef(
        "documentation", "Documentation completeness",
        "Share of claims that received all documents they required.",
        "claims with documents_received >= documents_required / claims with documents_required > 0",
        ("documents_required", "documents_received"), 95, "medium", 1.5,
        "Counts documents, not their quality or relevance. N/A when documents_required is 0 or blank.",
        ("documents_required", "documents_received", "status"),
    ),
    MetricDef(
        "sla", "SLA adherence",
        "Share of measurable claims handled within the allowed number of days.",
        "closed claims: (date_closed - date_reported) <= sla_days; open claims: (as_of - date_reported) <= sla_days; "
        "score = within SLA / measurable claims",
        ("date_reported", "sla_days", "date_closed", "status"), 90, "medium", 1.5,
        "Uses calendar days. Terminal-status claims with no closing date cannot be measured (N/A; flagged by Status consistency). "
        "Open-claim result depends on the evaluation date (as_of).",
        ("date_reported", "date_closed", "sla_days", "status"),
    ),
    MetricDef(
        "policy_check", "Policy-check completion",
        "Share of decided claims for which a policy check was recorded as completed.",
        "decided claims (Approved/Rejected/Paid/Closed) with policy_check_completed = Yes / decided claims",
        ("status", "policy_check_completed"), 98, "high", 1.5,
        "Trusts the recorded flag; does not verify that the check was actually performed correctly.",
        ("status", "policy_check_completed"),
    ),
    MetricDef(
        "payment", "Payment amount consistency",
        "Share of claims with payment figures that are internally consistent.",
        "claims with approved or paid amount where: approved <= claim_amount, paid <= approved, "
        "and paid only exists if approved exists",
        ("claim_amount", "approved_amount", "paid_amount"), 99, "critical", 1.5,
        "Does not check amounts against policy limits, deductibles or external payment systems.",
        ("claim_amount", "approved_amount", "paid_amount", "status"),
    ),
    MetricDef(
        "status_consistency", "Workflow and status consistency",
        "Share of claims whose status agrees with their dates and amounts.",
        "claims with no violated rule: terminal status needs date_closed; open status must not have date_closed; "
        "date_closed >= date_reported; Paid needs paid_amount; Rejected must not have payment; Approved needs approved_amount",
        ("status", "date_reported", "date_closed", "approved_amount", "paid_amount"), 95, "medium", 1.0,
        "Rules are a simplified workflow model; adapt them to the company's real status lifecycle.",
        ("status", "date_reported", "date_closed", "approved_amount", "paid_amount"),
    ),
    MetricDef(
        "duplicates", "Duplicate claim detection",
        "Share of claims that are not duplicates of another claim in the file.",
        "claims with a unique claim_id AND unique (policy_number, claim_type, date_reported, claim_amount) / claims with a claim_id",
        ("claim_id", "policy_number", "claim_type", "date_reported", "claim_amount"), 99, "high", 1.0,
        "Exact matching only; near-duplicates (typos, split amounts) are not detected. Duplicates are flagged for review, never auto-removed.",
        ("policy_number", "claim_type", "date_reported", "claim_amount"),
    ),
    MetricDef(
        "validity", "Invalid or inconsistent data",
        "Share of claims with no invalid values.",
        "claims with no unparseable value, negative amount/count, future report date, unknown status or unknown claim_type / all claims",
        ("all columns",), 98, "medium", 1.0,
        "Allowed status and claim_type lists are defaults and should be configured per company.",
        ("status", "claim_type", "date_reported", "claim_amount"),
    ),
    MetricDef(
        "process_compliance", "Process compliance",
        "Share of approved/paid claims that passed the mandatory controls before approval.",
        "Approved or Paid claims with policy_check_completed = Yes AND all required documents received / "
        "Approved or Paid claims",
        ("status", "policy_check_completed", "documents_required", "documents_received"), 100, "critical", 2.0,
        "Intentionally overlaps Policy-check and Documentation: it isolates the high-risk case of money being approved without controls.",
        ("status", "policy_check_completed", "documents_required", "documents_received"),
    ),
]


# ---------------------------------------------------------------- helpers
@dataclass
class Ctx:
    df: pd.DataFrame
    bad: pd.DataFrame
    as_of: pd.Timestamp


def _istrue(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _rules(df: pd.DataFrame, rules) -> Dict[int, str]:
    failed: Dict[int, str] = {}
    for mask, msg in rules:
        mask = mask.fillna(False).astype(bool)
        for i in df.index[mask]:
            failed[i] = f"{failed[i]}; {msg}" if i in failed else msg
    return failed


def _py(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return int(f) if f.is_integer() else round(f, 2)
    return v


# ---------------------------------------------------------------- metrics
def m_required_fields(ctx: Ctx):
    df = ctx.df
    missing = df[REQUIRED_FIELDS].isna() & ~ctx.bad[REQUIRED_FIELDS]
    failed = {}
    for i in df.index[missing.any(axis=1)]:
        cols = [c for c in REQUIRED_FIELDS if missing.at[i, c]]
        failed[i] = f"Missing required field(s): {', '.join(cols)}"
    return pd.Series(True, index=df.index), failed


def m_documentation(ctx: Ctx):
    df = ctx.df
    req, rec = df["documents_required"], df["documents_received"]
    app = req.notna() & (req > 0)
    mask = app & (rec.isna() | (rec < req))
    failed = {}
    for i in df.index[mask]:
        got = "none recorded" if pd.isna(rec[i]) else str(int(rec[i]))
        failed[i] = f"Received {got} of {int(req[i])} required documents"
    return app, failed


def m_sla(ctx: Ctx):
    df = ctx.df
    rep, cl, sla, status = df["date_reported"], df["date_closed"], df["sla_days"], df["status"]
    closed = cl.notna()
    app = rep.notna() & sla.notna() & (closed | status.isin(OPEN_STATUSES))
    elapsed = pd.Series(np.where(closed, (cl - rep).dt.days, (ctx.as_of - rep).dt.days), index=df.index)
    mask = app & (elapsed > sla)
    failed = {}
    for i in df.index[mask]:
        kind = "Closed in" if closed[i] else "Still open after"
        failed[i] = f"{kind} {int(elapsed[i])} days; SLA is {int(sla[i])} days"
    return app, failed


def m_policy_check(ctx: Ctx):
    df = ctx.df
    app = df["status"].isin(DECIDED_STATUSES)
    done = _istrue(df["policy_check_completed"])
    failed = _rules(df, [(app & ~done, "Claim is decided but policy check not recorded as completed")])
    return app, failed


def m_payment(ctx: Ctx):
    df = ctx.df
    ca, ap, pa = df["claim_amount"], df["approved_amount"], df["paid_amount"]
    app = ap.notna() | pa.notna()
    failed = _rules(df, [
        (ca.notna() & ap.notna() & (ap > ca), "Approved amount exceeds claimed amount"),
        (pa.notna() & ap.isna(), "Payment recorded without an approved amount"),
        (pa.notna() & ap.notna() & (pa > ap), "Paid amount exceeds approved amount"),
    ])
    return app, failed


def m_status_consistency(ctx: Ctx):
    df = ctx.df
    st, cl, rep, ap, pa = df["status"], df["date_closed"], df["date_reported"], df["approved_amount"], df["paid_amount"]
    app = st.isin(VALID_STATUSES)
    failed = _rules(df, [
        (app & st.isin(TERMINAL_STATUSES) & cl.isna(), "Terminal status but no closing date"),
        (app & st.isin(OPEN_STATUSES) & cl.notna(), "Open status but a closing date is recorded"),
        (app & cl.notna() & rep.notna() & (cl < rep), "Closing date is before reported date"),
        (app & (st == "Paid") & pa.isna(), "Status is Paid but no paid amount"),
        (app & (st == "Rejected") & pa.notna() & (pa > 0), "Rejected claim has a payment recorded"),
        (app & (st == "Approved") & ap.isna(), "Status is Approved but no approved amount"),
    ])
    return app, failed


def m_duplicates(ctx: Ctx):
    df = ctx.df
    cid = df["claim_id"]
    app = cid.notna()
    counts = cid.map(cid.value_counts())
    dup_id = app & (counts > 1)
    key = ["policy_number", "claim_type", "date_reported", "claim_amount"]
    comp = df[key].notna().all(axis=1) & df.duplicated(subset=key, keep=False)
    failed = {}
    for i in df.index[dup_id]:
        failed[i] = f"Claim ID appears {int(counts[i])} times in the file"
    for i in df.index[comp & app]:
        failed.setdefault(i, "Same policy, type, date and amount as another claim")
    return app, failed


def m_validity(ctx: Ctx):
    df, bad = ctx.df, ctx.bad
    failed = {}
    for i in df.index[bad.any(axis=1)]:
        cols = [c for c in bad.columns if bad.at[i, c]]
        failed[i] = f"Invalid or unparseable value in: {', '.join(cols)}"
    extra = _rules(df, [
        ((df["claim_amount"] < 0) | (df["approved_amount"] < 0) | (df["paid_amount"] < 0), "Negative amount"),
        ((df["documents_required"] < 0) | (df["documents_received"] < 0) | (df["sla_days"] < 0), "Negative count or SLA value"),
        (df["date_reported"] > ctx.as_of, "Reported date is in the future"),
        (df["status"].notna() & ~df["status"].isin(VALID_STATUSES), "Unknown status value"),
        (df["claim_type"].notna() & ~df["claim_type"].isin(VALID_CLAIM_TYPES), "Unknown claim type"),
    ])
    for i, msg in extra.items():
        failed[i] = f"{failed[i]}; {msg}" if i in failed else msg
    return pd.Series(True, index=df.index), failed


def m_process_compliance(ctx: Ctx):
    df = ctx.df
    app = df["status"].isin({"Approved", "Paid"})
    no_check = ~_istrue(df["policy_check_completed"])
    req, rec = df["documents_required"], df["documents_received"]
    docs_short = req.notna() & (req > 0) & (rec.isna() | (rec < req))
    failed = _rules(df, [
        (app & no_check, "Approved/paid without a completed policy check"),
        (app & docs_short, "Approved/paid with incomplete required documents"),
    ])
    return app, failed


IMPLS = {
    "required_fields": m_required_fields, "documentation": m_documentation, "sla": m_sla,
    "policy_check": m_policy_check, "payment": m_payment, "status_consistency": m_status_consistency,
    "duplicates": m_duplicates, "validity": m_validity, "process_compliance": m_process_compliance,
}


def effective_defs(overrides: Optional[dict] = None) -> List[MetricDef]:
    """Apply configuration overrides ({key: {threshold, weight, severity}}) to the defaults."""
    out = []
    for d in DEFAULT_METRICS:
        o = (overrides or {}).get(d.key, {})
        allowed = {k: v for k, v in o.items() if k in ("threshold", "weight", "severity")}
        if allowed.get("severity") not in (None, *SEVERITY_RANK):
            raise ValueError("invalid severity override")
        out.append(replace(d, **allowed))
    return out


# ---------------------------------------------------------------- evaluation
@dataclass
class EvaluationResult:
    metrics: List[dict]
    claims: List[dict]
    observations: List[dict]
    overall: dict
    kpis: dict


def compute_overall(metrics: List[dict]) -> dict:
    applicable = [m for m in metrics if m["score"] is not None]
    if not applicable:
        return {"score": None, "weighted_score": None, "band": "Not enough data", "caps_applied": []}
    wsum = sum(m["weight"] for m in applicable)
    weighted = sum(m["score"] * m["weight"] for m in applicable) / wsum
    caps = []
    crit = sum(m["failed_count"] for m in metrics if m["severity"] == "critical")
    if crit:
        caps.append({"cap": CRITICAL_CAP, "reason": f"{crit} failure(s) in critical metrics"})
    failing = [m["name"] for m in applicable if m["status"] == "FAIL"]
    if failing:
        caps.append({"cap": THRESHOLD_CAP, "reason": f"Below threshold: {', '.join(failing)}"})
    score = min([weighted] + [c["cap"] for c in caps])
    if crit:
        band = "Critical issues present"
    elif score >= 90:
        band = "Good"
    elif score >= 75:
        band = "Needs attention"
    else:
        band = "Poor"
    return {"score": round(score, 2), "weighted_score": round(weighted, 2), "band": band, "caps_applied": caps}


def evaluate(parsed: ParsedData, as_of: pd.Timestamp, overrides: Optional[dict] = None) -> EvaluationResult:
    ctx = Ctx(parsed.df, parsed.bad, pd.Timestamp(as_of))
    df = ctx.df
    pos = {idx: p for p, idx in enumerate(df.index)}
    n = len(df)
    app_counts = np.zeros(n, dtype=int)
    fail_counts = np.zeros(n, dtype=int)
    critical = np.zeros(n, dtype=bool)
    observations, metrics = [], []

    for d in effective_defs(overrides):
        app, failed = IMPLS[d.key](ctx)
        app = app.astype(bool)
        failed = {i: r for i, r in failed.items() if app.at[i]}
        a, f = int(app.sum()), len(failed)
        score = None if a == 0 else round(100.0 * (a - f) / a, 2)
        status = "N/A" if score is None else ("PASS" if score >= d.threshold else "FAIL")
        app_counts += app.to_numpy().astype(int)
        for i, reason in failed.items():
            p = pos[i]
            fail_counts[p] += 1
            if d.severity == "critical":
                critical[p] = True
            observations.append({
                "row_number": int(i) + 2,
                "claim_id": _py(df.at[i, "claim_id"]),
                "metric": d.key,
                "severity": d.severity,
                "reason": reason,
                "evidence": {fld: _py(df.at[i, fld]) for fld in d.evidence_fields},
            })
        metrics.append({
            "key": d.key, "name": d.name, "score": score, "threshold": d.threshold, "status": status,
            "applicable_count": a, "failed_count": f, "severity": d.severity, "weight": d.weight,
        })

    claims = []
    for p, idx in enumerate(df.index):
        a = int(app_counts[p])
        claims.append({
            "row_number": int(idx) + 2,
            "claim_id": _py(df.at[idx, "claim_id"]),
            "score": None if a == 0 else round(100.0 * (a - int(fail_counts[p])) / a, 2),
            "failure_count": int(fail_counts[p]),
            "has_critical": bool(critical[p]),
        })

    overall = compute_overall(metrics)
    by_key = {m["key"]: m for m in metrics}
    kpis = {
        "total_claims": n,
        "overall_score": overall["score"],
        "documentation_completeness": by_key["documentation"]["score"],
        "sla_compliance": by_key["sla"]["score"],
        "policy_check_completion": by_key["policy_check"]["score"],
        "claims_with_critical_issues": int(critical.sum()),
        "claims_with_any_issue": int((fail_counts > 0).sum()),
    }
    return EvaluationResult(metrics, claims, observations, overall, kpis)
