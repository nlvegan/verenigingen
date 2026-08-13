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

Deliberately not wrapped in a try/except. A handler here would convert "the one
thing this package exists to do did not happen" into a log line, and the
consequence would arrive later as a storm of unrelated failures in every test
that touches a Member — the #291 shape, a swallowed setup failure resurfacing
far from its cause. This is import-time code in a package every
``VereningingenTestCase`` test imports, so the failure is never survivable in a
useful way: collection succeeding with the emails un-disabled is worse than
collection failing with a message that names the reason (#314).
"""

from verenigingen.tests.setup import disable_workflow_action_emails

disable_workflow_action_emails()
