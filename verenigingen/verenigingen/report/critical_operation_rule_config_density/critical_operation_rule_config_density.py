"""
Critical Operation Rule Config Density
======================================

Discoverability lens over the ~2,600 Critical Operation Rule (COR) rows.

Each row is effectively a security "preset" stamped onto one whitelisted
endpoint. In practice thousands of rows express only a couple hundred distinct
configurations. This report collapses the rows to their distinct config
payloads so an administrator can learn the handful of common profiles instead
of reading a 2,600-row table.

It also surfaces which of the doctype's capability fields carry any live signal
(escalation, business validation, IP/time restrictions) versus which are unused
cognitive load, and flags `required_roles` as decorative (authorization flows
from the security level via ROLE_PROFILE_SECURITY_MAPPING, not this field).
"""

from collections import Counter, defaultdict

import frappe
from frappe import _

# Fields that actually change an endpoint's runtime behavior. Two rows sharing
# this tuple are behaviorally identical presets, regardless of name/description.
BEHAVIOR_FIELDS = [
    "operation_name",
    "operation_type",
    "security_level",
    "rate_limit_calls",
    "rate_limit_period_seconds",
    "rate_limit_scope",
    "batch_rate_limit_calls",
    "batch_rate_limit_period_seconds",
    "apply_batch_limits_to",
    "audit_level",
    "alert_on_execution",
    "enable_business_validation",
    "ip_restrictions",
    "time_restrictions",
    "allow_system_user",
    "bypass_validations",
    "required_roles",
]


def execute(filters=None):
    filters = filters or {}
    rows = _load_rows(filters)
    groups = _group_by_config(rows)
    columns = _get_columns()
    data = _build_rows(groups, total=len(rows))
    return columns, data, None, None, _get_summary(rows)


def _load_rows(filters):
    query_filters = {"enabled": 1}
    if filters.get("operation_type"):
        query_filters["operation_type"] = filters["operation_type"]
    if filters.get("security_level"):
        query_filters["security_level"] = filters["security_level"]
    return frappe.get_all("Critical Operation Rule", filters=query_filters, fields=BEHAVIOR_FIELDS)


def _truthy(value):
    return value not in (None, "", 0, "0")


def _config_signature(row):
    """The behavior tuple, excluding per-endpoint identity (operation_name)."""
    return (
        row.security_level,
        row.rate_limit_calls,
        row.rate_limit_period_seconds,
        row.rate_limit_scope or "per_user",
        row.batch_rate_limit_calls,
        row.batch_rate_limit_period_seconds,
        row.apply_batch_limits_to or "",
        row.audit_level or "",
        1 if row.alert_on_execution else 0,
        1 if row.enable_business_validation else 0,
        1 if (_truthy(row.ip_restrictions) or _truthy(row.time_restrictions)) else 0,
        1 if (row.allow_system_user or _truthy(row.bypass_validations)) else 0,
    )


def _group_by_config(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[_config_signature(row)].append(row)
    # Largest clusters first — the ones worth learning.
    return sorted(groups.items(), key=lambda item: -len(item[1]))


def _rate_limit_label(sig):
    calls, period = sig[1], sig[2]
    if not calls:
        return "—"
    return f"{calls} / {period}s"


def _batch_label(sig):
    calls, period, applies = sig[4], sig[5], sig[6]
    if not calls:
        return "—"
    return f"{calls} / {period}s {applies}".strip()


def _flags_label(sig):
    flags = []
    if sig[9]:
        flags.append("business")
    if sig[10]:
        flags.append("restriction")
    if sig[11]:
        flags.append("escalation")
    return ", ".join(flags)


def _build_rows(groups, total):
    data = []
    cumulative = 0
    for rank, (sig, members) in enumerate(groups, start=1):
        count = len(members)
        cumulative += count
        examples = ", ".join(sorted(m.operation_name for m in members)[:3])
        # A config signature deliberately excludes operation_type (it does not
        # affect runtime enforcement), so a group can span types. Surface which
        # types are present so a reader never assumes a cluster is single-type.
        op_types = ", ".join(sorted({m.operation_type for m in members}))
        data.append(
            {
                "rank": rank,
                "endpoints": count,
                "pct": round(100 * count / total, 1) if total else 0,
                "cumulative_pct": round(100 * cumulative / total, 1) if total else 0,
                "security_level": sig[0],
                "op_types": op_types,
                "rate_limit": _rate_limit_label(sig),
                "scope": sig[3],
                "batch": _batch_label(sig),
                "audit_level": sig[7],
                "alert": _("yes") if sig[8] else "",
                "flags": _flags_label(sig),
                "example_endpoints": examples,
            }
        )
    return data


def _get_summary(rows):
    total = len(rows)
    if not total:
        return []
    distinct = len({_config_signature(r) for r in rows})
    counts = Counter(_config_signature(r) for r in rows)
    top3 = sum(c for _, c in counts.most_common(3))
    escalation = sum(1 for r in rows if r.allow_system_user or _truthy(r.bypass_validations))
    business = sum(1 for r in rows if r.enable_business_validation)
    restriction = sum(1 for r in rows if _truthy(r.ip_restrictions) or _truthy(r.time_restrictions))
    decorative_roles = sum(1 for r in rows if _truthy(r.required_roles))
    return [
        {"label": _("Endpoints"), "value": total, "datatype": "Int"},
        {
            "label": _("Distinct configs"),
            "value": distinct,
            "datatype": "Int",
            "indicator": "Green" if distinct < total / 5 else "Orange",
        },
        {"label": _("Top-3 config coverage"), "value": f"{round(100 * top3 / total)}%", "datatype": "Data"},
        {
            "label": _("Escalation (used)"),
            "value": escalation,
            "datatype": "Int",
            "indicator": "Red" if escalation else "Green",
        },
        {"label": _("Business validation (used)"), "value": business, "datatype": "Int"},
        {"label": _("IP/time restrictions (used)"), "value": restriction, "datatype": "Int"},
        {
            "label": _("required_roles set (decorative)"),
            "value": decorative_roles,
            "datatype": "Int",
            "indicator": "Orange" if decorative_roles else "Green",
        },
    ]


def _get_columns():
    return [
        {"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 60},
        {"label": _("Endpoints"), "fieldname": "endpoints", "fieldtype": "Int", "width": 90},
        {"label": _("%"), "fieldname": "pct", "fieldtype": "Float", "precision": 1, "width": 70},
        {
            "label": _("Cumul %"),
            "fieldname": "cumulative_pct",
            "fieldtype": "Float",
            "precision": 1,
            "width": 80,
        },
        {"label": _("Level"), "fieldname": "security_level", "fieldtype": "Data", "width": 90},
        {"label": _("Op Types"), "fieldname": "op_types", "fieldtype": "Data", "width": 130},
        {"label": _("Rate Limit"), "fieldname": "rate_limit", "fieldtype": "Data", "width": 120},
        {"label": _("Scope"), "fieldname": "scope", "fieldtype": "Data", "width": 90},
        {"label": _("Batch"), "fieldname": "batch", "fieldtype": "Data", "width": 150},
        {"label": _("Audit"), "fieldname": "audit_level", "fieldtype": "Data", "width": 90},
        {"label": _("Alert"), "fieldname": "alert", "fieldtype": "Data", "width": 60},
        {"label": _("Flags"), "fieldname": "flags", "fieldtype": "Data", "width": 140},
        {
            "label": _("Example Endpoints"),
            "fieldname": "example_endpoints",
            "fieldtype": "Data",
            "width": 360,
        },
    ]
