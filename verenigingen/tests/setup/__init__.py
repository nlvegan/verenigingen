"""
Test setup hooks for Verenigingen app.

This module provides the before_tests hook that ensures ERPNext test fixtures
(Company, etc.) are created before our tests run.
"""
import frappe


def disable_workflow_action_emails():
    """Neutralize synchronous workflow-action emails for the whole test run.

    Frappe's ``process_workflow_actions()`` enqueues ``send_workflow_action_email``
    with ``now=frappe.in_test``, so in test mode it runs SYNCHRONOUSLY inside
    ``doc.insert()``/``doc.save()``. That email renders a PDF of the document
    (BeautifulSoup + the pure-Python html5lib parser), which is pathologically
    slow — tens of seconds per document.

    The production ``Membership Application Workflow`` is active on the Member
    doctype with email alerts enabled on every state, so every test that inserts
    a Member paid this cost. Modules creating ~12 Members in setUp hung for
    13+ minutes; the whole suite was slowed and made flaky by it.

    We replace the email function with a no-op for the test process. The
    ``Workflow Action`` DocType rows are still created — that happens *before*
    the email call in ``process_workflow_actions`` — so workflow behaviour tests
    remain valid. Only the email + PDF side effect is suppressed.

    NOTE: this ``before_tests`` hook only runs for the ``integration`` test
    category. ``EnhancedTestCase`` tests are categorized ``unspecified-category``
    (because ``FrappeTestCase`` is not their *direct* base), so they never reach
    this hook — for them the same patch is applied at import time of
    ``verenigingen.tests.fixtures.enhanced_test_factory``. The patch is
    idempotent, so applying it from both places is harmless.
    """
    try:
        from frappe.workflow.doctype.workflow_action import workflow_action

        def _noop_send_workflow_action_email(*args, **kwargs):
            return None

        workflow_action.send_workflow_action_email = _noop_send_workflow_action_email
    except Exception as e:  # pragma: no cover - defensive: never block the test run
        frappe.logger().warning(f"Could not disable workflow action emails for tests: {e}")


def before_tests():
    """
    Hook called before running tests for this app.

    Ensures ERPNext's test fixtures (Company, Item, etc.) are set up,
    since our app depends on ERPNext DocTypes.
    """
    # Suppress slow synchronous workflow-action emails (see function docstring)
    disable_workflow_action_emails()

    # Call ERPNext's before_tests to ensure basic setup
    try:
        from erpnext.setup.utils import before_tests as erpnext_before_tests
        erpnext_before_tests()
    except ImportError:
        frappe.logger().warning("ERPNext not installed, skipping ERPNext test setup")
    except Exception as e:
        frappe.logger().info(f"ERPNext before_tests: {e}")

    # Ensure all test companies exist by loading Company test records
    # ERPNext Account fixtures require: _Test Company, _Test Company 1,
    # _Test Company with perpetual inventory
    try:
        from frappe.test_runner import make_test_records

        required_companies = [
            "_Test Company",
            "_Test Company 1",
            "_Test Company with perpetual inventory",
        ]
        missing = [c for c in required_companies if not frappe.db.exists("Company", c)]

        if missing:
            # Force recreate to ensure all companies are created
            # (test record log may be stale)
            make_test_records("Company", verbose=False, force=True, commit=True)
            frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(f"Company test record creation failed: {e}")

    # Ensure Customer test records exist (needed by Item Price and other ERPNext fixtures)
    try:
        from frappe.test_runner import make_test_records

        if not frappe.db.exists("Customer", "_Test Customer"):
            make_test_records("Customer", verbose=False, force=True, commit=True)
            frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(f"Customer test record creation failed: {e}")
