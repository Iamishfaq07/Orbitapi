"""The project authorization policy and its legitimate cross-tenant exceptions.

These cover the rules that must keep working: role-based access inside an org,
support staff, explicit shares, partner organisations and public projects.
"""


def test_member_reads_org_project(client):
    bob = client.login("bob", "password")
    assert client.get("/api/v2/projects/101", bob).status_code == 200


def test_owner_reads_own_private_project(client):
    bob = client.login("bob", "password")  # Bob owns Beta (102), which is private
    assert client.get("/api/v2/projects/102", bob).status_code == 200


def test_non_owner_member_blocked_from_private(client):
    svc = client.login("svc-reporting", "reporting")
    assert client.get("/api/v2/projects/102", svc).status_code == 403


def test_shared_user_reads_cross_tenant(client):
    # Alpha (Acme) is explicitly shared with Eve (Globex).
    eve = client.login("eve", "eve2024")
    assert client.get("/api/v2/projects/101", eve).status_code == 200


def test_partner_org_reads_partner_project(client):
    # Orbit Platform (103) is partner-visible; Globex is Acme's partner.
    eve = client.login("eve", "eve2024")
    assert client.get("/api/v2/projects/103", eve).status_code == 200


def test_unrelated_tenant_blocked(client):
    # Eve has no share or partnership giving her Acme's private Beta.
    eve = client.login("eve", "eve2024")
    assert client.get("/api/v2/projects/102", eve).status_code == 403


def test_public_project_readable_by_anyone(client):
    eve = client.login("eve", "eve2024")
    assert client.get("/api/v2/projects/301", eve).status_code == 200


def test_support_reads_every_tenant(client):
    frank = client.login("frank", "frank")
    for pid in (101, 102, 201, 202):
        assert client.get(f"/api/v2/projects/{pid}", frank).status_code == 200
