#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Permission Registry Consistency
===============================

`verenigingen/hooks/permissions.py` declares two dicts that together implement
row-level security, and their coverage is **disjoint, not overlapping**:

- ``permission_query_conditions`` — SQL injected into **list** queries.
  ``frappe/model/db_query.py`` calls ``frappe.has_permission`` *without* a doc,
  so a controller hook never runs for list views.
- ``has_permission`` — the **document**-level check. ``frappe.client.get`` calls
  ``doc.check_permission()`` (``frappe/client.py:104``), which never consults the
  query condition.

A doctype registered in only one dict is scoped in only one direction, and
nothing warned about it. Registering *only* the query condition is the dangerous
direction: lists look correctly scoped while ``GET /api/resource/<dt>/<name>`` is
governed by DocPerms alone. That defect has now shipped four times — PR #191
(Project), #256 (Membership), #259 (Employee) and #257 (Team) — which is what
this module exists to stop. See issue #258.

Two traps that are load-bearing for anyone editing those hooks, both verified and
one of them pinned by a test below:

1. **A falsy ``has_permission`` return is a hard DENY, not "no opinion".**
   ``frappe/permissions.py::has_controller_permissions`` does
   ``if not controller_permission: return bool(controller_permission)``. A hook
   whose fallback path returns ``None`` — however its docstring reads — locks out
   every non-admin and makes that doctype's DocPerms unreachable. The generic
   ``frappe-core-permissions`` skill advises "ALWAYS return None by default"; it
   is wrong for this Frappe version.

2. **``permission_type`` never arrives.** ``has_controller_permissions`` calls
   ``frappe.call(method, doc=doc, ptype=ptype, ...)`` and ``frappe.call``'s
   ``get_newargs`` drops kwargs the callee does not declare. Helpers that name
   the parameter ``permission_type`` therefore always see ``None``, while the
   ones naming it ``ptype`` receive the real value. Renaming across the file is
   NOT a safe cleanup — see test_permission_type_kwarg_never_arrives.
"""

import frappe

from verenigingen.hooks.permissions import has_permission as HAS_PERMISSION_REGISTRY
from verenigingen.hooks.permissions import permission_query_conditions as QUERY_REGISTRY
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Doctypes deliberately list-scoped WITHOUT a document-level check.
# Every entry needs a reason, so adding one is a deliberate act rather than a
# silent widening. Child tables are the only justified case: Frappe routes a
# child-table permission check to the parent document
# (frappe/permissions.py::has_child_permission), so the parent's has_permission
# already governs them. test_child_table_exemptions_are_really_child_tables
# verifies that claim against the schema rather than trusting this comment.
DOC_CHECK_EXEMPTIONS = {
    "Chapter Member": "child table of Chapter; governed by has_chapter_permission",
    "Team Member": "child table of Team; governed by has_team_permission",
}

# Doctypes deliberately doc-checked WITHOUT list scoping.
LIST_SCOPE_EXEMPTIONS = {
    "Donation": (
        "read DocPerm is limited to System Manager / Verenigingen Administrator / "
        "Verenigingen Webhook User, so the role layer denies everyone else before a "
        "list query is reached. NOTE: that same fact makes the board-member and "
        "member branches of has_donation_permission dead code -- a controller hook "
        "can only deny, never grant."
    ),
}


class TestPermissionRegistryConsistency(EnhancedTestCase):
    """The two registries must agree, or a doctype is scoped in one direction only."""

    def test_every_list_scoped_doctype_has_a_document_level_check(self):
        """The dangerous direction: scoped lists, unscoped documents.

        This is the assertion that would have caught Membership (#256), Employee
        (#259) and Team (#257) before they shipped.
        """
        missing = set(QUERY_REGISTRY) - set(HAS_PERMISSION_REGISTRY) - set(DOC_CHECK_EXEMPTIONS)

        self.assertFalse(
            missing,
            f"{sorted(missing)} have a permission_query_conditions entry but no has_permission "
            "entry, so their list views are scoped while any single document is readable by "
            "name through DocPerms alone. Register a has_permission handler, or add the "
            "doctype to DOC_CHECK_EXEMPTIONS with a reason.",
        )

    def test_every_doc_checked_doctype_has_list_scoping(self):
        """The other direction is usually harmless, but it should still be deliberate.

        A doc-level check with no query condition means list views fall back to
        DocPerms. That is safe only when the role layer is already narrow enough,
        which is a fact about DocPerms and can change without anyone touching this file.
        """
        missing = set(HAS_PERMISSION_REGISTRY) - set(QUERY_REGISTRY) - set(LIST_SCOPE_EXEMPTIONS)

        self.assertFalse(
            missing,
            f"{sorted(missing)} have a has_permission entry but no permission_query_conditions "
            "entry, so their list views are governed by DocPerms alone. Register a query "
            "condition, or add the doctype to LIST_SCOPE_EXEMPTIONS with a reason.",
        )

    def test_child_table_exemptions_are_really_child_tables(self):
        """Verify the exemption's stated reason against the schema.

        The exemption rests on Frappe delegating a child-table check to the parent
        (has_child_permission). If one of these ever stops being `istable`, the
        delegation stops with it and the exemption becomes a hole.
        """
        for doctype, reason in DOC_CHECK_EXEMPTIONS.items():
            with self.subTest(doctype=doctype):
                self.assertTrue(
                    frappe.db.get_value("DocType", doctype, "istable"),
                    f"{doctype} is exempted as a child table ({reason}) but istable is not set, "
                    "so nothing governs it at document level",
                )

    def test_exemptions_do_not_go_stale(self):
        """An exemption for a doctype in neither registry is a leftover.

        Without this, removing a doctype from the hooks leaves an exemption behind
        that silently pre-authorises the next doctype to reuse the name.
        """
        registered = set(QUERY_REGISTRY) | set(HAS_PERMISSION_REGISTRY)
        stale = (set(DOC_CHECK_EXEMPTIONS) | set(LIST_SCOPE_EXEMPTIONS)) - registered

        self.assertFalse(
            stale, f"{sorted(stale)} are exempted but appear in neither registry; drop the exemption"
        )

    def test_every_registered_handler_resolves(self):
        """A dotted path that no longer resolves fails at permission-check time.

        Renaming or moving a handler without updating the registry produces an
        AttributeError inside a permission check -- which, depending on the caller,
        surfaces as a 500 or as a denial.
        """
        for label, registry in (("query", QUERY_REGISTRY), ("has_permission", HAS_PERMISSION_REGISTRY)):
            for doctype, dotted_path in registry.items():
                with self.subTest(registry=label, doctype=doctype):
                    try:
                        handler = frappe.get_attr(dotted_path)
                    except Exception as exc:
                        self.fail(f"{label} handler for {doctype} does not resolve: {dotted_path} ({exc})")
                    self.assertTrue(callable(handler), f"{dotted_path} is not callable")

    def test_permission_type_kwarg_never_arrives(self):
        """Pin the ptype trap so a rename cannot silently change webhook answers.

        has_controller_permissions calls frappe.call(method, doc=doc, ptype=ptype, ...)
        and frappe.call's get_newargs drops kwargs the callee does not declare. Every
        helper naming the parameter `permission_type` therefore receives None, and
        `_check_service_account_permission` does `perm_type = permission_type or "read"`
        -- so a service-account check is ALWAYS evaluated as read.

        Renaming those parameters to `ptype` would start feeding real ptypes into that
        branch and silently change webhook answers for write/create/submit. If someone
        does it deliberately, this test fails and they have to say so here.
        """
        from verenigingen.permissions import has_donor_permission, has_employee_permission

        supplied = {"doc": None, "user": "Administrator", "ptype": "write"}

        # Names it `permission_type` -> ptype is dropped, the helper sees nothing.
        self.assertNotIn(
            "ptype",
            frappe.get_newargs(has_donor_permission, supplied),
            "has_donor_permission names the parameter `permission_type`, so frappe cannot "
            "pass ptype to it. If this now passes, the signature changed and every "
            "_check_service_account_permission caller stopped being evaluated as read.",
        )

        # Names it `ptype` -> the real value arrives.
        self.assertIn(
            "ptype",
            frappe.get_newargs(has_employee_permission, supplied),
            "has_employee_permission is declared with `ptype` and should receive it",
        )
