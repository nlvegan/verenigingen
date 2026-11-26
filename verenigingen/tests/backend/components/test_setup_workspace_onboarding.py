# Integration tests for the workspace / onboarding / membership-application
# setup functions in verenigingen/setup/__init__.py.
#
# These are install-time, idempotent, safe-to-rerun functions that create or
# update the "Verenigingen" Workspace, the "Verenigingen" Module Onboarding
# document (+ its Onboarding Steps), Email Templates and web-page config.
#
# Strategy: call the real function against the live test-site database and assert
# on observable post-conditions (records exist, links/steps are present, the
# workspace stays intact). Idempotency is asserted by calling twice and checking
# the relevant counts do not drift. We never assert "created N" for the workspace
# functions because on an installed test site the records already exist.

import contextlib
import io

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod


class TestSetupMembershipApplicationSystem(FrappeTestCase):
    """setup_membership_application_system() + its web-page / manual wrappers."""

    def test_setup_application_web_pages_runs_without_error(self):
        # Pure informational/print function: must not raise and returns None.
        self.assertIsNone(setup_mod.setup_application_web_pages())

    def test_setup_membership_application_system_creates_basic_templates(self):
        # Orchestrates the application email-template seeders. The basic
        # confirmation template must exist after running it.
        setup_mod.setup_membership_application_system()
        self.assertTrue(
            frappe.db.exists("Email Template", "membership_application_confirmation"),
            "basic application confirmation template should exist after setup",
        )
        self.assertTrue(
            frappe.db.exists("Email Template", "membership_welcome"),
            "membership_welcome template should exist after setup",
        )

    def test_setup_membership_application_system_idempotent(self):
        setup_mod.setup_membership_application_system()
        before = frappe.db.count("Email Template")
        setup_mod.setup_membership_application_system()
        after = frappe.db.count("Email Template")
        self.assertEqual(before, after, "re-running must not create duplicate templates")

    def test_setup_membership_application_system_manual_wrapper(self):
        # Whitelisted manual endpoint must return a success envelope and have
        # the same observable effect as the underlying function.
        result = setup_mod.setup_membership_application_system_manual()
        self.assertTrue(result["success"])
        self.assertIn("completed", result["message"].lower())
        self.assertTrue(frappe.db.exists("Email Template", "membership_application_confirmation"))


class TestReinstallOnboarding(FrappeTestCase):
    """reinstall_onboarding() — rebuilds the Module Onboarding doc + 7 steps."""

    # The 7 steps this function is expected to create, in order. This list must
    # stay in step with the on-disk module_onboarding fixture: the seed used to
    # omit Verenigingen-Configure-Security, so running it against a site dropped
    # that step from the flow and left the Onboarding Step doc orphaned.
    EXPECTED_STEP_NAMES = [
        "Verenigingen-Setup-Settings",
        "Verenigingen-Configure-Security",
        "Verenigingen-Create-Member",
        "Verenigingen-Create-Membership-Type",
        "Verenigingen-Create-Membership",
        "Verenigingen-Create-Chapter",
        "Verenigingen-Create-Volunteer",
    ]

    def test_reinstall_creates_module_onboarding_with_all_steps(self):
        result = setup_mod.reinstall_onboarding()
        self.assertTrue(result["success"], result.get("message"))
        self.assertEqual(result["steps_created"], len(self.EXPECTED_STEP_NAMES))

        self.assertTrue(frappe.db.exists("Module Onboarding", "Verenigingen"))
        mo = frappe.get_doc("Module Onboarding", "Verenigingen")
        self.assertEqual(
            len(mo.steps),
            len(self.EXPECTED_STEP_NAMES),
            "Module Onboarding must carry a reference for every seeded step",
        )

        actual_step_refs = [row.step for row in mo.steps]
        self.assertEqual(actual_step_refs, self.EXPECTED_STEP_NAMES)

    def test_reinstall_sets_expected_metadata(self):
        setup_mod.reinstall_onboarding()
        mo = frappe.get_doc("Module Onboarding", "Verenigingen")
        self.assertEqual(mo.title, "Let's set up your Association Management.")
        # Guards the module-registration fix: the seed must register the doc
        # under the Verenigingen module (previously the buggy "E-Boekhouden").
        self.assertEqual(mo.module, "Verenigingen")
        self.assertEqual(int(mo.is_complete), 0)
        allowed_roles = {row.role for row in mo.allow_roles}
        self.assertIn("System Manager", allowed_roles)
        self.assertIn("Verenigingen Administrator", allowed_roles)

    # Full set of keys the production reinstall_onboarding() seed passes to
    # get_doc() for the Module Onboarding doc (steps are attached separately).
    MO_SEED_FIELDS = {
        "title",
        "subtitle",
        "module",
        "success_message",
        "documentation_url",
        "allow_roles",
        "is_complete",
    }
    # Full set of keys each Onboarding Step seed dict passes to get_doc().
    STEP_SEED_FIELDS = {
        "title",
        "action",
        "action_label",
        "creation_doctype",
        "description",
        "is_complete",
        "is_mandatory",
        "is_skipped",
        "reference_document",
        "show_form_tour",
        "show_full_form",
        "validate_action",
    }
    # Seed keys CONFIRMED absent from the current Module Onboarding / Onboarding
    # Step doctypes: Frappe silently drops these on get_doc(), so the intended
    # value is never persisted. They are accepted-but-known stale.
    MO_KNOWN_DROPPED = {"subtitle", "success_message", "documentation_url"}
    STEP_KNOWN_DROPPED = {"creation_doctype", "is_mandatory"}
    # Meta concepts that are not docfields — never compared against live fields.
    META_KEYS = {"doctype", "name"}

    def test_reinstall_only_writes_fields_that_exist_on_doctypes(self):
        """Drift guard for known-stale seed keys.

        Frappe silently drops unknown keys passed to get_doc(), so a stale key
        is invisible — the value the author intended is never persisted. The
        reinstall_onboarding() seed currently writes a handful of keys that no
        longer exist on the Module Onboarding / Onboarding Step doctypes; those
        are pinned in MO_KNOWN_DROPPED / STEP_KNOWN_DROPPED.

        We assert that the set of seed keys NOT present on the live doctype is
        EXACTLY the known-dropped set. This fails in two directions:
          * a NEW field gets silently dropped (a real regression — a value the
            author expects to persist is being thrown away), or
          * a known-dropped field is re-added/renamed onto the doctype (so the
            person who fixed it can remove it from the KNOWN_DROPPED set).
        """
        mo_live = {f.fieldname for f in frappe.get_meta("Module Onboarding").fields}
        step_live = {f.fieldname for f in frappe.get_meta("Onboarding Step").fields}

        mo_dropped = (self.MO_SEED_FIELDS - self.META_KEYS) - mo_live
        step_dropped = (self.STEP_SEED_FIELDS - self.META_KEYS) - step_live

        # Assert the dropped set is a SUBSET of the known-dropped set rather than
        # exactly equal. The known-dropped fields are version-dependent: a newer
        # Frappe (as on fresh CI) re-introduces `subtitle` / `success_message` /
        # `documentation_url` onto Module Onboarding, so they are no longer
        # dropped there, while an older dev schema still drops them. Either way is
        # benign. The real regression we must catch is a NEW seed key being
        # silently dropped (a value the author expects to persist being thrown
        # away), which would make `mo_dropped` exceed the known set.
        unexpected_mo = mo_dropped - self.MO_KNOWN_DROPPED
        unexpected_step = step_dropped - self.STEP_KNOWN_DROPPED
        self.assertEqual(
            unexpected_mo,
            set(),
            "A Module Onboarding seed key is silently dropped (not on the live "
            f"doctype and not in MO_KNOWN_DROPPED): {unexpected_mo}",
        )
        self.assertEqual(
            unexpected_step,
            set(),
            "An Onboarding Step seed key is silently dropped (not on the live "
            f"doctype and not in STEP_KNOWN_DROPPED): {unexpected_step}",
        )

    def test_reinstall_creates_each_onboarding_step_document(self):
        setup_mod.reinstall_onboarding()
        for step_name in self.EXPECTED_STEP_NAMES:
            self.assertTrue(
                frappe.db.exists("Onboarding Step", step_name),
                f"Onboarding Step '{step_name}' should exist after reinstall",
            )
        # Verify one step carries the structural fields the seed sets (and that
        # the doctype actually persists).
        step = frappe.get_doc("Onboarding Step", "Verenigingen-Setup-Settings")
        self.assertEqual(step.reference_document, "Verenigingen Settings")
        self.assertEqual(step.title, "Configure Verenigingen Settings")
        self.assertEqual(step.action, "Create Entry")
        self.assertEqual(int(step.validate_action), 1)

    def test_reinstall_steps_carry_expected_reference_documents(self):
        setup_mod.reinstall_onboarding()
        expected_refs = {
            "Verenigingen-Setup-Settings": "Verenigingen Settings",
            "Verenigingen-Configure-Security": "System Settings",
            "Verenigingen-Create-Member": "Member",
            "Verenigingen-Create-Membership-Type": "Membership Type",
            "Verenigingen-Create-Membership": "Membership",
            "Verenigingen-Create-Chapter": "Chapter",
            "Verenigingen-Create-Volunteer": "Volunteer",
        }
        for step_name, ref in expected_refs.items():
            step = frappe.get_doc("Onboarding Step", step_name)
            self.assertEqual(
                step.reference_document,
                ref,
                f"{step_name} should reference {ref}",
            )

    def test_reinstall_is_idempotent(self):
        # First call establishes the doc; second must rebuild to the same steps
        # without growing the Onboarding Step table.
        setup_mod.reinstall_onboarding()
        steps_before = frappe.db.count("Onboarding Step")
        result = setup_mod.reinstall_onboarding()
        steps_after = frappe.db.count("Onboarding Step")
        self.assertEqual(result["steps_created"], len(self.EXPECTED_STEP_NAMES))
        self.assertEqual(
            steps_before,
            steps_after,
            "re-running reinstall must not duplicate Onboarding Step documents",
        )
        mo = frappe.get_doc("Module Onboarding", "Verenigingen")
        self.assertEqual(len(mo.steps), len(self.EXPECTED_STEP_NAMES))


class TestInstallAndLinkOnboarding(FrappeTestCase):
    """install_and_link_onboarding() — custom field + MO doc + workspace link."""

    def test_install_creates_custom_field_and_links_workspace(self):
        # Its failures are swallowed and only printed, so the printout is the
        # one channel that shows a step went wrong.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            setup_mod.install_and_link_onboarding()
        self.assertNotIn("Failed to create custom field", out.getvalue())
        # Positive control: the meta check found the field and skipped the insert.
        # Without it, rewording the failure message above would pass silently.
        self.assertIn("Workspace already has a module_onboarding field", out.getvalue())

        # Workspace must have a module_onboarding field: native since frappe
        # v16.50 (frappe#39927), otherwise the Custom Field this function adds.
        self.assertTrue(
            frappe.get_meta("Workspace").has_field("module_onboarding"),
            "Workspace should have a module_onboarding field (native or custom)",
        )
        # The Module Onboarding document must exist (created via reinstall if absent).
        self.assertTrue(frappe.db.exists("Module Onboarding", "Verenigingen"))

        # The workspace must be linked to the Module Onboarding doc.
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        self.assertEqual(workspace.module_onboarding, "Verenigingen")

    def test_install_and_link_onboarding_idempotent(self):
        setup_mod.install_and_link_onboarding()
        cf_before = frappe.db.count("Custom Field")
        mo_before = frappe.db.count("Module Onboarding")

        setup_mod.install_and_link_onboarding()
        cf_after = frappe.db.count("Custom Field")
        mo_after = frappe.db.count("Module Onboarding")

        self.assertEqual(cf_before, cf_after, "custom field must not be duplicated")
        self.assertEqual(mo_before, mo_after, "Module Onboarding must not be duplicated")
        # Workspace link remains set.
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        self.assertEqual(workspace.module_onboarding, "Verenigingen")


class TestSetupWorkspace(FrappeTestCase):
    """cleanup_workspace_links / setup_workspace."""

    def test_workspace_survives_setup(self):
        # Guard against the functions accidentally deleting the workspace.
        setup_mod.setup_workspace()
        self.assertTrue(
            frappe.db.exists("Workspace", "Verenigingen"),
            "setup_workspace must never leave the site without the workspace",
        )

    def test_setup_workspace_creates_the_custom_block_a_fresh_install_lacks(self):
        # #2150: `install-app` runs after_install BEFORE the fixtures sync, so on a fresh
        # install the Custom HTML Block the shipped workspace names does not exist yet and
        # workspace.save() raised "Could not find Row #1: Custom Block Name: Page Links".
        # Reproduce that state by deleting the block (the Workspace row stays), then run the step.
        block_names = frappe.get_all(
            "Workspace Custom Block", filters={"parent": "Verenigingen"}, pluck="custom_block_name"
        )
        self.assertTrue(block_names, "the shipped workspace must reference a Custom HTML Block")
        for name in block_names:
            frappe.db.delete("Custom HTML Block", {"name": name})
            self.assertFalse(frappe.db.exists("Custom HTML Block", name), "precondition: block removed")
        self.addCleanup(setup_mod.ensure_workspace_custom_blocks)

        # The onboarding link is written by the LAST step of setup_workspace, which the failing
        # save used to skip, so it proves the later steps completed.
        frappe.db.set_value("Workspace", "Verenigingen", "module_onboarding", None)

        setup_mod.setup_workspace()

        shipped = self._shipped_custom_blocks()
        for name in block_names:
            self.assertTrue(frappe.db.exists("Custom HTML Block", name), f"{name} was not created")
            # The recreated block must carry the shipped content, not just exist.
            self.assertTrue(shipped[name]["html"], "fixture must carry html for this to discriminate")
            for field in ("html", "script", "style"):
                self.assertEqual(
                    frappe.db.get_value("Custom HTML Block", name, field) or "",
                    shipped[name].get(field) or "",
                    f"{name}.{field} differs from fixtures/custom_html_block.json",
                )
        self.assertEqual(
            frappe.db.get_value("Workspace", "Verenigingen", "module_onboarding"),
            "Verenigingen",
            "the steps after the custom-block repair did not complete",
        )

    @staticmethod
    def _shipped_custom_blocks():
        import json

        path = frappe.get_app_path("verenigingen", "fixtures", "custom_html_block.json")
        with open(path) as f:
            return {row["name"]: row for row in json.load(f)}

    def test_ensure_workspace_custom_blocks_refuses_a_block_that_is_not_shipped(self):
        # A referenced block with no fixture entry cannot be created: refuse loudly rather
        # than let workspace.save() fail later with a less specific message.
        unshipped = "Unshipped Block 2150"
        self.assertNotIn(unshipped, self._shipped_custom_blocks())
        row = frappe.get_doc(
            {
                "doctype": "Workspace Custom Block",
                "parent": "Verenigingen",
                "parenttype": "Workspace",
                "parentfield": "custom_blocks",
                "custom_block_name": unshipped,
                "label": unshipped,
            }
        ).insert(ignore_permissions=True, ignore_links=True)
        self.addCleanup(frappe.db.delete, "Workspace Custom Block", {"name": row.name})
        with self.assertRaisesRegex(RuntimeError, "not shipped"):
            setup_mod.ensure_workspace_custom_blocks()

    def test_ensure_workspace_custom_blocks_leaves_an_existing_block_alone(self):
        # Only proves `ensure` does not touch an existing block; the fixtures sync
        # overwrites the block on every migrate regardless.
        name = frappe.get_all(
            "Workspace Custom Block", filters={"parent": "Verenigingen"}, pluck="custom_block_name"
        )[0]
        setup_mod.ensure_workspace_custom_blocks()  # make sure it exists
        frappe.db.set_value("Custom HTML Block", name, "html", "<p>edited</p>")
        setup_mod.ensure_workspace_custom_blocks()
        self.assertEqual(frappe.db.get_value("Custom HTML Block", name, "html"), "<p>edited</p>")

    def test_cleanup_removes_only_links_to_missing_doctypes(self):
        # After cleanup, no remaining DocType-type link may point at a
        # non-existent DocType.
        setup_mod.cleanup_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        for link in workspace.links:
            link_to = link.get("link_to")
            if link_to and link.get("link_type") == "DocType":
                self.assertTrue(
                    frappe.db.exists("DocType", link_to),
                    f"cleanup left a dangling DocType link: {link.get('label')} -> {link_to}",
                )

    def _links_present(self, labels):
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        return {link.get("label") for link in workspace.links} & set(labels)

    def test_cleanup_keeps_valid_report_and_page_links_and_drops_dangling_ones(self):
        """#2151: each link is checked against its OWN link_type, not always DocType.

        Appends real Workspace Link rows (probe shortcut: rows added directly, not
        through the install flow) inside a savepoint that is rolled back after.
        """
        # A Member report: its name never collides with a DocType, which the
        # "doctype named as report" control below relies on.
        report = frappe.db.get_value("Report", {"ref_doctype": "Member"}, "name")
        page = frappe.db.get_value("Page", {}, "name")
        self.assertTrue(report and page, "site must have a Report and a Page to link to")

        frappe.db.savepoint("t2151")
        self.addCleanup(frappe.db.rollback, save_point="t2151")
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        probes = {
            "T2151 keep report": ("Report", report),
            "T2151 keep page": ("Page", page),
            "T2151 drop report": ("Report", "T2151 No Such Report"),
            "T2151 drop page": ("Page", "t2151-no-such-page"),
            "T2151 drop doctype": ("DocType", "T2151 No Such DocType"),
            # Control for a "does it exist as ANY type" wrong fix: these names exist, but
            # not as the type the link claims.
            "T2151 drop report named as doctype": ("Report", "Member"),
            "T2151 drop doctype named as report": ("DocType", report),
            # No blank-link_type probe: Workspace.save refuses a link_to without a link_type
            # ("Link Type must be set first"), so that row cannot exist in a saved workspace.
            # The cleanup's blank -> DocType default only ever meets Card Breaks without link_to.
        }
        # Workspace.save validates links, so dangling rows go in below the controller.
        for idx, (label, (link_type, link_to)) in enumerate(probes.items(), start=1000):
            frappe.get_doc(
                {
                    "doctype": "Workspace Link",
                    "parent": workspace.name,
                    "parenttype": "Workspace",
                    "parentfield": "links",
                    "idx": idx,
                    "type": "Link",
                    "label": label,
                    "link_type": link_type,
                    "link_to": link_to,
                }
            ).db_insert()
        self.assertEqual(self._links_present(probes), set(probes), "fixture rows must exist before cleanup")

        setup_mod.cleanup_workspace_links()

        self.assertEqual(
            self._links_present(probes),
            {"T2151 keep report", "T2151 keep page"},
        )

    def test_cleanup_workspace_links_idempotent(self):
        setup_mod.cleanup_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        count_before = len(workspace.links)
        # A second cleanup pass should find nothing to remove.
        setup_mod.cleanup_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        count_after = len(workspace.links)
        self.assertEqual(count_before, count_after)

    def test_setup_workspace_manual_wrapper(self):
        result = setup_mod.setup_workspace_manual()
        self.assertTrue(result["success"])
        self.assertIn("completed", result["message"].lower())
        self.assertTrue(frappe.db.exists("Workspace", "Verenigingen"))
        # After the full orchestration the onboarding link is set.
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        self.assertEqual(workspace.module_onboarding, "Verenigingen")


class TestRunCompleteSetupWrapper(FrappeTestCase):
    """run_complete_setup() — whitelisted full-install orchestration wrapper."""

    def test_run_complete_setup_returns_success_envelope(self):
        # execute_after_install seeds all reference data and the workspace; it is
        # idempotent on an already-installed test site. Assert the envelope and a
        # representative post-condition (workspace + a seeded reference record).
        result = setup_mod.run_complete_setup()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertTrue(result["success"], result.get("message"))
        self.assertTrue(frappe.db.exists("Workspace", "Verenigingen"))
        self.assertTrue(frappe.db.exists("Module Onboarding", "Verenigingen"))


class TestWorkspaceSetupSurvivesTheFixturesSync(FrappeTestCase):
    """#2349: sync_fixtures re-imports the Workspace fixture on `install-app` (after
    after_install) and on EVERY migrate, so the onboarding link setup_workspace() writes was
    reverted unless the fixture itself ships it.

    Maintainer ruling (2026-11-19): ONBOARDING ONLY. The empty 'Termination & Appeals' card
    break and the 'Termination Requests' / 'SEPA Mandates' shortcuts that setup_workspace()
    used to add (they rendered nothing: the card had no children and no content block
    referenced the shortcuts) are removed from the setup and are NOT shipped in the fixture.
    """

    CARD = "Termination & Appeals"
    SHORTCUTS = {"Termination Requests", "SEPA Mandates"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Start from what a migrate leaves, not from whatever an earlier test or an old
        # setup_workspace() left on the site (one sync: it takes over a minute).
        cls._quietly(cls._sync_once)
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        # Workspace is shared site state and setup_workspace() commits, so a rollback is not
        # enough: put the migrate-state rows back by hand.
        cls._saved = {
            "module_onboarding": workspace.module_onboarding,
            "links": [row.as_dict(no_nulls=False) for row in workspace.links],
            "shortcuts": [row.as_dict(no_nulls=False) for row in workspace.shortcuts],
        }
        cls.addClassCleanup(cls._cleanup_restore_the_workspace)

    @staticmethod
    def _sync_once():
        from frappe.utils.fixtures import sync_fixtures

        sync_fixtures("verenigingen")

    def setUp(self):
        super().setUp()
        self._cleanup_restore_the_workspace()

    @classmethod
    def _cleanup_restore_the_workspace(cls):
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        workspace.module_onboarding = cls._saved["module_onboarding"]
        for table in ("links", "shortcuts"):
            workspace.set(table, [])
            for row in cls._saved[table]:
                workspace.append(table, {k: v for k, v in row.items() if k not in ("name", "idx")})
        workspace.save(ignore_permissions=True)
        frappe.db.commit()

    @staticmethod
    def _state():
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        return {
            "module_onboarding": workspace.module_onboarding,
            "labels": {row.label for row in workspace.links},
            "shortcuts": {row.label for row in workspace.shortcuts},
        }

    @staticmethod
    def _quietly(fn, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args)

    def _sync_fixtures_as_migrate_does(self):
        from frappe.utils.fixtures import sync_fixtures

        self._quietly(sync_fixtures, "verenigingen")

    def _put_the_retired_card_and_shortcuts_back(self):
        """The state an existing site is in if the old setup_workspace() ran on it."""
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        # Start clean: an earlier test in the module may already have left some of them.
        workspace.set("links", [row for row in workspace.links if row.label != self.CARD])
        workspace.set("shortcuts", [row for row in workspace.shortcuts if row.label not in self.SHORTCUTS])
        workspace.append("links", {"type": "Card Break", "label": self.CARD, "link_type": "DocType"})
        workspace.append(
            "shortcuts",
            {"type": "DocType", "label": "Termination Requests", "link_to": "Membership Termination Request"},
        )
        workspace.append("shortcuts", {"type": "DocType", "label": "SEPA Mandates", "link_to": "SEPA Mandate"})
        workspace.save()  # the test user is Administrator
        state = self._state()
        self.assertIn(self.CARD, state["labels"], "precondition: card present")
        self.assertTrue(self.SHORTCUTS <= state["shortcuts"], "precondition: shortcuts present")

    def test_onboarding_written_by_setup_workspace_survives_the_next_fixtures_sync(self):
        self._quietly(setup_mod.setup_workspace)
        written = self._state()
        # Control: the step really wrote the onboarding, or the comparison below is empty.
        self.assertEqual(written["module_onboarding"], "Verenigingen")

        self._sync_fixtures_as_migrate_does()

        self.assertEqual(self._state(), written, "the fixtures sync reverted setup_workspace()")

    def test_setup_workspace_does_not_add_the_retired_card_or_shortcuts(self):
        # Control for the ruling: red if setup_workspace() ever adds them again.
        self._quietly(setup_mod.setup_workspace)
        state = self._state()
        self.assertNotIn(self.CARD, state["labels"])
        self.assertFalse(self.SHORTCUTS & state["shortcuts"])

    def test_a_workspace_without_onboarding_converges_through_the_fixtures_sync_alone(self):
        # Fresh install: after_install's setup_workspace runs BEFORE the fixtures sync, so the
        # sync is the last writer and must itself carry the onboarding link.
        frappe.db.set_value("Workspace", "Verenigingen", "module_onboarding", None)
        self.assertIsNone(self._state()["module_onboarding"], "precondition: stripped")

        self._sync_fixtures_as_migrate_does()

        after = self._state()
        self.assertEqual(after["module_onboarding"], "Verenigingen")
        self.assertNotIn(self.CARD, after["labels"])
        self.assertFalse(self.SHORTCUTS & after["shortcuts"])

    def test_an_existing_site_loses_the_retired_card_and_shortcuts_on_the_next_fixtures_sync(self):
        self._put_the_retired_card_and_shortcuts_back()

        self._sync_fixtures_as_migrate_does()

        after = self._state()
        self.assertNotIn(self.CARD, after["labels"])
        self.assertFalse(self.SHORTCUTS & after["shortcuts"])
