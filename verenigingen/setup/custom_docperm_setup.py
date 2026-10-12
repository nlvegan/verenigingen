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
   snapshot of the old JSON, so that revocation needs a patch. Core DocTypes are not covered.

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
    # Staff create Employee records by hand when the automated flow fails (#1606). No delete.
    ("Employee", "Verenigingen Staff", ("read", "write", "create")),
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


def apply_custom_permissions():
    """Entry point for ``after_install`` and ``after_migrate``. Idempotent."""
    _repair_truncated_sets()
    _apply_core_grants()
    _reconcile_own_doctypes()
    _prune_revoked_keys()


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


def _prune_revoked_keys():
    raw = frappe.db.get_global(SNAPSHOT_KEY)
    if not raw:
        return
    checks = _check_fields()
    for doctype, old_rows in frappe.parse_json(raw).items():
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
