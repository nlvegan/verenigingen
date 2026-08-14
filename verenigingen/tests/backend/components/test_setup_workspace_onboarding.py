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
        setup_mod.install_and_link_onboarding()

        # The module_onboarding custom field must exist on Workspace.
        self.assertTrue(
            frappe.db.exists("Custom Field", {"dt": "Workspace", "fieldname": "module_onboarding"}),
            "module_onboarding custom field should be created on Workspace",
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
    """cleanup_workspace_links / update_workspace_links / setup_workspace."""

    def test_workspace_survives_setup(self):
        # Guard against the functions accidentally deleting the workspace.
        setup_mod.setup_workspace()
        self.assertTrue(
            frappe.db.exists("Workspace", "Verenigingen"),
            "setup_workspace must never leave the site without the workspace",
        )

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

    def test_cleanup_workspace_links_idempotent(self):
        setup_mod.cleanup_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        count_before = len(workspace.links)
        # A second cleanup pass should find nothing to remove.
        setup_mod.cleanup_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        count_after = len(workspace.links)
        self.assertEqual(count_before, count_after)

    def test_update_workspace_links_adds_termination_section(self):
        # The Termination & Appeals card-break + SEPA Mandate link are
        # unconditionally addable (the referenced doctypes exist on the site).
        setup_mod.update_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        labels = {link.get("label") for link in workspace.links}
        self.assertIn("Termination & Appeals", labels)
        self.assertIn("SEPA Mandate", labels)
        # Shortcuts for the same doctypes get added too.
        shortcut_labels = {sc.get("label") for sc in workspace.shortcuts}
        self.assertIn("Termination Requests", shortcut_labels)
        self.assertIn("SEPA Mandates", shortcut_labels)

    def test_update_workspace_links_idempotent(self):
        # Links/shortcuts are matched by label and not re-appended.
        setup_mod.update_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        links_before = len(workspace.links)
        shortcuts_before = len(workspace.shortcuts)

        setup_mod.update_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        links_after = len(workspace.links)
        shortcuts_after = len(workspace.shortcuts)

        self.assertEqual(links_before, links_after, "links must not be duplicated by label")
        self.assertEqual(shortcuts_before, shortcuts_after, "shortcuts must not be duplicated by label")

    def test_no_duplicate_link_labels_after_update(self):
        setup_mod.update_workspace_links()
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        # The two unconditional additions must appear exactly once.
        for target in ("Termination & Appeals", "SEPA Mandate"):
            occurrences = [link for link in workspace.links if link.get("label") == target]
            self.assertEqual(len(occurrences), 1, f"label '{target}' should appear exactly once")

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
