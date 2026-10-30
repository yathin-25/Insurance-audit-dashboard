"""Deterministic SYNTHETIC insurance claims. No real data is involved.

generate_claims(with_defects=False) -> clean data that should score 100 on every metric.
generate_claims(with_defects=True)  -> same data with known defects injected; the second return
value maps metric key -> claim_ids that SHOULD be flagged (used by tests as ground truth).

CLI:  python -m scripts.generate_synthetic --rows 500 --out sample_data/synthetic_claims.csv
"""
import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

AS_OF = date(2026, 10, 1)
TYPES = ["Auto", "Health", "Property", "Life", "Liability", "Travel"]
STATUSES = ["Submitted", "Under Review", "Approved", "Rejected", "Paid", "Closed"]
WEIGHTS = [10, 15, 15, 10, 30, 20]
OPEN = {"Submitted", "Under Review", "Approved"}
COLUMNS = ["claim_id", "policy_number", "claim_type", "date_reported", "status", "claim_amount",
           "documents_required", "documents_received", "policy_check_completed", "sla_days",
           "date_closed", "approved_amount", "paid_amount", "adjuster_id"]


def _iso(d):
    return d.isoformat() if d else ""


def generate_claims(n=500, seed=42, with_defects=True, as_of=AS_OF):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        status = rng.choices(STATUSES, WEIGHTS)[0]
        amount = round(rng.uniform(500, 50000), 2)
        docs = rng.randint(3, 5)
        if status in OPEN:
            reported, closed = as_of - timedelta(days=rng.randint(1, 25)), None
        else:
            reported = as_of - timedelta(days=rng.randint(40, 300))
            closed = reported + timedelta(days=rng.randint(3, 25))
        approved = round(amount * 0.9, 2) if status in ("Approved", "Paid", "Closed") else None
        paid = approved if status in ("Paid", "Closed") else None
        check = rng.choice(["Yes", "No"]) if status == "Under Review" else ("No" if status == "Submitted" else "Yes")
        rows.append({
            "claim_id": f"CLM-{100000 + i}", "policy_number": f"POL-{500000 + i}",
            "claim_type": rng.choice(TYPES), "date_reported": _iso(reported), "status": status,
            "claim_amount": amount, "documents_required": docs, "documents_received": docs,
            "policy_check_completed": check, "sla_days": 30, "date_closed": _iso(closed),
            "approved_amount": "" if approved is None else approved,
            "paid_amount": "" if paid is None else paid, "adjuster_id": f"ADJ-{rng.randint(1, 12):02d}",
        })

    injected = {}
    if with_defects:
        used = set()

        def pick(status):
            for r in rows:
                if r["status"] == status and r["claim_id"] not in used:
                    used.add(r["claim_id"])
                    return r
            raise RuntimeError(f"not enough {status} rows; increase n")

        def mark(metric, r):
            injected.setdefault(metric, []).append(r["claim_id"])

        r = pick("Paid"); r["policy_check_completed"] = "No"; mark("policy_check", r); mark("process_compliance", r)
        r = pick("Under Review"); r["documents_received"] = r["documents_required"] - 2; mark("documentation", r)
        r = pick("Closed")
        r["date_closed"] = _iso(date.fromisoformat(r["date_reported"]) + timedelta(days=60)); mark("sla", r)
        r = pick("Approved"); rows.append(dict(r)); mark("duplicates", r)
        r = pick("Paid"); r["paid_amount"] = round(r["approved_amount"] * 1.5, 2); mark("payment", r)
        r = pick("Submitted"); r["claim_amount"] = ""; mark("required_fields", r)
        r = pick("Under Review"); r["claim_amount"] = "abc"; mark("validity", r)
        r = pick("Rejected"); r["paid_amount"] = 100; mark("status_consistency", r)

    return pd.DataFrame(rows, columns=COLUMNS), injected


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--clean", action="store_true", help="no injected defects")
    p.add_argument("--out", default="sample_data/synthetic_claims.csv")
    a = p.parse_args()
    df, _ = generate_claims(a.rows, a.seed, with_defects=not a.clean)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} SYNTHETIC claims to {out}")
