"""Multi-org membership, role hierarchy and support tooling."""


def test_switch_active_org(client):
    alice = client.login("alice", "alice123")  # member of org 10, viewer of org 20
    switched = client.post("/api/v2/auth/switch-org/20", alice).json()
    me = client.get("/api/v2/auth/me", switched["access_token"]).json()["claims"]
    assert me["org_id"] == 20 and me["role"] == "viewer"


def test_org_projects_scoped_to_active_org(client):
    charlie = client.login("charlie", "Charlie!2024")  # owner of org 20
    rows = client.get("/org/projects", charlie).json()
    assert {p["id"] for p in rows} == {201, 202}


def test_support_sees_all_tickets(client):
    frank = client.login("frank", "frank")
    orgs = {t["org_id"] for t in client.get("/api/v2/tickets", frank).json()}
    assert orgs == {10, 20}


def test_regular_user_sees_only_own_tickets(client):
    bob = client.login("bob", "password")
    rows = client.get("/api/v2/tickets", bob).json()
    assert all(t["user_id"] == 2 for t in rows)


def test_org_owner_reads_private_project(client):
    # Grace owns org 10; owners/admins may read private projects in their org.
    grace = client.login("grace", "Gr@ce-Adm1n")
    assert client.get("/api/v2/projects/102", grace).status_code == 200
