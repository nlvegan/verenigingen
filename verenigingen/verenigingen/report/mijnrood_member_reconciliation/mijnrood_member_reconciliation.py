"""MijnRood ↔ Verenigingen Member Reconciliation.

Compares the membership rosters on both sides and surfaces discrepancies.
Joins on ``Member.member_id`` (str) == ``admin_member.id`` (int).

Classifications:
- OK                 — both sides agree on state
- Status mismatch    — both sides have the member, states disagree
- Only in MijnRood   — MijnRood has a row, we don't
- Only in Verenigingen — we have a member_id, MijnRood doesn't

Active definition (per operator guidance):
- Active = MijnRood status ID ∈ get_active_status_ids() (default: 1 lid, 2 aspirant)
  AND Verenigingen Member.status == 'Active'.
- Suspended (MijnRood geschorst, id=6) maps to our Member.status='Suspended'.
- Applications (admin_membershipapplication) are a separate table on MijnRood
  and intentionally not in this report. Members with status='Pending' or
  'Rejected' on our side are skipped unless a member_id is set.

Fetch is live on each report run — no caching, freshness > speed. Takes a
few seconds via the SSH tunnel for a few thousand rows.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from verenigingen.mijnrood_sync.field_mapping import (
    get_active_status_ids,
    get_status_id_map,
)

# Mapping from MijnRood status ID → expected Verenigingen Member.status value.
# When the actual status differs from the expected one, it's a "Status mismatch".
# Derived from the default id→label table in field_mapping.py.
STATUS_ID_TO_EXPECTED = {
    1: "Active",  # lid
    2: "Active",  # aspirant (also active per is_active config)
    3: "Quit",  # opgezegd
    4: "Banned",  # geroyeerd
    5: "Deceased",  # overleden
    6: "Suspended",  # geschorst
}


def execute(filters: dict | None = None):
    filters = filters or {}
    discrepancy_only = bool(filters.get("discrepancy_only", 1))
    include_terminated = bool(filters.get("include_terminated", 0))

    mijnrood_rows = _fetch_mijnrood_members()
    our_rows = _fetch_our_members()

    rows = _classify(mijnrood_rows, our_rows)

    if not include_terminated:
        rows = [
            r for r in rows if r["our_status"] not in ("Quit", "Banned", "Deceased", "Rejected", "Expired")
        ]

    if discrepancy_only:
        rows = [r for r in rows if r["discrepancy"] != "OK"]

    rows.sort(key=lambda r: (r["discrepancy"] != "OK", r["discrepancy"], r.get("mijnrood_id") or 0))

    columns = _columns()
    summary = _summary(rows)
    chart = _chart(rows)
    return columns, rows, None, chart, summary


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _fetch_mijnrood_members() -> dict[int, dict]:
    """Pull admin_member + admin_membershipstatus via SSH tunnel.

    Returns a dict keyed by mijnrood_id.
    """
    from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

    client = MijnRoodDatabaseClient()
    try:
        with client:
            members = client.fetch_all_rows("admin_member")
            statuses = {s["id"]: s for s in client.fetch_membership_statuses()}
    except Exception as exc:
        frappe.log_error(
            frappe.get_traceback(),
            "MijnRood Member Reconciliation: fetch failed",
        )
        frappe.throw(_("Could not fetch data from MijnRood: {0}").format(exc))

    result: dict[int, dict] = {}
    for m in members:
        mid = m.get("id")
        if mid is None:
            continue
        status_id = m.get("current_membership_status_id")
        status_row = statuses.get(status_id) or {}
        result[int(mid)] = {
            "mijnrood_id": int(mid),
            "first_name": (m.get("first_name") or "").strip(),
            "last_name": (m.get("last_name") or "").strip(),
            "email": (m.get("email") or "").strip().lower(),
            "status_id": status_id,
            "status_name": status_row.get("name") or "",
            "allowed_access": int(status_row.get("allowed_access") or 0),
        }
    return result


def _fetch_our_members() -> dict[int, dict]:
    """Pull Frappe Members that have a member_id set.

    Returns a dict keyed by member_id (as int for join).
    """
    rows = frappe.get_all(
        "Member",
        filters={"member_id": ["!=", ""]},
        fields=["name", "member_id", "first_name", "last_name", "email", "status"],
    )
    result: dict[int, dict] = {}
    for r in rows:
        try:
            mid = int(r["member_id"])
        except (TypeError, ValueError):
            continue
        result[mid] = {
            "mijnrood_id": mid,
            "member_name": r["name"],
            "first_name": (r.get("first_name") or "").strip(),
            "last_name": (r.get("last_name") or "").strip(),
            "email": (r.get("email") or "").strip().lower(),
            "our_status": r.get("status") or "",
        }
    return result


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify(mijnrood: dict[int, dict], ours: dict[int, dict]) -> list[dict[str, Any]]:
    """Produce one row per member (union of keys)."""
    all_ids = set(mijnrood.keys()) | set(ours.keys())
    active_ids = get_active_status_ids()
    status_labels = get_status_id_map()
    out: list[dict[str, Any]] = []

    for mid in all_ids:
        m = mijnrood.get(mid)
        o = ours.get(mid)

        if m and not o:
            out.append(_row_only_mijnrood(m, status_labels))
            continue
        if o and not m:
            out.append(_row_only_ours(o))
            continue

        # Both present — compare states.
        our_status = o["our_status"]
        mr_status_id = m.get("status_id")
        expected = STATUS_ID_TO_EXPECTED.get(mr_status_id)

        mr_is_active = mr_status_id in active_ids
        our_is_active = our_status == "Active"

        if expected and expected == our_status:
            discrepancy = "OK"
        elif mr_is_active and our_is_active:
            # Both active but status IDs don't map exactly (e.g. aspirant vs Active)
            discrepancy = "OK"
        else:
            discrepancy = "Status mismatch"

        name = _compose_name(m.get("first_name"), m.get("last_name")) or _compose_name(
            o.get("first_name"), o.get("last_name")
        )
        email = m.get("email") or o.get("email")
        if m.get("email") and o.get("email") and m["email"] != o["email"]:
            email = f"{m['email']} / {o['email']}"

        out.append(
            {
                "mijnrood_id": mid,
                "member": o["member_name"],
                "name": name,
                "email": email,
                "mijnrood_status": status_labels.get(mr_status_id, str(mr_status_id or "")),
                "mijnrood_allowed_access": "Yes" if m.get("allowed_access") else "No",
                "our_status": our_status,
                "discrepancy": discrepancy,
            }
        )

    return out


def _row_only_mijnrood(m: dict, status_labels: dict) -> dict:
    return {
        "mijnrood_id": m["mijnrood_id"],
        "member": None,
        "name": _compose_name(m.get("first_name"), m.get("last_name")),
        "email": m.get("email"),
        "mijnrood_status": status_labels.get(m.get("status_id"), str(m.get("status_id") or "")),
        "mijnrood_allowed_access": "Yes" if m.get("allowed_access") else "No",
        "our_status": None,
        "discrepancy": "Only in MijnRood",
    }


def _row_only_ours(o: dict) -> dict:
    return {
        "mijnrood_id": o["mijnrood_id"],
        "member": o["member_name"],
        "name": _compose_name(o.get("first_name"), o.get("last_name")),
        "email": o.get("email"),
        "mijnrood_status": None,
        "mijnrood_allowed_access": None,
        "our_status": o["our_status"],
        "discrepancy": "Only in Verenigingen",
    }


def _compose_name(first: str | None, last: str | None) -> str:
    parts = [(first or "").strip(), (last or "").strip()]
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def _columns() -> list[dict]:
    return [
        {"fieldname": "mijnrood_id", "label": _("MijnRood ID"), "fieldtype": "Int", "width": 100},
        {"fieldname": "member", "label": _("Member"), "fieldtype": "Link", "options": "Member", "width": 170},
        {"fieldname": "name", "label": _("Name"), "fieldtype": "Data", "width": 220},
        {"fieldname": "email", "label": _("Email"), "fieldtype": "Data", "width": 260},
        {"fieldname": "mijnrood_status", "label": _("MijnRood Status"), "fieldtype": "Data", "width": 140},
        {
            "fieldname": "mijnrood_allowed_access",
            "label": _("Access"),
            "fieldtype": "Data",
            "width": 70,
        },
        {"fieldname": "our_status", "label": _("Our Status"), "fieldtype": "Data", "width": 110},
        {"fieldname": "discrepancy", "label": _("Discrepancy"), "fieldtype": "Data", "width": 170},
    ]


def _summary(rows: list[dict]) -> list[dict]:
    counts = {
        "OK": 0,
        "Status mismatch": 0,
        "Only in MijnRood": 0,
        "Only in Verenigingen": 0,
    }
    for r in rows:
        counts[r["discrepancy"]] = counts.get(r["discrepancy"], 0) + 1

    return [
        {
            "label": _("Status Mismatch"),
            "value": counts["Status mismatch"],
            "indicator": "Red" if counts["Status mismatch"] else "Green",
            "datatype": "Int",
        },
        {
            "label": _("Only in MijnRood"),
            "value": counts["Only in MijnRood"],
            "indicator": "Orange" if counts["Only in MijnRood"] else "Green",
            "datatype": "Int",
        },
        {
            "label": _("Only in Verenigingen"),
            "value": counts["Only in Verenigingen"],
            "indicator": "Orange" if counts["Only in Verenigingen"] else "Green",
            "datatype": "Int",
        },
        {
            "label": _("OK (hidden unless filter off)"),
            "value": counts["OK"],
            "indicator": "Green",
            "datatype": "Int",
        },
    ]


def _chart(rows: list[dict]) -> dict | None:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["discrepancy"]] = counts.get(r["discrepancy"], 0) + 1
    if not counts:
        return None
    labels = list(counts.keys())
    values = [counts[k] for k in labels]
    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Members"), "values": values}],
        },
        "type": "donut",
        "height": 260,
    }
