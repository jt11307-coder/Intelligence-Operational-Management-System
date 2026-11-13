"""Role permissions. The administrator set is explicit so new actions are not inherited by accident."""

from __future__ import annotations

from wpd_compstat.constants import ROLES

_ALL = {
    "dashboard",
    "search",
    "view_narratives",
    "view_sensitive",
    "view_source_pdf",
    "import_pdf",
    "classify",
    "resolve_exceptions",
    "analyze",
    "traffic_import",
    "briefing",
    "reports",
    "export",
    "presentation",
    "assignments_propose",
    "assignments_update",
    "assignments_approve",
    "assignments_assess",
    "backup",
    "restore",
    "data_quality",
    "configure",
    "manage_users",
    "delete_records",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "administrator": frozenset(_ALL),
    "crime_analyst": frozenset(
        {
            "dashboard",
            "search",
            "view_narratives",
            "view_sensitive",
            "view_source_pdf",
            "import_pdf",
            "classify",
            "resolve_exceptions",
            "analyze",
            "traffic_import",
            "briefing",
            "reports",
            "export",
            "presentation",
            "assignments_propose",
            "assignments_update",
            "backup",
            "data_quality",
        }
    ),
    "command_staff": frozenset(
        {
            "dashboard",
            "search",
            "view_narratives",
            "view_source_pdf",
            "analyze",
            "briefing",
            "reports",
            "export",
            "presentation",
            "assignments_approve",
            "assignments_update",
            "assignments_assess",
        }
    ),
    "supervisor": frozenset(
        {
            "dashboard",
            "search",
            "view_narratives",
            "view_source_pdf",
            "briefing",
            "assignments_update",
        }
    ),
    "read_only": frozenset({"dashboard", "search"}),
}


def has_permission(role: str, permission: str) -> bool:
    if role not in ROLES:
        return False
    return permission in ROLE_PERMISSIONS[role]
