# #1700: every transition action a shipped workflow uses needs a Workflow Action
# Master. Frappe imports the fixtures dir with links unvalidated, so the missing
# masters never block an install -- they surface when the Workflow is next saved.
#
# CI sites are fresh installs, so the masters ship as FIXTURES (imported by
# sync_fixtures on install/migrate), not as a patch.

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.fixtures import import_doc

WORKFLOW_NAME = "Periodic Donation Agreement Workflow"


def _wf1700_fixtures_dir():
    return frappe.get_app_path("verenigingen", "fixtures")


def _wf1700_load_fixture(fname):
    with open(os.path.join(_wf1700_fixtures_dir(), fname)) as f:
        return json.load(f)


def _shipped_workflows():
    """Every Workflow row any fixture file ships."""
    rows = []
    for fname in sorted(os.listdir(_wf1700_fixtures_dir())):
        if fname.endswith(".json"):
            rows += [r for r in _wf1700_load_fixture(fname) if isinstance(r, dict) and r.get("doctype") == "Workflow"]
    return rows


def _shipped_masters():
    return {r["workflow_action_name"] for r in _wf1700_load_fixture("workflow_action_master.json")}


def _shipped_actions():
    return {t["action"] for wf in _shipped_workflows() for t in wf.get("transitions", [])}


class TestWorkflowActionMasters(FrappeTestCase):
    def test_fixture_ships_the_donation_workflow(self):
        """Control for the sweep below: it must actually find a workflow."""
        names = {wf["name"] for wf in _shipped_workflows()}
        self.assertIn(WORKFLOW_NAME, names)
        self.assertEqual(len(_shipped_actions()), 5)

    def test_every_shipped_workflow_action_has_a_master(self):
        # Standard masters Frappe itself installs (Approve, Reject, Review) need no fixture.
        stock = {"Approve", "Reject", "Review"}
        missing = _shipped_actions() - _shipped_masters() - stock
        self.assertFalse(missing, f"workflow actions with no shipped Workflow Action Master: {missing}")

    def test_hook_exports_every_shipped_master(self):
        """hooks.fixtures filters the export: a master missing from the filter
        is dropped on the next `bench export-fixtures`."""
        from verenigingen.hooks.fixtures import fixtures

        exported = set()
        for entry in fixtures:
            if isinstance(entry, dict) and entry.get("doctype") == "Workflow Action Master":
                for field, op, values in entry["filters"]:
                    self.assertEqual((field, op), ("workflow_action_name", "in"))
                    exported |= set(values)
        self.assertLessEqual(_shipped_masters(), exported)

    def test_workflow_resaves_once_the_masters_fixture_is_imported(self):
        """Real behaviour: Workflow validation links every transition's action.
        Import the masters fixture exactly as sync_fixtures does (same call, same
        file), then save the Workflow that the fixtures dir already imported."""
        if not frappe.db.exists("Workflow", WORKFLOW_NAME):
            import_doc(os.path.join(_wf1700_fixtures_dir(), "periodic_donation_agreement_workflow.json"))
        # A previous run (or a synced site) may already hold the masters; start
        # from the state a pre-fix site is in. Rolled back with the test.
        for action in _shipped_actions():
            frappe.db.delete("Workflow Action Master", {"name": action})
        import_doc(os.path.join(_wf1700_fixtures_dir(), "workflow_action_master.json"))

        for action in _shipped_actions():
            self.assertTrue(frappe.db.exists("Workflow Action Master", action), action)
        frappe.get_doc("Workflow", WORKFLOW_NAME).save()
