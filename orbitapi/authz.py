"""Core-side authorization policy for project resources.

This is the shared policy the project domain uses. It has to honour several
legitimate exceptions to strict tenant isolation at the same time:

  * a user's role in the resource's organisation (owner > admin > member > viewer),
  * support staff, who service every tenant,
  * explicit per-resource shares with another user or another org,
  * partner organisations, for projects marked `partners` or `public`.

Other domains (notes, tickets, invoices) historically grew their own checks in
their route handlers and do not all route through here.
"""
from typing import Any, Dict, Optional

from . import config, db


def role_rank(role: Optional[str]) -> int:
    try:
        return config.ROLE_ORDER.index(role)
    except (ValueError, TypeError):
        return -1


def membership_role(user_id: int, org_id: int) -> Optional[str]:
    row = db.one("SELECT role FROM memberships WHERE user_id = ? AND org_id = ?", (user_id, org_id))
    return row["role"] if row else None


def _is_partner(viewer_org_id: int, owner_org_id: int) -> bool:
    return db.one(
        "SELECT 1 FROM partnerships WHERE org_id = ? AND partner_org_id = ? AND scope = 'projects:read'",
        (owner_org_id, viewer_org_id),
    ) is not None


def _share(project_id: int, user: Dict[str, Any], need_write: bool = False) -> Optional[str]:
    rows = db.query("SELECT principal_type, principal_id, access FROM project_shares WHERE project_id = ?",
                    (project_id,))
    for r in rows:
        if r["principal_type"] == "user" and r["principal_id"] == user.get("user_id"):
            if not need_write or r["access"] == "write":
                return r["access"]
        if r["principal_type"] == "org" and r["principal_id"] == user.get("org_id"):
            if not need_write or r["access"] == "write":
                return r["access"]
    return None


def can_read_project(project: Dict[str, Any], user: Dict[str, Any]) -> bool:
    vis = project.get("visibility")
    if vis == "public":
        return True
    # Support staff service every tenant.
    if user.get("is_support"):
        return True
    # The owner can always read their own project.
    if project["owner_id"] == user.get("user_id"):
        return True
    # A role in the project's own organisation.
    role = membership_role(user.get("user_id"), project["org_id"])
    if role is not None:
        if vis == "private":
            # Private projects are limited to owners/admins; members need an explicit share.
            if role_rank(role) >= role_rank("admin"):
                return True
        else:
            return True
    # Explicit share with this user or their org.
    if _share(project["id"], user):
        return True
    # Partner organisations may read partner-scoped projects.
    if vis in ("partners", "public") and _is_partner(user.get("org_id"), project["org_id"]):
        return True
    return False


def can_write_project(project: Dict[str, Any], user: Dict[str, Any]) -> bool:
    if project["owner_id"] == user.get("user_id"):
        return True
    role = membership_role(user.get("user_id"), project["org_id"])
    if role_rank(role) >= role_rank("admin"):
        return True
    if _share(project["id"], user, need_write=True) == "write":
        return True
    return False


def load_project(project_id: int) -> Optional[Dict[str, Any]]:
    return db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
