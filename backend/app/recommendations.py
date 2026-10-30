"""Prioritised, actionable recommendations linked to metric failures.

Recommendations are templates driven by measured failures. They are advice for human
reviewers; the system never acts on a claim.
"""
from typing import List

from .metrics import SEVERITY_RANK, EvaluationResult

TEMPLATES = {
    "process_compliance": (
        "Review approved/paid claims that skipped mandatory controls",
        "Have a senior reviewer manually re-examine each affected claim. Add a workflow gate that blocks "
        "approval until the policy check and required documents are recorded.",
    ),
    "payment": (
        "Investigate payment amount inconsistencies",
        "Reconcile approved and paid amounts against the payment system for each affected claim. "
        "Add validation so paid <= approved <= claimed at data entry.",
    ),
    "policy_check": (
        "Complete or document missing policy checks",
        "Confirm whether the policy check was done but not recorded, or not done. Make the check a required step before a decision.",
    ),
    "duplicates": (
        "Resolve possible duplicate claims",
        "Compare each duplicate group, keep the legitimate record and document the decision. Add a duplicate check at intake.",
    ),
    "sla": (
        "Reduce SLA breaches",
        "Review the slowest and oldest open claims first; look for bottlenecks by claim type or adjuster and add ageing alerts.",
    ),
    "documentation": (
        "Chase missing claim documents",
        "Contact claimants for outstanding documents and stop progressing claims whose required documents are incomplete.",
    ),
    "status_consistency": (
        "Fix status / date / amount contradictions",
        "Correct records where the status disagrees with dates or amounts, and tighten the status-change rules in the claims system.",
    ),
    "required_fields": (
        "Fill in missing mandatory fields",
        "Add required-field validation at data entry and back-fill the affected claims from source documents.",
    ),
    "validity": (
        "Correct invalid data values",
        "Fix unparseable dates/numbers, negative values and unknown codes at source; apply input validation in the upstream system.",
    ),
}


def build_recommendations(result: EvaluationResult) -> List[dict]:
    examples = {}
    for o in result.observations:
        ids = examples.setdefault(o["metric"], [])
        if o["claim_id"] and o["claim_id"] not in ids and len(ids) < 5:
            ids.append(o["claim_id"])

    recs = []
    for m in result.metrics:
        if m["failed_count"] == 0:
            continue
        title, action = TEMPLATES[m["key"]]
        recs.append({
            "metric": m["key"],
            "severity": m["severity"],
            "title": title,
            "action": action,
            "affected_claims": m["failed_count"],
            "example_claim_ids": examples.get(m["key"], []),
            "evidence_hint": f"Filter observations by metric '{m['key']}' to see the evidence for every affected claim.",
            "requires_human_review": True,
        })
    recs.sort(key=lambda r: (SEVERITY_RANK[r["severity"]], -r["affected_claims"]))
    for i, r in enumerate(recs, start=1):
        r["priority"] = i
    return recs
