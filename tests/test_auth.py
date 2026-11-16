"""Authentication and session behaviour."""


def test_login_returns_token(client):
    token = client.login("bob", "password")
    assert token
    me = client.get("/api/v2/auth/me", token).json()["claims"]
    assert me["sub"] == "bob" and me["org_id"] == 10


def test_login_wrong_password(client):
    r = client.post("/api/v2/auth/login", json={"username": "bob", "password": "nope"},
                    headers={"X-Forwarded-For": "10.2.0.1"})
    assert r.status_code == 401


def test_mfa_required_for_grace(client):
    r = client.post("/api/v2/auth/login", json={"username": "grace", "password": "Gr@ce-Adm1n"},
                    headers={"X-Forwarded-For": "10.2.0.2"})
    assert r.json().get("mfa_required") is True


def test_register_creates_member_of_free_org(client):
    r = client.post("/api/v2/auth/register",
                    json={"username": "newbie", "email": "newbie@x.test", "password": "pw"})
    assert r.status_code == 200
    me = client.get("/api/v2/auth/me", r.json()["access_token"]).json()["claims"]
    assert me["org_id"] == 30


def test_me_lists_memberships(client):
    token = client.login("alice", "alice123")
    orgs = {m["org_id"] for m in client.get("/api/v2/auth/me", token).json()["claims"]["memberships"]}
    assert orgs == {10, 20}
