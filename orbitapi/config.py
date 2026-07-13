"""Runtime configuration for the OrbitAPI services (gateway + core)."""
import os

SECRET = os.environ.get("ORBIT_JWT_SECRET", "dev-secret-key-change-in-prod")

ACCESS_TOKEN_HOURS = int(os.environ.get("ORBIT_TOKEN_HOURS", str(24 * 30)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ORBIT_DATA_DIR", os.path.join(os.path.dirname(BASE_DIR), "data"))
DB_PATH = os.path.join(DATA_DIR, "orbit.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
KEYS_DIR = os.path.join(DATA_DIR, "keys")

# The gateway proxies authenticated requests to the core service over this URL.
CORE_SERVICE_URL = os.environ.get("ORBIT_CORE_URL", "http://127.0.0.1:9000")

# Public gateway URL (used by the batch helper to re-enter the authenticated API).
GATEWAY_URL = os.environ.get("ORBIT_GATEWAY_URL", "http://127.0.0.1:8000")

# Shared secret the gateway presents to the core service on internal calls.
INTERNAL_SERVICE_TOKEN = os.environ.get("ORBIT_INTERNAL_TOKEN", "orbit-internal-svc-token-2f4b")

# Header names used to carry the resolved caller identity from gateway to core.
H_USER = "x-orbit-user-id"
H_USERNAME = "x-orbit-username"
H_ORG = "x-orbit-org-id"
H_ROLE = "x-orbit-role"
H_SUPPORT = "x-orbit-support"
H_ADMIN = "x-orbit-is-admin"
H_CLEARANCE = "x-orbit-clearance"
H_INTERNAL = "x-orbit-internal"

PAYMENT_WEBHOOK_SECRET = "whsec_orbit_live_9f8e7d6c5b4a"
AWS_ACCESS_KEY_ID = "AKIA3ORBIT7X2QPLM9DZ"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYORBITd9k2a"

TRUSTED_INTERNAL_PREFIXES = ("127.", "10.", "192.168.", "::1", "localhost")

# Role hierarchy inside a tenant (higher index = more privilege).
ROLE_ORDER = ["viewer", "member", "admin", "owner"]

LOGIN_RATE_LIMIT_PER_MINUTE = 5
VERSION = "3.0.0"
