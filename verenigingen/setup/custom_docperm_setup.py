"""Custom DocPerm handling on install and migrate (#1621, #1622).

Frappe's rule (``frappe/model/meta.py::set_custom_permissions``): once a DocType has ANY
``Custom DocPerm`` row, ONLY those rows apply and its stock ``DocPerm`` rows (the JSON
``permissions`` array) are ignored. ``frappe.permissions.add_permission`` copies the stock
rows into Custom DocPerm before adding one; a raw insert, which is what fixture import
does, does not. Three things follow, handled here in this order by
:func:`apply_custom_permissions` (hooked on ``after_install`` and ``after_migrate``):

1. ``_repair_truncated_sets``: core DocTypes that the retired ``custom_docperm.json``
   fixture left with only our rows (and the HRMS Employee Self Service row).
2. ``_apply_core_grants``: our grants on core DocTypes, via the framework API so the
   stock rows are copied first. ADDITIVE: a flag is raised, never lowered, and nothing is
   removed, because we do not own these DocTypes.
3. ``_reconcile_own_doctypes``: our OWN DocTypes that have Custom DocPerm rows (HRMS's
   Employee Self Service User Type creates them for Link targets, ``public_document_creator``
   creates them for Member/Donor/Donation). There the JSON is authoritative for the
   (role, permlevel, if_owner) combinations it declares. Rows the JSON does not declare
   are kept.

4. ``_prune_revoked_keys`` (#1629): a (role, permlevel, if_owner) the JSON used to declare
   and no longer does. Undeclared rows are otherwise indistinguishable from an admin's
   deliberate addition or the User Type / public-creator rows we must keep, so the OLD
   declaration is recorded by :func:`snapshot_own_declared_permissions` (``before_migrate``,
   before ``sync_all`` replaces the stock rows) and a frozen row is deleted only when its
   key was dropped AND its flags still equal what the old JSON declared. A row someone edited
   since is theirs and stays. Without a snapshot (``after_install``, or a migrate that skipped
   the hook) nothing is pruned. Known limits, all failing toward KEEPING a grant:
   a duplicate Custom row for the revoked key whose flags differ survives (Frappe ORs it);
   a Check field added to DocPerm in the same migrate makes every flag comparison miss;
   stock rows rewritten outside migrate (``reload-doctype``, a developer_mode save) leave no
   snapshot of the old JSON, so that revocation needs a patch.
5. ``_revoke_dropped_core_grants`` (#1642): the same problem for ``CORE_GRANTS``, which lives in
   Python, so a ``before_migrate`` snapshot would already see the NEW tuple. Instead
   :func:`_apply_core_grants` records, at the end of every run, what it granted
   (:data:`CORE_LEDGER_KEY`); the next run revokes whatever the ledger holds and
   ``CORE_GRANTS`` no longer declares. What we granted is the declared ptypes that the core
   DocType's STOCK row for that role does not already carry: a flag stock grants is not ours to
   lower, a flag nobody declared (an admin's, HRMS's, an ESS ``select``) is never in the ledger,
   and a row we created is deleted only when it is then empty. History before the ledger
   existed is unknowable and is not revoked; the ledger is seeded from the current
   declaration on the first run, so every later removal does revoke. Residual ambiguity: an
   admin who raised a flag we ALSO declare is indistinguishable from us having raised it.

No commit here: both hooks run inside migrate / install-app, which commit themselves.
"""

import frappe
from frappe.core.doctype.custom_docperm.custom_docperm import update_custom_docperm
from frappe.permissions import add_permission, setup_custom_perms
from frappe.utils import cint

APP = "verenigingen"
# tabDefaultValue key for the before_migrate snapshot; set_global commits with the atomic
# pre_schema_updates phase, so it survives a migrate that dies before after_migrate.
SNAPSHOT_KEY = "verenigingen_own_docperm_snapshot"
# tabDefaultValue key for the ledger of core grants: {doctype: {role: [ptype, ...]}}. Written at
# the end of each apply, so it holds the PREVIOUS declaration when the next apply starts.
CORE_LEDGER_KEY = "verenigingen_core_grants_ledger"

# (doctype, role, ptypes granted). All at permlevel 0, not if_owner. Lifted verbatim from the
# retired fixtures/custom_docperm.json, minus its DocType row (meta.py skips custom perms for
# DocType itself, so that row never had any effect).
CORE_GRANTS = (
    ("Mode of Payment", "Verenigingen Webhook User", ("read",)),
    ("Company", "Verenigingen Webhook User", ("read",)),
    ("Account", "Verenigingen Webhook User", ("read",)),
    ("Address", "All", ("read", "write", "create", "report", "export", "share", "print", "email")),
    (
        "Address",
        "System Manager",
        ("read", "write", "create", "delete", "report", "export", "import", "share", "print", "email"),
    ),
    ("Address", "Accounts User", ("read", "write", "create", "report", "export", "share", "print", "email")),
    ("Address", "Sales User", ("read", "write", "create", "report", "export", "share", "print", "email")),
    ("Address", "Purchase User", ("read", "write", "create", "report", "export", "share", "print", "email")),
    (
        "Address",
        "Maintenance User",
        ("read", "write", "create", "report", "export", "share", "print", "email"),
    ),
    ("Address", "Verenigingen Webhook User", ("read", "write", "create")),
    ("Address", "Verenigingen Chapter Board Member", ("read", "write", "export")),
    ("Customer", "Verenigingen Webhook User", ("read", "write", "create")),
    # Item read for the Verenigingen Administrator profile (#1774); the row also carries `export`,
    # the framework default add_permission gives every new row. Its only invoicing role is
    # Accounts Manager, which can create a Sales Invoice but cannot read Item (stock Item read
    # goes to Accounts USER), and ERPNext checks Item read against the session user, so the
    # invoice created at approval failed for that approver.
    ("Item", "Verenigingen Administrator", ("read",)),
    ("Contact", "Sales User", ("read", "write", "create", "report", "export", "share", "print", "email")),
    ("Contact", "Accounts User", ("read", "write", "create", "report", "export", "share", "print", "email")),
    ("Contact", "Purchase User", ("read", "write", "create", "report", "export", "share", "print", "email")),
    (
        "Contact",
        "System Manager",
        ("read", "write", "create", "delete", "report", "export", "import", "share", "print", "email"),
    ),
    ("Contact", "Verenigingen Webhook User", ("read", "write", "create")),
    (
        "Customer",
        "Verenigingen Staff",
        ("read", "write", "create", "report", "export", "share", "print", "email"),
    ),
    (
        "Address",
        "Verenigingen Staff",
        ("read", "write", "create", "report", "export", "share", "print", "email"),
    ),
    ("Employee", "Employee", ("read", "report", "print", "email")),
    (
        "Employee",
        "HR User",
        ("read", "write", "create", "delete", "report", "export", "import", "share", "print", "email"),
    ),
    (
        "Employee",
        "HR Manager",
        ("read", "write", "create", "delete", "report", "export", "import", "share", "print", "email"),
    ),
    ("Employee", "Verenigingen Chapter Board Member", ("read", "report", "export", "print", "email")),
    ("Contact", "Verenigingen Chapter Board Member", ("read", "write", "export", "print", "email")),
    (
        "Contact",
        "Verenigingen Staff",
        ("read", "write", "create", "report", "export", "share", "print", "email"),
    ),
    (
        "Bank Transaction",
        "Accounts Manager",
        (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
        ),
    ),
    (
        "Bank Transaction",
        "Accounts User",
        ("read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"),
    ),
    (
        "Bank Transaction",
        "System Manager",
        (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
        ),
    ),
    ("Bank Transaction", "Verenigingen Webhook User", ("read", "write", "create", "submit")),
    (
        "Journal Entry",
        "Accounts Manager",
        (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "amend",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
        ),
    ),
    (
        "Journal Entry",
        "Accounts User",
        ("read", "write", "create", "submit", "amend", "report", "export", "share", "print", "email"),
    ),
    ("Journal Entry", "Auditor", ("read", "report", "export", "print", "email")),
    (
        "Journal Entry",
        "System Manager",
        (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "amend",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
        ),
    ),
    ("Journal Entry", "Verenigingen Webhook User", ("read", "write", "create", "submit")),
    (
        "Payment Entry",
        "Accounts User",
        (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "amend",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
        ),
    ),
    (
        "Payment Entry",
        "Accounts Manager",
        (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "amend",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
        ),
    ),
    ("Payment Entry", "Verenigingen Webhook User", ("read", "write", "create", "submit")),
)

_ROW_META = ("name", "doctype", "creation", "modified", "modified_by", "owner", "docstatus")


# Script reports that read EVERY Expense Claim with no permission filter and are open to Expense
# Approver. Approvers are scoped to their chapters by has_expense_claim_permission /
# get_expense_claim_permission_query, which a raw frappe.qb report never consults (#1606), so the
# role is taken off the report. HR Manager (Treasurer) and System Manager keep it.
REPORT_ROLE_REMOVALS = {"Unpaid Expense Claim": ("Expense Approver",)}
REPORT_ROLE_ADDITIONS = {"Unpaid Expense Claim": ("System Manager",)}


def apply_custom_permissions():
    """Entry point for ``after_install`` and ``after_migrate``. Idempotent."""
    _repair_truncated_sets()
    _apply_core_grants()
    _reconcile_own_doctypes()
    _prune_revoked_keys()
    _restrict_report_roles()


def _restrict_report_roles():
    """Custom Role on a Report REPLACES its stock roles, so start from whatever applies now."""
    for report, removed in REPORT_ROLE_REMOVALS.items():
        if not frappe.db.exists("Report", report):
            continue
        name = frappe.db.get_value("Custom Role", {"report": report}, "name")
        doc = frappe.get_doc("Custom Role", name) if name else frappe.new_doc("Custom Role")
        current = [r.role for r in doc.roles] if name else _stock_report_roles(report)
        wanted = [r for r in current if r not in removed]
        wanted += [r for r in REPORT_ROLE_ADDITIONS.get(report, ()) if r not in wanted]
        if name and wanted == current:
            continue
        doc.report = report
        doc.set("roles", [{"role": r} for r in wanted])
        # Security: install/migrate hook; no session user to hold Custom Role permission.
        doc.save(ignore_permissions=True)


def _stock_report_roles(report):
    return frappe.get_all("Has Role", filters={"parenttype": "Report", "parent": report}, pluck="role")


def snapshot_own_declared_permissions():
    """``before_migrate``: record what the JSON declares for each frozen own DocType.

    A pending snapshot is kept, not overwritten: if the previous migrate died after
    ``sync_all``, the stock rows already show the NEW JSON and only the pending snapshot
    still knows the old one.
    """
    if frappe.db.get_global(SNAPSHOT_KEY):
        return
    checks = _check_fields()
    snapshot = {
        doctype: [[*_key(row), _granted_flags(row, checks)] for row in _stock_rows(doctype)]
        for doctype in _own_doctypes_with_custom_perms()
    }
    frappe.db.set_global(SNAPSHOT_KEY, frappe.as_json(snapshot, indent=None))


def _declared_roles(doctype):
    return {role for dt, role, _ptypes in CORE_GRANTS if dt == doctype}


def _stock_rows(doctype):
    return frappe.get_all("DocPerm", fields="*", filters={"parent": doctype})


def _custom_rows(doctype):
    return frappe.get_all("Custom DocPerm", fields="*", filters={"parent": doctype})


def _key(row):
    return (row.role, cint(row.permlevel), cint(row.if_owner))


def _insert_custom_copy(stock_row):
    values = {k: v for k, v in stock_row.items() if k not in _ROW_META}
    frappe.get_doc({**values, "doctype": "Custom DocPerm"}).insert(ignore_permissions=True)


def _repair_truncated_sets():
    """Give back the stock rows the retired fixture hid, ONLY where the set looks truncated.

    "Truncated" = every role in the Custom DocPerm set is one we declare for that DocType or
    the role of a User Type (the HRMS Employee Self Service row is added through
    ``add_permission`` onto an already-frozen set). Any other role means somebody curated the
    set, and we leave it alone.
    """
    user_type_roles = set(frappe.get_all("User Type", pluck="role"))
    for doctype in sorted({dt for dt, _r, _p in CORE_GRANTS}):
        custom = _custom_rows(doctype)
        if not custom:
            continue  # nothing hides the stock rows; _apply_core_grants copies them first
        if not {r.role for r in custom} <= _declared_roles(doctype) | user_type_roles:
            continue
        present = {_key(r) for r in custom}
        for stock in _stock_rows(doctype):
            if _key(stock) not in present:
                _insert_custom_copy(stock)
        frappe.clear_cache(doctype=doctype)


def _ensure_grant_role(role):
    # after_install runs BEFORE the role fixtures are synced (installer.install_app), so the
    # role may not exist yet; the fixture import later overwrites these defaults.
    if not frappe.db.exists("Role", role):
        frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _apply_core_grants():
    ledger = _load_core_ledger()
    _revoke_dropped_core_grants(ledger)
    for doctype, role, ptypes in CORE_GRANTS:
        _ensure_grant_role(role)
        setup_custom_perms(doctype)  # copies the stock rows first, only if no Custom DocPerm yet
        where = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
        if not frappe.db.exists("Custom DocPerm", where):
            add_permission(doctype, role, 0, ptypes[0])
        # Duplicate rows for one (role, permlevel) exist in the wild (a stock copy plus a
        # fixture-era row) and Frappe ORs them, so a grant is met when ANY row carries the flag.
        rows = frappe.get_all("Custom DocPerm", filters=where, fields=["name", *ptypes])
        missing = {p: 1 for p in ptypes if not any(cint(r[p]) for r in rows)}
        if missing:
            update_custom_docperm(rows[0].name, missing)
        frappe.clear_cache(doctype=doctype)
        _record_core_grant(ledger, doctype, role, ptypes)
    frappe.db.set_global(CORE_LEDGER_KEY, frappe.as_json(ledger, indent=None))


def _load_core_ledger():
    """The recorded ledger, or ``{}`` when it is unreadable: then nothing is revoked and the
    apply loop re-seeds it, rather than a bad value aborting every migrate."""
    raw = frappe.db.get_global(CORE_LEDGER_KEY)
    if not raw:
        return {}
    try:
        ledger = frappe.parse_json(raw)
        valid = isinstance(ledger, dict) and all(
            isinstance(roles, dict)
            and all(
                isinstance(entry, dict)
                and isinstance(entry.get("ptypes"), list)
                and isinstance(entry.get("defaults"), list)
                for entry in roles.values()
            )
            for roles in ledger.values()
        )
    except ValueError:
        valid = False
    if not valid:
        frappe.log_error(
            title="Core grants ledger unreadable, nothing revoked and it was re-seeded",
            message=f"{CORE_LEDGER_KEY}: {str(raw)[:500]}",
        )
        return {}
    return ledger


def _stock_granted(doctype, role, ptype):
    return any(cint(r.get(ptype)) for r in _stock_rows(doctype) if _key(r) == (role, 0, 0))


def _creation_defaults():
    """Check fields Frappe turns on in a new Custom DocPerm row (read, export)."""
    return [
        df.fieldname
        for df in frappe.get_meta("Custom DocPerm").fields
        if df.fieldtype == "Check" and cint(df.default)
    ]


def _has_stock_row(doctype, role):
    return any(_key(r) == (role, 0, 0) for r in _stock_rows(doctype))


def _record_core_grant(ledger, doctype, role, ptypes):
    """Remember what this run declared. Stock is consulted when revoking, not here.

    A row with no stock counterpart was created by ``add_permission``, whose creation defaults
    (read, export) are ours too, but only while undeclared: they go with the row, not with the
    tuple, so they are kept apart from the declared ptypes.
    """
    defaults = []
    if not _has_stock_row(doctype, role):
        defaults = [f for f in _creation_defaults() if f not in ptypes]
    ledger.setdefault(doctype, {})[role] = {"ptypes": list(ptypes), "defaults": defaults}


def _revoke_dropped_core_grants(ledger):
    """Take back what a previous ``CORE_GRANTS`` granted and the current one does not (#1642).

    Only the dropped flags, only on the (role, permlevel 0, not if_owner) row we wrote to, and
    never a flag the stock row grants. Flags nobody here declared are untouched, so an admin's
    extra flag on the same row survives. A row with no stock counterpart is ours outright and is
    deleted once it carries no flag at all.
    """
    declared = {(dt, role): set(ptypes) for dt, role, ptypes in CORE_GRANTS}
    for doctype in list(ledger):
        for role, recorded in list(ledger[doctype].items()):
            kept = declared.get((doctype, role))
            # read stays while the tuple does: write without read lets a user edit a document
            # they cannot open.
            dropped = [p for p in recorded["ptypes"] if kept is None or (p not in kept and p != "read")]
            if kept is None:
                dropped += recorded["defaults"]
            if dropped:
                _lower_core_flags(doctype, role, dropped)
        del ledger[doctype]  # re-recorded by the apply loop for everything still declared


def _lower_core_flags(doctype, role, flags):
    lower = [p for p in flags if not _stock_granted(doctype, role, p)]
    ours_outright = not _has_stock_row(doctype, role)
    checks = [f for f in _check_fields() if f != "if_owner"]
    for row in _custom_rows(doctype):
        if _key(row) != (role, 0, 0):
            continue
        changed = {p: 0 for p in lower if cint(row.get(p))}
        if changed:
            update_custom_docperm(row.name, changed)
        if ours_outright and not any(cint(row.get(f)) for f in checks if f not in changed):
            frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True)
    frappe.clear_cache(doctype=doctype)


def _own_doctypes_with_custom_perms():
    modules = frappe.get_all("Module Def", filters={"app_name": APP}, pluck="name")
    if not modules:
        return []
    own = frappe.get_all(
        "DocType", filters={"module": ["in", modules], "custom": 0, "istable": 0}, pluck="name"
    )
    frozen = set(frappe.get_all("Custom DocPerm", pluck="parent", distinct=True))
    return sorted(frozen & set(own))


def _check_fields():
    return [df.fieldname for df in frappe.get_meta("Custom DocPerm").fields if df.fieldtype == "Check"]


def _reconcile_own_doctypes():
    checks = _check_fields()
    for doctype in _own_doctypes_with_custom_perms():
        by_key = {}
        for row in _custom_rows(doctype):
            by_key.setdefault(_key(row), []).append(row)
        for declared in _stock_rows(doctype):
            existing = by_key.get(_key(declared))
            if not existing:
                _insert_custom_copy(declared)
                continue
            for row in existing:
                changed = {
                    f: cint(declared.get(f)) for f in checks if cint(row.get(f)) != cint(declared.get(f))
                }
                if changed:
                    update_custom_docperm(row.name, changed)
        frappe.clear_cache(doctype=doctype)


def _granted_flags(row, checks):
    return sorted(f for f in checks if cint(row.get(f)))


def _load_own_snapshot():
    """The recorded snapshot, ``None`` when there is none, ``{}`` when it is unreadable
    (reported; the caller then prunes nothing and clears it, so a bad value cannot abort every
    migrate)."""
    raw = frappe.db.get_global(SNAPSHOT_KEY)
    if not raw:
        return None
    try:
        snapshot = frappe.parse_json(raw)
        valid = isinstance(snapshot, dict) and all(
            isinstance(rows, list)
            and all(
                isinstance(r, list) and len(r) == 4 and isinstance(r[0], str) and isinstance(r[3], list)
                for r in rows
            )
            for rows in snapshot.values()
        )
    except ValueError:
        valid = False
    if not valid:
        frappe.log_error(
            title="Own DocType permission snapshot unreadable, nothing pruned (a revocation may have been missed this migrate)",
            message=f"{SNAPSHOT_KEY}: {str(raw)[:500]}",
        )
        return {}
    return snapshot


def _prune_revoked_keys():
    snapshot = _load_own_snapshot()
    if snapshot is None:
        return
    checks = _check_fields()
    for doctype, old_rows in snapshot.items():
        declared_now = {_key(row) for row in _stock_rows(doctype)}
        revoked = {
            (role, permlevel, if_owner): flags
            for role, permlevel, if_owner, flags in old_rows
            if (role, permlevel, if_owner) not in declared_now
        }
        for row in _custom_rows(doctype):
            if revoked.get(_key(row)) == _granted_flags(row, checks):
                frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True)
        frappe.clear_cache(doctype=doctype)
    frappe.defaults.clear_default(key=SNAPSHOT_KEY, parent="__global")
