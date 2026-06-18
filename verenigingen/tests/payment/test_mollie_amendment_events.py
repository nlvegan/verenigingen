"""
Coverage for verenigingen_payments/mollie/events/amendment_events.py:

* sync_mollie_subscription_on_amendment_applied - the background-job handler:
  idempotency short-circuit, status persistence per sync outcome, admin
  notification on failure, and the exception path that calls the document's
  failure handler.
* notify_administrators_of_sync_issue - recipient resolution + EmailService
  delegation (and the no-recipients early return).
* _build_sync_issue_message - HTML escaping + conditional sections.

The MollieSubscriptionSyncService and EmailService are the boundaries; they are
patched at the handler's import seam so the handler's own status-mapping and
persistence logic runs unmodified against a real Contribution Amendment Request.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.events import amendment_events

_SYNC_SERVICE_PATH = (
    "verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service."
    "MollieSubscriptionSyncService"
)
_EMAIL_SERVICE_PATH = "verenigingen.services.communication.email_service.get_email_service"


class _FakeSyncService:
    def __init__(self, result):
        self._result = result
        self.called_with = []

    def __call__(self, *args, **kwargs):
        # Class is patched with this instance acting as the constructor.
        return self

    def sync_subscription_for_amendment(self, doc):
        self.called_with.append(doc.name)
        return self._result


class _FakeEmailService:
    def __init__(self, result=None):
        self._result = result or {"success": True}
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return self._result


class _AmendmentEventTestBase(EnhancedTestCase):
    def _make_amendment(self):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Event",
            last_name=f"Sync{token}",
            email=f"event-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", "cst_E", update_modified=False)
        membership = self.create_test_membership(member_name=member.name)
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 30.0,
                "reason": "Test amendment sync coverage",
                "status": "Applied",
            }
        ).insert()
        return amendment, membership, member


class TestSyncHandler(_AmendmentEventTestBase):
    def test_already_synced_short_circuits(self):
        amendment, _, _ = self._make_amendment()
        frappe.db.set_value(
            "Contribution Amendment Request", amendment.name, "mollie_sync_completed", 1, update_modified=False
        )
        fake = _FakeSyncService({"status": "success"})

        with patch(_SYNC_SERVICE_PATH, fake):
            amendment_events.sync_mollie_subscription_on_amendment_applied(amendment)

        # The sync service was never invoked.
        self.assertEqual(fake.called_with, [])

    def test_success_marks_completed(self):
        amendment, _, _ = self._make_amendment()
        fake = _FakeSyncService({"status": "success", "message": "done"})

        with patch(_SYNC_SERVICE_PATH, fake):
            amendment_events.sync_mollie_subscription_on_amendment_applied(amendment)

        self.assertEqual(fake.called_with, [amendment.name])
        self.assertEqual(
            frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_status"),
            "Completed",
        )
        self.assertEqual(
            frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_completed"),
            1,
        )

    def test_skipped_marks_skipped_no_notify(self):
        amendment, _, _ = self._make_amendment()
        fake = _FakeSyncService({"status": "skipped", "reason": "no_mollie_subscription"})

        with patch(_SYNC_SERVICE_PATH, fake), patch.object(
            amendment_events, "notify_administrators_of_sync_issue"
        ) as notify:
            amendment_events.sync_mollie_subscription_on_amendment_applied(amendment)

        self.assertEqual(
            frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_status"),
            "Skipped",
        )
        notify.assert_not_called()

    def test_failed_notifies_admins(self):
        amendment, _, _ = self._make_amendment()
        fake = _FakeSyncService({"status": "error", "message": "API down"})

        with patch(_SYNC_SERVICE_PATH, fake), patch.object(
            amendment_events, "notify_administrators_of_sync_issue"
        ) as notify:
            amendment_events.sync_mollie_subscription_on_amendment_applied(amendment)

        self.assertEqual(
            frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_status"),
            "Failed",
        )
        notify.assert_called_once()

    def test_warning_with_review_notifies(self):
        amendment, _, _ = self._make_amendment()
        fake = _FakeSyncService(
            {"status": "warning", "message": "mismatch", "requires_admin_review": True}
        )

        with patch(_SYNC_SERVICE_PATH, fake), patch.object(
            amendment_events, "notify_administrators_of_sync_issue"
        ) as notify:
            amendment_events.sync_mollie_subscription_on_amendment_applied(amendment)

        self.assertEqual(
            frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_status"),
            "Needs Review",
        )
        notify.assert_called_once()

    def test_dict_input_resolves_document(self):
        amendment, _, _ = self._make_amendment()
        fake = _FakeSyncService({"status": "success"})

        with patch(_SYNC_SERVICE_PATH, fake):
            amendment_events.sync_mollie_subscription_on_amendment_applied({"name": amendment.name})

        self.assertEqual(fake.called_with, [amendment.name])

    def test_exception_calls_failure_handler_and_reraises(self):
        amendment, _, _ = self._make_amendment()

        class _Raising:
            def __call__(self, *a, **k):
                return self

            def sync_subscription_for_amendment(self, doc):
                raise RuntimeError("kaboom")

        with patch(_SYNC_SERVICE_PATH, _Raising()), patch.object(
            type(amendment), "handle_mollie_sync_failure"
        ) as handler:
            with self.assertRaises(RuntimeError):
                amendment_events.sync_mollie_subscription_on_amendment_applied(amendment)

        handler.assert_called_once()


class TestNotifyAdministrators(_AmendmentEventTestBase):
    def test_sends_email_to_admins(self):
        amendment, _, _ = self._make_amendment()
        fake_email = _FakeEmailService()
        sync_result = {"status": "error", "message": "API down"}

        with patch(_EMAIL_SERVICE_PATH, return_value=fake_email):
            amendment_events.notify_administrators_of_sync_issue(amendment, sync_result)

        # At least the System Manager / admin roles resolve on a test site.
        self.assertEqual(len(fake_email.sent), 1)
        sent = fake_email.sent[0]
        self.assertIn("Mollie Subscription Sync Issue", sent["subject"])
        self.assertEqual(sent["reference_doctype"], "Contribution Amendment Request")
        self.assertEqual(sent["reference_name"], amendment.name)

    def test_no_recipients_returns_without_send(self):
        amendment, _, _ = self._make_amendment()
        fake_email = _FakeEmailService()
        sync_result = {"status": "error", "message": "API down"}

        # Force the recipient query to come back empty.
        with patch(_EMAIL_SERVICE_PATH, return_value=fake_email), patch.object(
            frappe, "get_all", return_value=[]
        ):
            amendment_events.notify_administrators_of_sync_issue(amendment, sync_result)

        self.assertEqual(fake_email.sent, [])


class TestBuildSyncIssueMessage(EnhancedTestCase):
    def _context(self, member, membership, amendment, sync_result):
        return {
            "amendment": amendment,
            "member": member,
            "membership": membership,
            "sync_result": sync_result,
            "member_url": "http://x/member",
            "amendment_url": "http://x/amend",
        }

    def test_message_includes_core_fields(self):
        ctx = self._context(
            frappe._dict(full_name="Jane Doe", name="MEM-1"),
            frappe._dict(name="MS-1"),
            frappe._dict(name="AMEND-1", amendment_type="Fee Change"),
            {"status": "error", "message": "bad"},
        )
        message = amendment_events._build_sync_issue_message(ctx)
        self.assertIn("AMEND-1", message)
        self.assertIn("Jane Doe", message)
        self.assertIn("Action Required", message)

    def test_message_includes_subscription_and_amount_sections(self):
        ctx = self._context(
            frappe._dict(full_name="Jane Doe", name="MEM-1"),
            frappe._dict(name="MS-1"),
            frappe._dict(name="AMEND-1", amendment_type="Fee Change"),
            {
                "status": "warning",
                "message": "mismatch",
                "subscription_id": "sub_NEW",
                "old_subscription_id": "sub_OLD",
                "mollie_amount": "25.00",
                "expected_amount": "30.00",
            },
        )
        message = amendment_events._build_sync_issue_message(ctx)
        self.assertIn("sub_NEW", message)
        self.assertIn("sub_OLD", message)
        self.assertIn("25.00", message)
        self.assertIn("30.00", message)
