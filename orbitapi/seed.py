"""Database schema and sample data, loaded on first start."""
import hashlib
import os
import shutil

from . import config, db


def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


SCHEMA = """
DROP TABLE IF EXISTS organizations;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS memberships;
DROP TABLE IF EXISTS partnerships;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS project_shares;
DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS coupons;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS files;
DROP TABLE IF EXISTS webhooks;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS api_keys;
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS saved_views;

CREATE TABLE organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT NOT NULL,
    api_key TEXT NOT NULL,
    billing_email TEXT,
    seats INTEGER DEFAULT 5,
    is_support_provider INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_md5 TEXT NOT NULL,
    home_org_id INTEGER NOT NULL,
    clearance TEXT NOT NULL DEFAULT 'standard',
    is_support INTEGER NOT NULL DEFAULT 0,
    full_name TEXT,
    phone TEXT,
    ssn TEXT,
    address TEXT,
    credit_balance INTEGER NOT NULL DEFAULT 0,
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    otp_code TEXT,
    reset_token TEXT,
    avatar_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- A user can belong to several organisations, with a different role in each.
CREATE TABLE memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Directed trust between orgs (partner_org may access partner-scoped resources of org).
CREATE TABLE partnerships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL,
    partner_org_id INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'projects:read'
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    budget INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    visibility TEXT NOT NULL DEFAULT 'org',
    last_invoice_id INTEGER
);

-- A project may be shared with an individual user or a whole org, at read or write.
CREATE TABLE project_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    principal_type TEXT NOT NULL,
    principal_id INTEGER NOT NULL,
    access TEXT NOT NULL DEFAULT 'read'
);

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by INTEGER,
    approved_by INTEGER
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    price_cents INTEGER NOT NULL,
    stock INTEGER NOT NULL,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    internal_cost_cents INTEGER,
    supplier TEXT
);

CREATE TABLE coupons (
    code TEXT PRIMARY KEY,
    discount_pct INTEGER NOT NULL,
    max_uses INTEGER NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    staff_only INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    coupon_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    shipping_address TEXT,
    card_last4 TEXT,
    card_number TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER,
    to_user_id INTEGER,
    amount INTEGER NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT,
    size INTEGER,
    is_private INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    event TEXT NOT NULL,
    signing_secret TEXT NOT NULL
);

CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'normal',
    internal_notes TEXT,
    assigned_to INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_private INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    actor TEXT,
    ip TEXT,
    action TEXT,
    detail TEXT
);

CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    name TEXT,
    token TEXT NOT NULL,
    scopes TEXT DEFAULT 'read',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_name TEXT,
    body TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subscriptions (
    org_id INTEGER PRIMARY KEY,
    plan TEXT NOT NULL,
    seats INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    renews_at TEXT,
    mrr_cents INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE saved_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    blob TEXT NOT NULL
);
"""

# (id, name, plan, api_key, billing_email, seats, is_support_provider)
ORGS = [
    (10, "Acme Robotics", "enterprise", "org10_live_4c1d2a9e8b7f", "finance@acme.test", 50, 0),
    (20, "Globex Labs", "pro", "org20_live_77aa0b1c2d3e", "ap@globex.test", 20, 0),
    (30, "Initech Support", "partner", "org30_live_0000deadbeef", "it@initech.test", 10, 1),
]

# (id, username, email, password, home_org, clearance, is_support, full_name, phone, ssn, addr, bal, mfa, otp)
USERS = [
    (1, "alice", "alice@acme.test", "alice123", 10, "standard", 0, "Alice Archer",
     "+1-555-0101", "123-45-6789", "1 Market St, SF", 5000, 1, "4821"),
    (2, "bob", "bob@acme.test", "password", 10, "standard", 0, "Bob Builder",
     "+1-555-0102", "234-56-7890", "2 Mission St, SF", 2500, 0, None),
    (3, "charlie", "charlie@globex.test", "Charlie!2024", 20, "elevated", 0, "Charlie Chen",
     "+1-555-0103", "345-67-8901", "3 Castro St, MV", 10000, 0, None),
    (4, "diana", "diana@acme.test", "billing", 10, "finance", 0, "Diana Diaz",
     "+1-555-0104", "456-78-9012", "4 Folsom St, SF", 0, 0, None),
    (5, "eve", "eve@globex.test", "eve2024", 20, "standard", 0, "Eve Evans",
     "+1-555-0105", "567-89-0123", "5 Shoreline, MV", 100, 0, None),
    (6, "frank", "frank@initech.test", "frank", 30, "standard", 1, "Frank Fisher",
     "+1-555-0106", "678-90-1234", "6 Penny Ln, Austin", 0, 0, None),
    (7, "grace", "grace@acme.test", "Gr@ce-Adm1n", 10, "elevated", 0, "Grace Hopper",
     "+1-555-0107", "789-01-2345", "7 Navy Yard, DC", 25000, 1, "0937"),
    (8, "svc-reporting", "svc@acme.test", "reporting", 10, "elevated", 0, "Reporting Bot",
     None, None, None, 0, 0, None),
]

# (user_id, org_id, role) — the authority of record for every per-tenant check.
MEMBERSHIPS = [
    (1, 10, "member"),
    (1, 20, "viewer"),
    (2, 10, "member"),
    (3, 20, "owner"),
    (4, 10, "admin"),
    (5, 20, "member"),
    (6, 30, "member"),
    (7, 10, "owner"),
    (8, 10, "member"),
]

# Acme and Globex are partners; each may read the other's partner-scoped projects.
PARTNERSHIPS = [
    (10, 20, "projects:read"),
    (20, 10, "projects:read"),
]

# (id, org_id, owner_id, name, sensitivity, budget, status, visibility)
PROJECTS = [
    (101, 10, 1, "Alpha", "internal", 50000, "active", "org"),
    (102, 10, 2, "Beta", "confidential", 120000, "active", "private"),
    (103, 10, 7, "Orbit Platform", "internal", 300000, "active", "partners"),
    (201, 20, 3, "Gamma", "internal", 80000, "active", "org"),
    (202, 20, 5, "Delta", "confidential", 40000, "active", "private"),
    (301, 30, 6, "Support Runbook", "internal", 0, "active", "public"),
]

# (project_id, principal_type, principal_id, access)
PROJECT_SHARES = [
    (101, "user", 2, "read"),
    (101, "user", 5, "read"),
    (103, "org", 20, "read"),
]

# (id, project_id, org_id, amount, status, created_by)
INVOICES = [
    (501, 101, 10, 15000, "draft", 1),
    (502, 102, 10, 40000, "issued", 2),
    (503, 201, 20, 22000, "draft", 3),
]

PRODUCTS = [
    (1, "Orbit Starter Seat", "One seat, monthly", 1900, 1000, 0, 400, "internal"),
    (2, "Orbit Pro Seat", "One pro seat, monthly", 4900, 1000, 0, 900, "internal"),
    (3, "Telemetry Add-on", "Usage analytics", 9900, 50, 0, 2500, "Datadog-ish Inc"),
    (4, "Hardware Beacon", "Physical tracker", 2500, 3, 0, 1800, "Shenzhen Parts Co"),
    (5, "Employee Discount Bundle", "Staff purchase bundle", 100, 500, 1, 3000, "internal"),
    (6, "Orbit AI", "Launches Q3", 19900, 10, 1, 7000, "internal"),
]

COUPONS = [
    ("WELCOME10", 10, 1000, 0, 1, 0),
    ("ONETIME50", 50, 1, 0, 1, 0),
    ("STAFF100", 100, 9999, 0, 1, 1),
    ("EXPIRED75", 75, 100, 0, 0, 0),
]

# (id, user_id, org_id, product_id, qty, unit, total, coupon, status, addr, last4, card)
ORDERS = [
    (1, 1, 10, 2, 3, 4900, 14700, None, "paid", "1 Market St, SF", "4242", "4242424242424242"),
    (2, 2, 10, 3, 1, 9900, 9900, "WELCOME10", "shipped", "2 Mission St, SF", "1881", "4000056655665556"),
    (3, 5, 20, 1, 10, 1900, 19000, None, "paid", "5 Shoreline, MV", "0005", "5555555555554444"),
    (4, 3, 20, 4, 1, 2500, 2500, None, "pending", "3 Castro St, MV", "1117", "378282246310005"),
]

TICKETS = [
    (1, 1, 10, "Cannot export report", "Export button spins forever.", "open", "normal",
     "Customer on legacy plan, do not offer refund. S3 creds rotated (AKIA3ORBIT7X2QPLM9DZ).", 6),
    (2, 5, 20, "Billing question", "Why was I charged twice?", "open", "high",
     "Duplicate charge confirmed; card 5555555555554444 refunded manually.", 6),
    (3, 2, 10, "Feature request", "Dark mode please", "closed", "low", "Wontfix.", None),
]

NOTES = [
    (1, 1, 10, "Alpha launch plan", "Launch on Friday. Board not informed yet.", 1),
    (2, 2, 10, "Beta budget", "We are 40k over budget on Beta.", 1),
    (3, 3, 20, "Acquisition target", "Globex intends to acquire Acme in Q4. CONFIDENTIAL.", 1),
    (4, 7, 10, "Admin recovery codes", "recovery: 1111-2222-3333 / 4444-5555-6666", 1),
    (5, 1, 10, "Team lunch", "Tacos on Tuesday", 0),
]

WEBHOOKS = [
    (1, 3, 20, "https://hooks.globex.test/orbit", "order.paid", "whsec_globex_8c7b6a"),
]


def seed() -> None:
    db.script(SCHEMA)
    for o in ORGS:
        db.execute("INSERT INTO organizations VALUES (?,?,?,?,?,?,?)", o)
    for u in USERS:
        (uid, username, email, pw, home, clr, sup, name, phone, ssn, addr, bal, mfa, otp) = u
        db.execute(
            "INSERT INTO users (id, username, email, password_md5, home_org_id, clearance, is_support,"
            " full_name, phone, ssn, address, credit_balance, mfa_enabled, otp_code)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, username, email, md5(pw), home, clr, sup, name, phone, ssn, addr, bal, mfa, otp),
        )
    for m in MEMBERSHIPS:
        db.execute("INSERT INTO memberships (user_id, org_id, role) VALUES (?,?,?)", m)
    for p in PARTNERSHIPS:
        db.execute("INSERT INTO partnerships (org_id, partner_org_id, scope) VALUES (?,?,?)", p)
    for p in PROJECTS:
        db.execute("INSERT INTO projects (id, org_id, owner_id, name, sensitivity, budget, status, visibility)"
                   " VALUES (?,?,?,?,?,?,?,?)", p)
    for s in PROJECT_SHARES:
        db.execute("INSERT INTO project_shares (project_id, principal_type, principal_id, access) VALUES (?,?,?,?)", s)
    for inv in INVOICES:
        db.execute("INSERT INTO invoices (id, project_id, org_id, amount, status, created_by) VALUES (?,?,?,?,?,?)", inv)
    for p in PRODUCTS:
        db.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)", p)
    for c in COUPONS:
        db.execute("INSERT INTO coupons VALUES (?,?,?,?,?,?)", c)
    for o in ORDERS:
        db.execute(
            "INSERT INTO orders (id, user_id, org_id, product_id, quantity, unit_price_cents, total_cents,"
            " coupon_code, status, shipping_address, card_last4, card_number) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", o)
    for t in TICKETS:
        db.execute(
            "INSERT INTO tickets (id, user_id, org_id, subject, body, status, priority, internal_notes, assigned_to)"
            " VALUES (?,?,?,?,?,?,?,?,?)", t)
    for n in NOTES:
        db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?)", n)
    for w in WEBHOOKS:
        db.execute("INSERT INTO webhooks VALUES (?,?,?,?,?,?)", w)
    db.execute("INSERT INTO transactions (from_user_id, to_user_id, amount, note) VALUES (?,?,?,?)",
               (3, 1, 500, "consulting fee"))
    for i, (uid, org, name) in enumerate([(7, 10, "grace-ci"), (3, 20, "charlie-laptop"), (1, 10, "alice-cli")]):
        db.execute("INSERT INTO api_keys (user_id, org_id, name, token, scopes) VALUES (?,?,?,?,?)",
                   (uid, org, name, f"sk_live_{1000 + i}", "read,write,admin" if uid == 7 else "read"))
    for row in [
        (101, 1, "Alice Archer", "Kickoff notes. Board sync still pending."),
        (101, 2, "Bob Builder", "Beta is 40k over budget, keep this off the status page."),
        (201, 3, "Charlie Chen", "Acquisition memo lives in globex-payroll.csv."),
    ]:
        db.execute("INSERT INTO comments (project_id, author_id, author_name, body) VALUES (?,?,?,?)", row)
    for org, plan, seats, mrr in [(10, "enterprise", 50, 4900000), (20, "pro", 20, 980000), (30, "partner", 10, 0)]:
        db.execute("INSERT INTO subscriptions (org_id, plan, seats, status, renews_at, mrr_cents) VALUES (?,?,?,?,?,?)",
                   (org, plan, seats, "active", "2027-01-01", mrr))
    db.execute("INSERT INTO saved_views (owner_id, name, blob) VALUES (?,?,?)",
               (1, "My open orders", "gASVFAAAAAAAAAB9lIwGZmlsdGVylIwEb3BlbpRzLg=="))

    if os.path.isdir(config.UPLOAD_DIR):
        shutil.rmtree(config.UPLOAD_DIR)
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    seeded_files = [
        (1, 10, "alpha-roadmap.txt", "Alpha roadmap: ship v2 on Friday.\n", 1),
        (3, 20, "globex-payroll.csv", "name,salary\ncharlie,250000\neve,98000\n", 1),
        (2, 10, "team-photo.txt", "(imagine a photo)\n", 0),
    ]
    for owner, org, name, content, private in seeded_files:
        path = os.path.join(config.UPLOAD_DIR, name)
        with open(path, "w") as fh:
            fh.write(content)
        db.execute(
            "INSERT INTO files (owner_id, org_id, filename, stored_path, content_type, size, is_private)"
            " VALUES (?,?,?,?,?,?,?)",
            (owner, org, name, path, "text/plain", len(content), private))

    os.makedirs(config.KEYS_DIR, exist_ok=True)
    with open(os.path.join(config.KEYS_DIR, "primary"), "w") as fh:
        fh.write(config.SECRET)
    with open(os.path.join(config.DATA_DIR, "backup.env"), "w") as fh:
        fh.write("ORBIT_JWT_SECRET=dev-secret-key-change-in-prod\n"
                 "ORBIT_INTERNAL_TOKEN=orbit-internal-svc-token-2f4b\n"
                 "DB_ROOT_PASSWORD=pr0d-db-r00t-9f3a\n"
                 "STRIPE_SECRET_KEY=sk_live_51Mhq0rB1tP9xZ2KdVn7YeQ\n")
