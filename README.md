# OrbitAPI

OrbitAPI is the backend for **Orbit**, a multi-tenant platform for running projects,
billing and a small commerce catalogue across many organisations. It is split into two
services:

- **gateway** — the public API. It authenticates callers, resolves which organisation and
  role a request runs as, and forwards it to the core service.
- **core** — the internal service. It holds the domain logic and database and serves the
  project, billing, commerce, files and reporting APIs behind the gateway.

```
client ──▶ gateway ──(X-Orbit-* identity headers)──▶ core ──▶ SQLite
```

## Tenancy and roles

- A user can belong to **several organisations**, with a different role in each. Roles form a
  hierarchy: `owner` > `admin` > `member` > `viewer`.
- Membership is the authority of record; the active organisation travels with the request and
  can be changed with `POST /api/v2/auth/switch-org/{org_id}`.
- Isolation between tenants is the default, with a few exceptions that the product
  needs:
  - **Support staff** (the Initech Support org) service every tenant.
  - **Shares** — a project can be shared with another user or another organisation.
  - **Partnerships** — partner organisations can read partner-scoped projects.
  - **Public** projects are visible to everyone.

## Running

### Docker (gateway + core)

```bash
docker compose up --build
```

The gateway is published on `http://localhost:8000`; the core service stays on the internal
compose network. The SQLite database lives in the `orbit-data` volume and is seeded with the
sample workspace below on first start.

### Local

```bash
pip install -r requirements.txt
# terminal 1 — core service
uvicorn service:app --port 9000
# terminal 2 — gateway
ORBIT_CORE_URL=http://127.0.0.1:9000 uvicorn gateway:app --port 8000
```

- Gateway: http://localhost:8000 — Swagger UI at `/docs`
- Health: `/health` on each service

## Sample accounts

| Username        | Password      | Home org | Memberships                  |
|-----------------|---------------|----------|------------------------------|
| `alice`         | `alice123`    | 10       | org10 member, org20 viewer   |
| `bob`           | `password`    | 10       | org10 member                 |
| `charlie`       | `Charlie!2024`| 20       | org20 owner                  |
| `diana`         | `billing`     | 10       | org10 admin                  |
| `eve`           | `eve2024`     | 20       | org20 member                 |
| `frank`         | `frank`       | 30       | org30 member (support staff) |
| `grace`         | `Gr@ce-Adm1n` | 10       | org10 owner                  |
| `svc-reporting` | `reporting`   | 10       | org10 member                 |

Organisations: **10** Acme Robotics, **20** Globex Labs, **30** Initech Support (support
provider). Acme and Globex are partners; Alpha (101) is shared with Eve; Orbit Platform (103)
is partner-visible.

```bash
# Authenticate against the gateway
TOKEN=$(curl -s localhost:8000/api/v2/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"bob","password":"password"}' | jq -r .access_token)

curl -s localhost:8000/api/v2/projects/101 -H "Authorization: Bearer $TOKEN"

# Switch active organisation (to one you belong to)
curl -s -X POST localhost:8000/api/v2/auth/switch-org/20 -H "Authorization: Bearer $TOKEN"
```

Tokens are accepted as a `Bearer` header, a `?token=` query parameter or the `orbit_session`
cookie. Organisation API keys may be passed in `X-API-Key`.

## API overview

| Area          | Base path | Service |
|---------------|-----------|---------|
| Auth / session| `/api/v2/auth` | gateway |
| Projects      | `/api/v2/projects`, `/projects/{id}/shares`, `/org/projects` | core |
| Invoices      | `/api/v2/invoices` | core |
| Notes / tickets | `/api/v2/notes`, `/api/v2/tickets` | core |
| Collaboration | `/api/v2/projects/{id}/comments` | core |
| Commerce      | `/api/v2/products`, `/orders`, `/coupons`, `/wallet` | core |
| Billing       | `/api/v2/billing` | core |
| Files         | `/api/v2/files` | core |
| Integrations  | `/api/v2/webhooks`, `/integrations`, `/fx` | core |
| Reports       | `/api/v2/reports` | core |
| API keys      | `/api/v2/api-keys` | core |
| Admin         | `/api/v2/admin` | core |

A `/api/v1` partner surface is retained for backwards compatibility. See the Swagger UI for
the full, current list of routes.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite boots both services and exercises authentication and the project access rules,
including the legitimate cross-tenant cases (shares, partners, support).

## Configuration

| Variable              | Default                          | Purpose                           |
|-----------------------|----------------------------------|-----------------------------------|
| `ORBIT_JWT_SECRET`    | `dev-secret-key-change-in-prod`  | HMAC signing key for JWTs          |
| `ORBIT_CORE_URL`      | `http://127.0.0.1:9000`          | Where the gateway reaches core     |
| `ORBIT_INTERNAL_TOKEN`| `orbit-internal-svc-token-2f4b`  | Gateway→core shared secret         |
| `ORBIT_DATA_DIR`      | `./data`                         | SQLite + upload storage location   |


## License

Released under the [MIT License](LICENSE).
