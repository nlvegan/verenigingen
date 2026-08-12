"""Test utilities package for the Verenigingen app.

Importing this package (which every ``VereningingenTestCase`` test does, via
``from verenigingen.tests.utils.base import ...``) suppresses the slow
synchronous workflow-action emails for the test process.

Frappe's ``process_workflow_actions()`` runs ``send_workflow_action_email``
synchronously in test mode (``now=frappe.in_test``); that email renders a PDF
of the document, which on a CI/test box without a network reachable to
wkhtmltopdf raises ``OSError: ... HostNotFoundError`` — erroring out *every*
test that inserts a Member (the active ``Membership Application Workflow`` is on
the Member doctype).

The ``before_tests`` hook only fires for the ``integration`` category, and
``VereningingenTestCase`` extends the compat ``FrappeTestCase`` (categorized
``unspecified-category``), so neither the hook nor the
``enhanced_test_factory`` import-time patch reaches these tests. Applying the
same idempotent patch here closes that gap for the ``base.py`` test base class.
"""

from verenigingen.tests.harness_logger import get_harness_logger

try:
    from verenigingen.tests.setup import disable_workflow_action_emails

    disable_workflow_action_emails()
except Exception as e:  # pragma: no cover - defensive: never block test collection
    # Not `frappe.logger()`: that one sits at ERROR under `bench run-tests`, so this
    # warning was discarded. See verenigingen/tests/harness_logger.py.
    get_harness_logger("tests.utils").warning(f"disable_workflow_action_emails import failed: {e}")
