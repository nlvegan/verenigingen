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
governed by DocPerms alone. See issue #258.

What this module actually covers
--------------------------------

**Registry AGREEMENT — that the two key sets line up.** Two doctypes shipped with
that gap: ``Employee`` (#259) and ``Team`` (#257, PR #265).

**It does NOT cover handler CORRECTNESS**, and that distinction matters, because
the other two incidents in this defect family were not registry gaps at all —
both doctypes were registered in *both* dicts the whole time, and the bug was in
the handler body:

- **#191 (Project)** — ``get_project_permission_query_conditions`` returned ``""``
  for a role that should have been scoped, and ``""`` means UNRESTRICTED, not
  "no access".
- **#256 (Membership)** — ``has_membership_permission`` returned ``None`` (a hard
  DENY, see trap 1) and was then briefly "fixed" to ``return True``, a blanket
  grant on every Membership by name.

A green run here says the key sets agree. It does not say any handler is right.

Nor does it cover: doctypes in **neither** registry that arguably need both;
``has_website_permission`` (a third mechanism — frappe registers Address, erpnext
registers Project and others, and portal routes use it rather than either dict);
Server Script "Permission Query" rows (``db_query.py``); or ``frappe.get_all`` and
raw SQL, which bypass both registries by design.

Two traps that are load-bearing for anyone editing those hooks
--------------------------------------------------------------

1. **A falsy ``has_permission`` return is a hard DENY, not "no opinion".**
   ``frappe/permissions.py::has_controller_permissions`` does
   ``if not controller_permission: return bool(controller_permission)``. A hook
   whose fallback path returns ``None`` — however its docstring reads — locks out
   every non-admin and makes that doctype's DocPerms unreachable. The generic
   ``frappe-core-permissions`` skill advises "ALWAYS return None by default"; it
   is wrong for this Frappe version. This is what #256 did.

2. **``permission_type`` never arrives.** Pinned by
   test_permission_type_kwarg_partition_is_unchanged below.

Handler resolvability (every dotted path imports and is callable) is already
asserted by ``verenigingen/tests/test_hooks_modules.py::TestPermissionHandlerResolution``
and is deliberately not repeated here.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

# Doctypes deliberately list-scoped WITHOUT a document-level check.
# Every entry needs a reason, so adding one is a deliberate act rather than a
# silent widening. Child tables are the only justified case: Frappe routes a
# child-table DOCUMENT check to the parent (frappe/permissions.py:120-129 ->
# has_child_permission), so the parent's has_permission governs reads by name.
# (The list direction is separate: frappe.client.get_list with a parent passes no
# child doc, so the parent hook does not run there -- which is exactly why these
# two keep their own query conditions.)
# test_child_table_exemptions_are_really_child_tables verifies the claim against
# the schema rather than trusting this comment.
DOC_CHECK_EXEMPTIONS = {
    "Chapter Member": "child table of Chapter; document reads governed by has_chapter_permission",
    "Team Member": "child table of Team; document reads governed by has_team_permission",
}

# Doctypes deliberately doc-checked WITHOUT list scoping.
LIST_SCOPE_EXEMPTIONS = {
    "Donation": (
        "read DocPerm is limited to the three roles in DONATION_READ_ROLES, so the role "
        "layer denies everyone else before a list query is reached. NOTE: a fully "
        "implemented get_donation_permission_query exists at permissions.py:841 and is "
        "NOT registered -- and it cannot simply be registered, because "
        "`Verenigingen Webhook User` is not in Roles.ADMIN_ROLES and matches none of its "
        "branches, so it would fall through to `1=0` and the webhook account would stop "
        "seeing donations in list queries. That same role layer is also why the "
        "board-member and member branches of has_donation_permission are dead code: a "
        "controller hook can only deny, never grant."
    ),
}

# The premise the Donation exemption rests on. Asserted, not trusted: DocPerms are
# editable from the Role Permission Manager with no code change, and the moment a
# fourth role gains read, the exemption is wrong and Donation needs its query.
DONATION_READ_ROLES = {
    "System Manager",
    "Verenigingen Administrator",
    "Verenigingen Webhook User",
}

# Handlers that declare the parameter as `ptype` and therefore RECEIVE the real
# permission type. Everything else in the registry declares `permission_type` and
# always sees None. See test_permission_type_kwarg_partition_is_unchanged.
PTYPE_AWARE_HANDLERS = {
    "Employee",
    "Team",
    "Chapter",
    "Project",
    "Event Contact Campaign",
}


def _app_hooks(hook_name):
    """The MERGED hook map frappe actually consults, narrowed to this app's handlers.

    Reading the module dicts directly would be subtly wrong in three ways:
    a future entry added in hooks/__init__.py rather than hooks/permissions.py would
    leave the test asserting on a stale object; a doctype scoped by ANOTHER app would
    be reported as this app's gap; and the "*" bucket would be invisible.
    """
    merged = frappe.get_hooks(hook_name) or {}
    return {
        doctype: [p for p in paths if p.startswith("verenigingen.")]
        for doctype, paths in merged.items()
        if any(p.startswith("verenigingen.") for p in paths)
    }


class TestPermissionRegistryConsistency(FrappeTestCase):
    """The two registries must agree, or a doctype is scoped in one direction only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.query_registry = _app_hooks("permission_query_conditions")
        cls.doc_registry = _app_hooks("has_permission")

    def test_no_wildcard_registration(self):
        """A "*" entry would apply to every doctype and make the checks below meaningless."""
        for label, registry in (("query", self.query_registry), ("has_permission", self.doc_registry)):
            with self.subTest(registry=label):
                self.assertNotIn(
                    "*",
                    registry,
                    f"this app registers a wildcard {label} handler; the per-doctype reasoning "
                    "in this module no longer describes what is in effect",
                )

    def test_every_list_scoped_doctype_has_a_document_level_check(self):
        """The dangerous direction: scoped lists, unscoped documents.

        This is the assertion that would have caught Employee (#259) and Team (#257).
        """
        missing = set(self.query_registry) - set(self.doc_registry) - set(DOC_CHECK_EXEMPTIONS)

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
        missing = set(self.doc_registry) - set(self.query_registry) - set(LIST_SCOPE_EXEMPTIONS)

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
        self.assertTrue(DOC_CHECK_EXEMPTIONS, "exemption list is empty; this test would assert nothing")

        for doctype, reason in DOC_CHECK_EXEMPTIONS.items():
            with self.subTest(doctype=doctype):
                self.assertTrue(
                    frappe.db.get_value("DocType", doctype, "istable"),
                    f"{doctype} is exempted as a child table ({reason}) but istable is not set, "
                    "so nothing governs it at document level",
                )

    def test_donation_exemption_premise_still_holds(self):
        """The Donation exemption is only valid while its DocPerm stays narrow.

        Unlike the child-table exemptions, this one rests on a fact that is editable
        from the Role Permission Manager UI with no code change. Assert it, so the
        exemption invalidates itself instead of quietly becoming wrong.
        """
        read_roles = {perm.role for perm in frappe.get_meta("Donation").permissions if perm.read}

        self.assertEqual(
            read_roles,
            DONATION_READ_ROLES,
            "Donation's read DocPerm changed. The LIST_SCOPE_EXEMPTIONS entry assumes the role "
            "layer denies everyone but these roles, so Donation needs no query condition. That "
            "is no longer true: either register get_donation_permission_query "
            "(permissions.py:841 -- but read the exemption note first, it denies the webhook "
            "account) or update DONATION_READ_ROLES and the reasoning.",
        )

    def test_exemptions_are_filed_in_the_right_direction_and_not_stale(self):
        """An exemption must describe a gap that actually exists, in the dict that has it.

        Three failure modes, all silent without this: an exemption for a doctype in
        neither registry (leftover, and it pre-authorises the next doctype to reuse the
        name); an exemption filed in the wrong direction; and a redundant one, where the
        doctype has since gained the entry it was exempted from needing.
        """
        registered = set(self.query_registry) | set(self.doc_registry)

        stale = (set(DOC_CHECK_EXEMPTIONS) | set(LIST_SCOPE_EXEMPTIONS)) - registered
        self.assertFalse(
            stale, f"{sorted(stale)} are exempted but appear in neither registry; drop the exemption"
        )

        misfiled = set(DOC_CHECK_EXEMPTIONS) - set(self.query_registry)
        self.assertFalse(
            misfiled,
            f"{sorted(misfiled)} are in DOC_CHECK_EXEMPTIONS (which excuses a MISSING doc check) "
            "but have no query condition either; they belong in neither dict as written",
        )

        redundant = set(DOC_CHECK_EXEMPTIONS) & set(self.doc_registry)
        self.assertFalse(
            redundant,
            f"{sorted(redundant)} now HAVE a has_permission entry, so the exemption is obsolete "
            "and hides them from the check; remove it",
        )

        misfiled_list = set(LIST_SCOPE_EXEMPTIONS) - set(self.doc_registry)
        self.assertFalse(
            misfiled_list,
            f"{sorted(misfiled_list)} are in LIST_SCOPE_EXEMPTIONS but have no has_permission entry",
        )

        redundant_list = set(LIST_SCOPE_EXEMPTIONS) & set(self.query_registry)
        self.assertFalse(
            redundant_list,
            f"{sorted(redundant_list)} now HAVE a query condition, so the exemption is obsolete",
        )

    def test_permission_type_kwarg_partition_is_unchanged(self):
        """Pin which handlers receive the real ptype, across the WHOLE registry.

        has_controller_permissions calls frappe.call(method, doc=doc, ptype=ptype, ...)
        and frappe.call's get_newargs drops kwargs the callee does not declare. A helper
        naming the parameter `permission_type` therefore always sees None -- and
        `_check_service_account_permission` does `perm_type = permission_type or "read"`,
        so every service-account check is evaluated as a READ whatever the real operation.

        Renaming those parameters to `ptype` looks like a tidy-up and would silently
        change webhook answers for write/create/submit. Asserting the whole partition
        (rather than one example) means any such rename fails here and has to be argued
        for in this file.
        """
        supplied = {"doc": None, "user": "Administrator", "ptype": "write"}

        receives_ptype = set()
        for doctype, paths in self.doc_registry.items():
            for dotted_path in paths:
                handler = frappe.get_attr(dotted_path)
                if "ptype" in frappe.get_newargs(handler, supplied):
                    receives_ptype.add(doctype)

        self.assertEqual(
            receives_ptype,
            PTYPE_AWARE_HANDLERS,
            "the set of has_permission handlers that actually receive `ptype` changed. "
            "Gaining one means a handler was renamed from `permission_type` to `ptype`: "
            "verify it does not forward the value into _check_service_account_permission, "
            "which would start evaluating non-read operations differently for the webhook "
            "account. Losing one means the reverse. Update PTYPE_AWARE_HANDLERS deliberately.",
        )
