"""
#1970: a background job whose user no longer exists must not recurse in ``_()``.

Frappe's ``_()`` resolves the job user's language lazily (``set_user_lang(job.user)``) and only
flips ``job.lang_resolved`` AFTER that lookup succeeds. For a user that has been deleted the lookup
raises ``DoesNotExistError`` whose message is built with ``_()`` again, so every translation in the
job (a handler's message, the audit logger, Frappe's own ``log_error``) recurses until
``RecursionError``. The framework is not ours to edit, so the app's ``before_job`` hook marks the
language resolved for a vanished user.

These tests simulate ``frappe.utils.background_jobs.execute_job`` by installing ``frappe.local.job``
and running the registered ``before_job`` hooks, exactly as that function does, then calling the job
function. They do not run a real RQ worker.
"""

import frappe
from frappe import _

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase


def _start_job_as(user):
    """Mimic execute_job's bootstrap for ``user``: set frappe.local.job, then run before_job hooks."""
    frappe.local.job = frappe._dict(
        method="test", job_name="test", kwargs={}, user=user, after_job=None
    )
    for task in frappe.get_hooks("before_job"):
        frappe.call(task, method="test", kwargs={}, transaction_type="job")


class TestBackgroundJobVanishedUser(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._prior_lang = getattr(frappe.local, "lang", "en")
        self._prior_job = getattr(frappe.local, "job", None)
        self.ghost = f"ghost-1970-{frappe.generate_hash(length=6)}@example.com"
        self.assertFalse(frappe.db.exists("User", self.ghost))

    def tearDown(self):
        frappe.local.lang = self._prior_lang
        frappe.local.job = self._prior_job
        super().tearDown()

    def test_missing_request_with_vanished_job_user_returns_benign_failure(self):
        _start_job_as(self.ghost)
        errors_before = frappe.db.count("Error Log")

        result = api.process_account_creation_request(f"ACR-NOPE-{frappe.generate_hash(length=6)}")

        self.assertFalse(result["success"])
        self.assertIn("no longer exists", str(result))
        # A benign skip stays out of the Error Log (see the handler's comment); an
        # unhandled RecursionError would have surfaced as a raise above.
        self.assertEqual(frappe.db.count("Error Log"), errors_before)

    def test_translation_in_a_vanished_user_job_does_not_recurse(self):
        """Class check: any ``_()`` in the job, not only the one handler."""
        _start_job_as(self.ghost)
        self.assertEqual(_("Account creation request no longer exists."), "Account creation request no longer exists.")

    def test_existing_job_user_still_gets_their_language(self):
        """Control: the hook must not stop language resolution for a user that exists."""
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"lang-1970-{frappe.generate_hash(length=6)}@example.com",
                "first_name": "Lang",
                "language": "nl",
                "send_welcome_email": 0,
            }
        ).insert()
        frappe.local.lang = "en"

        _start_job_as(user.name)
        _("Save")  # first translation triggers lazy language resolution

        self.assertEqual(frappe.local.lang, "nl")
        self.assertTrue(frappe.local.job.lang_resolved)
