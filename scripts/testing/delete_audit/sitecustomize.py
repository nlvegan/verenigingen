"""Record every delete that REPORTED SUCCESS, so a second process can ask the site
which of them are still there.

The question this exists to answer is not "did cleanup report success" -- that is the
instrument that has lied three times in this repo (`cleanup_status == "skipped"`, a
zero-length error list, a global orphan join). It is "is the row gone", asked of the
database, after everything the run was going to do has been done.

Deliberately split in two: this half only APPENDS to a JSONL during the run. The
survivor check runs in a separate process afterwards, which (a) has no connection
lifetime problem at interpreter exit, and (b) sees only COMMITTED state -- which is
exactly the contamination question. A row transiently resurrected and then rolled back
at class end never mattered; one that outlives the run did.

Installation is deferred to the first test, on purpose: at `sitecustomize` time frappe
is not importable yet, and `frappe.db` is a `LocalProxy` whose class has no `delete`
until a connection exists. Only `unittest` is safe to touch this early.

Activated by being on PYTHONPATH; writes to $DELETE_AUDIT_LOG.
"""

import json
import os
import sys
import unittest

_LOG = os.environ.get("DELETE_AUDIT_LOG")
_STATE = {"test": "<no test>", "installed": False, "handle": None}


def _record(kind, doctype, name, creation=None):
    if not doctype or not name:
        return
    _STATE["handle"].write(
        json.dumps(
            {
                "kind": kind,
                "doctype": str(doctype),
                "name": str(name),
                "creation": str(creation) if creation else None,
                "test": _STATE["test"],
            }
        )
        + "\n"
    )


def _creation_of(doctype, name):
    """The row's `creation`, read BEFORE the delete.

    A docname is not an identity. Several fixtures here are get-or-create on a FIXED
    name (`Test Amsterdam Chapter`), so a later test recreating one looks exactly like
    a resurrection if you only remember the name -- the auditor's own false-positive
    mode, and the first thing the census turned up. `creation` distinguishes them: a
    resurrected row is the SAME row, a recreated one is a new row wearing the name.
    """
    import frappe

    try:
        return frappe.db.get_value(doctype, name, "creation")
    except Exception:
        return None


def _install_frappe_hooks():
    import frappe
    import frappe.model.delete_doc as ddoc
    from frappe.database.database import Database

    real_delete_doc = ddoc.delete_doc

    def audited_delete_doc(doctype=None, name=None, *a, **kw):
        names_before = name if isinstance(name, (list, tuple)) else [name]
        creations = {one: _creation_of(doctype, one) for one in names_before}
        result = real_delete_doc(doctype, name, *a, **kw)
        # `delete_doc` returns False when the row was already gone and ignore_missing
        # is on. That is not a delete, and recording it would make every cleanup that
        # walks past a missing row look like a resurrection.
        if result is not False:
            names = name if isinstance(name, (list, tuple)) else [name]
            for one in names:
                _record("delete_doc", doctype, one, creations.get(one))
        return result

    ddoc.delete_doc = audited_delete_doc
    frappe.delete_doc = audited_delete_doc

    real_db_delete = Database.delete

    def audited_db_delete(self, doctype, filters=None, **kw):
        # A filter dict is not a docname. Record only the unambiguous shapes; a
        # filtered bulk delete is out of scope, and saying so beats guessing.
        target = None
        if isinstance(filters, str):
            target = filters
        elif (
            isinstance(filters, dict)
            and set(filters) == {"name"}
            and isinstance(filters["name"], str)
        ):
            target = filters["name"]
        creation = _creation_of(doctype, target) if target else None
        out = real_db_delete(self, doctype, filters, **kw)
        if target:
            _record("db.delete", doctype, target, creation)
        return out

    Database.delete = audited_db_delete


_real_run = unittest.TestCase.run


def _audited_run(self, *a, **kw):
    if not _STATE["installed"]:
        _STATE["installed"] = True
        _STATE["handle"] = open(_LOG, "a", buffering=1)
        try:
            _install_frappe_hooks()
        except Exception as exc:  # pragma: no cover
            print(f"DELETE-AUDIT PROBE FAILED TO INSTALL: {exc}", file=sys.stderr)
    previous = _STATE["test"]
    _STATE["test"] = f"{type(self).__module__}.{type(self).__name__}.{self._testMethodName}"
    try:
        return _real_run(self, *a, **kw)
    finally:
        _STATE["test"] = previous


if _LOG:
    unittest.TestCase.run = _audited_run
