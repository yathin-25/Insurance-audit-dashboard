import io

from scripts.generate_synthetic import generate_claims
from tests.conftest import PASSWORD, auth


def csv_bytes(with_defects=True, n=300):
    df, _ = generate_claims(n, with_defects=with_defects)
    return df.to_csv(index=False).encode()


def upload(client, headers, content=None, origin="synthetic", name="claims.csv"):
    return client.post("/datasets", headers=headers, data={"data_origin": origin},
                       files={"file": (name, content if content is not None else csv_bytes(), "text/csv")})


def full_run(client):
    h = auth(client, "anna")
    ds = upload(client, h).json()["dataset_id"]
    r = client.post(f"/datasets/{ds}/evaluate", headers=h)
    assert r.status_code == 201, r.text
    return h, ds, r.json()["run_id"]


# ------------------------------------------------------------ authn / authz
def test_requests_without_token_are_rejected(client):
    for path in ("/runs", "/me", "/metrics/definitions", "/admin/audit"):
        assert client.get(path).status_code == 401


def test_bad_login_and_lockout(client):
    for _ in range(5):
        assert client.post("/auth/login", json={"username": "anna", "password": "wrong-password"}).status_code == 401
    # account now locked: even the correct password is refused
    assert client.post("/auth/login", json={"username": "anna", "password": PASSWORD}).status_code == 401


def test_tampered_token_rejected(client):
    h = auth(client, "anna")
    bad = {"Authorization": h["Authorization"][:-3] + "abc"}
    assert client.get("/me", headers=bad).status_code == 401


def test_viewer_cannot_upload_or_see_claims(client):
    _, _, run_id = full_run(client)
    v = auth(client, "vera")
    assert upload(client, v).status_code == 403
    assert client.get(f"/runs/{run_id}", headers=v).status_code == 200          # summary allowed
    assert client.get(f"/runs/{run_id}/claims", headers=v).status_code == 403   # claim level denied
    assert client.get(f"/runs/{run_id}/observations", headers=v).status_code == 403
    assert client.get(f"/runs/{run_id}/report.csv", headers=v).status_code == 403


def test_analyst_cannot_use_admin_endpoints(client):
    a = auth(client, "anna")
    assert client.get("/admin/audit", headers=a).status_code == 403
    assert client.post("/admin/users", headers=a, json={"username": "bob", "password": PASSWORD, "role": "admin"}).status_code == 403


# ------------------------------------------------------------ upload safety
def test_real_data_blocked_by_default(client):
    a = auth(client, "anna")
    r = upload(client, a, origin="real")
    assert r.status_code == 403


def test_bad_uploads_rejected_with_clear_errors(client):
    a = auth(client, "anna")
    r = upload(client, a, content=b"claim_id,status\nX,Paid\n")
    assert r.status_code == 400 and "Missing required column" in str(r.json())
    assert upload(client, a, content=b"MZ", name="x.exe").status_code == 400
    assert upload(client, a, content=b"a" * 3_000_000).status_code == 413
    assert upload(client, a, content=csv_bytes(), name="../../etc/passwd.csv").status_code == 201  # path stripped


# ------------------------------------------------------------ end to end
def test_end_to_end_flow(client):
    h, ds, run_id = full_run(client)
    summary = client.get(f"/runs/{run_id}", headers=h).json()
    assert summary["dataset"]["label"].startswith("SYNTHETIC")
    assert summary["kpis"]["total_claims"] == 301  # 300 + one injected duplicate row
    assert summary["overall"]["score"] <= 59
    assert summary["recommendations"][0]["severity"] == "critical"

    claims = client.get(f"/runs/{run_id}/claims?failing_only=true&sort_by=failure_count&order=desc", headers=h).json()
    assert claims["total"] >= 8
    detail = client.get(f"/runs/{run_id}/claims/{claims['items'][0]['row_number']}", headers=h).json()
    assert detail["observations"] and "evidence" in detail["observations"][0]

    obs = client.get(f"/runs/{run_id}/observations?severity=critical", headers=h).json()
    assert obs["total"] >= 2 and all(o["severity"] == "critical" for o in obs["items"])

    found = client.get(f"/runs/{run_id}/claims?search=CLM-10000", headers=h).json()
    assert found["total"] >= 1
    assert len(client.get("/runs", headers=h).json()) == 1


def test_export_exposes_no_amounts(client):
    h, _, run_id = full_run(client)
    r = client.get(f"/runs/{run_id}/report.csv", headers=h)
    header = r.text.splitlines()[0]
    assert header == "row_number,claim_id,score,failure_count,has_critical,failed_metrics"
    assert "claim_amount" not in r.text and "policy_number" not in r.text


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


# ------------------------------------------------------------ audit & deletion
def test_audit_log_records_actions_without_claim_data(client):
    h, ds, run_id = full_run(client)
    client.get(f"/runs/{run_id}/report.csv", headers=h)
    log = client.get("/admin/audit?limit=100", headers=auth(client, "adam")).json()
    actions = {e["action"] for e in log}
    assert {"login", "upload", "evaluate", "export"} <= actions
    blob = str(log)
    assert "CLM-" not in blob and "POL-" not in blob


def test_admin_delete_removes_data_and_file(client):
    h, ds, run_id = full_run(client)
    assert client.delete(f"/datasets/{ds}", headers=h).status_code == 403  # analyst cannot
    adm = auth(client, "adam")
    assert client.delete(f"/datasets/{ds}", headers=adm).status_code == 204
    assert client.get(f"/runs/{run_id}", headers=adm).status_code == 404


def test_weak_password_rejected_for_new_user(client):
    adm = auth(client, "adam")
    r = client.post("/admin/users", headers=adm, json={"username": "bob", "password": "short", "role": "viewer"})
    assert r.status_code == 422
