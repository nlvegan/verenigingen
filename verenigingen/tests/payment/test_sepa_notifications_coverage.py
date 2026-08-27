"""
SEPA Notifications Coverage Tests
=================================

NEW coverage-focused tests for
``verenigingen.verenigingen_payments.utils.sepa_notifications``.

These exercise genuinely-uncovered branches with REAL fixtures (Member,
SEPA Mandate, Communication, Comment) rather than mocks, complementing the
existing unit/integration suites:
  - verenigingen/tests/backend/components/test_sepa_notifications.py
  - verenigingen/tests/sepa/test_sepa_payment_notifications_integration.py

The single external seam patched here is the email DELIVERY boundary:
``verenigingen.services.communication.compatibility.send_sepa_email`` (a true
external send), and ``frappe.enqueue`` (an infra boundary). Everything else
runs for real so the assertions catch regressions in actual side effects.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.utils.sepa_notifications import (
    SEPAMandateNotificationManager,
    log_notification_comment,
    log_notification_comments_batch,
)

SEND_PATH = "verenigingen.services.communication.compatibility.send_sepa_email"


class TestSEPANotificationsCoverage(EnhancedTestCase):
    """Coverage for uncovered SEPA notification branches using real fixtures."""

    def setUp(self):
        super().setUp()
        self.manager = SEPAMandateNotificationManager()
        self.factory = SEPATestDataFactory(use_faker=True)

        # Member WITH an email
        self.member = self.create_test_member(
            first_name="Coverage",
            last_name="Tester",
            email="coverage.tester@test.invalid",
            birth_date="1985-03-03",
        )

        # Member WITHOUT an email (factory enforces a valid email, so clear it
        # at the DB level — the notification methods read email via direct SQL).
        self.member_no_email = self.create_test_member(
            first_name="NoEmail",
            last_name="Recipient",
            birth_date="1986-04-04",
        )
        frappe.db.set_value("Member", self.member_no_email.name, "email", "")

        self.mandate = self._make_mandate(self.member.name)

    # ---- factory helpers (insert allowed only in *prefixed* helpers) ----

    def _make_mandate(self, member_name, **kwargs):
        return self.factory.create_test_sepa_mandate(member=member_name, **kwargs)

    # ------------------------------------------------------------------
    # Missing-email early returns (cancelled / expiring branches uncovered)
    # ------------------------------------------------------------------

    def test_cancelled_notification_skips_member_without_email(self):
        mandate = self._make_mandate(self.member_no_email.name)
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_cancelled_notification(mandate, reason="Bank changed")
            mock_send.assert_not_called()

    def test_expiring_notification_skips_member_without_email(self):
        mandate = self._make_mandate(self.member_no_email.name)
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_expiring_notification(mandate, days_until_expiry=10)
            mock_send.assert_not_called()

    def test_created_notification_skips_member_without_email(self):
        mandate = self._make_mandate(self.member_no_email.name)
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_created_notification(mandate)
            mock_send.assert_not_called()

    def test_created_notification_returns_for_unknown_member(self):
        # Mandate referencing a member row that the SQL lookup won't find. Reuse the
        # mandate setUp already created: since #584 this member may not hold a second
        # Active memberships mandate, and the point here is the in-memory `member`
        # value the notification path reads, not a distinct row.
        mandate = self.mandate
        mandate.member = "MEMBER-DOES-NOT-EXIST-XYZ"
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_created_notification(mandate)
            mock_send.assert_not_called()

    # ------------------------------------------------------------------
    # Cancelled / expiring happy paths with REAL member (context assertions)
    # ------------------------------------------------------------------

    def test_cancelled_notification_builds_context_and_sends(self):
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_cancelled_notification(self.mandate, reason="Closing account")
            mock_send.assert_called_once()
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template"], "sepa_mandate_cancelled")
            self.assertIn("Cancelled", kwargs["subject"])
            self.assertEqual(kwargs["recipients"], [self.member.email])
            ctx = kwargs["context"]
            self.assertEqual(ctx["cancellation_reason"], "Closing account")
            self.assertEqual(ctx["mandate_id"], self.mandate.mandate_id)
            # IBAN masked, full account number never present
            self.assertNotIn(self.mandate.iban, ctx["iban"])
            self.assertIn("****", ctx["iban"])

    def test_cancelled_notification_default_reason(self):
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_cancelled_notification(self.mandate)
            ctx = mock_send.call_args[1]["context"]
            self.assertEqual(ctx["cancellation_reason"], "Cancelled by member request")

    def test_expiring_notification_builds_context_and_sends(self):
        self.mandate.expiry_date = add_days(today(), 12)
        with patch(SEND_PATH) as mock_send:
            self.manager.send_mandate_expiring_notification(self.mandate, days_until_expiry=12)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template"], "sepa_mandate_expiring")
            self.assertEqual(kwargs["context"]["days_until_expiry"], 12)
            self.assertIn("renewal_link", kwargs["context"])

    # ------------------------------------------------------------------
    # Exception-swallow branches: a failing send must NOT propagate
    # ------------------------------------------------------------------

    def test_created_notification_swallows_send_exception(self):
        with patch(SEND_PATH, side_effect=RuntimeError("smtp down")):
            # Must not raise — failure is logged and swallowed.
            self.manager.send_mandate_created_notification(self.mandate)

    def test_cancelled_notification_swallows_send_exception(self):
        with patch(SEND_PATH, side_effect=RuntimeError("smtp down")):
            self.manager.send_mandate_cancelled_notification(self.mandate, reason="x")

    def test_expiring_notification_swallows_send_exception(self):
        with patch(SEND_PATH, side_effect=RuntimeError("smtp down")):
            self.manager.send_mandate_expiring_notification(self.mandate, days_until_expiry=5)

    # ------------------------------------------------------------------
    # Bulk preload + per-type dispatch with REAL members
    # ------------------------------------------------------------------

    def test_load_member_data_bulk_returns_real_rows(self):
        data = self.manager._load_member_data_bulk([self.member.name, self.member_no_email.name])
        self.assertEqual(len(data), 2)
        self.assertEqual(data[self.member.name]["email"], self.member.email)
        self.assertEqual(data[self.member_no_email.name]["email"], "")

    def test_batch_dispatch_builds_one_email_per_valid_member(self):
        m2 = self.create_test_member(
            first_name="Second", last_name="Member", email="second.member@test.invalid",
            birth_date="1991-01-01",
        )
        mandate2 = self._make_mandate(m2.name)
        no_email_mandate = self._make_mandate(self.member_no_email.name)

        notifications = [
            {"mandate": self.mandate, "notification_type": "created", "extra_data": {}},
            {"mandate": mandate2, "notification_type": "cancelled", "extra_data": {"reason": "moved"}},
            {"mandate": no_email_mandate, "notification_type": "expiring",
             "extra_data": {"days_until_expiry": 9}},
            {"mandate": self.mandate, "notification_type": "unknown_type", "extra_data": {}},
        ]

        with patch.object(self.manager, "_send_email_batch") as mock_batch:
            self.manager.send_mandate_notifications_batch(notifications)
            mock_batch.assert_called_once()
            batch = mock_batch.call_args[0][0]
            # no_email member skipped + unknown type skipped => 2 emails
            self.assertEqual(len(batch), 2)
            templates = {e["template"] for e in batch}
            self.assertEqual(templates, {"sepa_mandate_created", "sepa_mandate_cancelled"})

    def test_batch_empty_input_is_noop(self):
        with patch.object(self.manager, "_send_email_batch") as mock_batch:
            self.manager.send_mandate_notifications_batch([])
            mock_batch.assert_not_called()

    # ------------------------------------------------------------------
    # _send_email_batch: real Communication insert + enqueue dispatch
    # ------------------------------------------------------------------

    def test_send_email_batch_creates_communication_and_enqueues(self):
        """REGRESSION GUARD for a fixed prod bug (sepa_notifications.py ~444).

        ``_send_email_batch`` built the Communication doc with
        ``"recipients": email_data["recipients"]`` where recipients is a LIST
        (assembled as ``[member_data["email"]]`` in send_mandate_notifications_batch
        line ~370). Frappe's Communication "To" field rejects a list with
        "Value for To cannot be a list", so secure_document_operation returned
        success=False, NO Communication was persisted, and the delivery email was
        never enqueued -- the except-branch swallowed + logged the failure, hiding
        it. The prod code now joins recipients into a comma-separated string before
        insert; this test asserts the Communication IS persisted and delivery IS
        enqueued, and fails if that join regresses.
        """
        before = frappe.db.count("Communication")
        email_batch = [
            {
                "recipients": [self.member.email],
                "subject": "SEPA Direct Debit Mandate Activated",
                "template": "sepa_mandate_created",
                "context": self.manager._prepare_created_context(
                    self.mandate,
                    {"name": self.member.name, "full_name": self.member.full_name,
                     "email": self.member.email},
                    self.manager._get_settings(),
                ),
                "member": self.member.name,
            }
        ]
        with (
            patch("frappe.enqueue") as mock_enqueue,
            patch(
                "frappe.core.doctype.communication.communication.Communication.send_email"
            ) as mock_send_email,
        ):
            self.manager._send_email_batch(email_batch)

        after = frappe.db.count("Communication")
        self.assertEqual(after, before + 1, "A Communication document should be persisted")

        comm = frappe.get_all(
            "Communication",
            filters={"reference_doctype": "Member", "reference_name": self.member.name,
                     "subject": "SEPA Direct Debit Mandate Activated"},
            fields=["name", "communication_type", "sent_or_received"],
            limit=1,
        )
        self.assertEqual(len(comm), 1)
        self.assertEqual(comm[0]["communication_type"], "Automated Message")
        self.assertEqual(comm[0]["sent_or_received"], "Sent")

        # Delivery is attempted on the persisted Communication.
        #
        # This previously asserted that
        # "frappe.core.doctype.communication.email.send_communication_email" was
        # enqueued. That function has never existed in any Frappe version, so the
        # worker died on AttributeError and no mail was ever sent -- the assertion
        # passed for its whole life while guarding nothing. Assert the real delivery
        # seam instead: Communication.send_email() (CommunicationEmailMixin), which
        # hands off to frappe.sendmail -> Email Queue.
        mock_send_email.assert_called_once()

        # Comment logging still goes through the queue.
        methods = [c.kwargs.get("method") for c in mock_enqueue.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen_payments.utils.sepa_notifications."
            "log_notification_comments_batch",
            methods,
        )

    def test_send_email_batch_uses_cached_template(self):
        # Prime the cache, then assert subsequent reads hit the cache (file read once).
        first = self.manager._get_template("sepa_mandate_created")
        self.assertIsNotNone(first, "Template file should be loaded into cache")
        self.assertIn("sepa_mandate_created", self.manager._template_cache)
        second = self.manager._get_template("sepa_mandate_created")
        self.assertIs(first, second)

    def test_get_template_missing_caches_none(self):
        result = self.manager._get_template("definitely_missing_template_xyz")
        self.assertIsNone(result)
        # Cached as None so a later render falls back to render_template path.
        self.assertIn("definitely_missing_template_xyz", self.manager._template_cache)
        self.assertIsNone(self.manager._template_cache["definitely_missing_template_xyz"])

    # ------------------------------------------------------------------
    # check_and_send_expiry_notifications: real query + 7-day dedup guard
    # ------------------------------------------------------------------

    def test_expiry_scheduler_sends_for_expiring_mandate(self):
        # setUp already gave this member their one Active mandate (#584); make that
        # one expire rather than adding a second.
        expiring = self.mandate
        frappe.db.set_value("SEPA Mandate", expiring.name, "expiry_date", add_days(today(), 20))

        with patch(SEND_PATH) as mock_send:
            self.manager.check_and_send_expiry_notifications()
            # At least our mandate's member should receive an expiring notice.
            sent_recipients = [c[1]["recipients"][0] for c in mock_send.call_args_list]
            self.assertIn(self.member.email, sent_recipients)

    def test_expiry_scheduler_respects_recent_notification_guard(self):
        # As above: reuse this member's single Active mandate (#584).
        expiring = self.mandate
        frappe.db.set_value("SEPA Mandate", expiring.name, "expiry_date", add_days(today(), 18))
        self._persist_recent_expiry_communication(expiring.name)

        with patch(SEND_PATH) as mock_send:
            self.manager.check_and_send_expiry_notifications()
            # The member already got an "Expiring Soon" Communication < 7 days ago,
            # so the dedup guard must suppress a fresh send for THIS mandate.
            for call in mock_send.call_args_list:
                self.assertNotEqual(
                    call[1]["recipients"], [self.member.email],
                    "Recent notification guard should suppress duplicate expiry email",
                )

    def _persist_recent_expiry_communication(self, mandate_name):
        comm = frappe.get_doc(
            {
                "doctype": "Communication",
                "subject": "SEPA Mandate Expiring Soon - Action Required",
                "content": "prior",
                "communication_type": "Automated Message",
                "reference_doctype": "SEPA Mandate",
                "reference_name": mandate_name,
                "sent_or_received": "Sent",
                "communication_medium": "Email",
            }
        )
        comm.insert(ignore_permissions=True)
        return comm

    # ------------------------------------------------------------------
    # log_notification_comment / log_notification_comments_batch
    # ------------------------------------------------------------------

    def test_log_notification_comment_creates_comment(self):
        before = frappe.db.count("Comment", {"reference_name": self.member.name})
        log_notification_comment(self.member.name, "SEPA Direct Debit Mandate Activated")
        after = frappe.db.count("Comment", {"reference_name": self.member.name})
        self.assertEqual(after, before + 1)

        comment = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Member", "reference_name": self.member.name,
                     "comment_type": "Info"},
            fields=["content"],
            order_by="creation desc",
            limit=1,
        )
        self.assertIn("Notification sent", comment[0]["content"])
        self.assertIn("Activated", comment[0]["content"])

    def test_log_notification_comment_skips_missing_member(self):
        before = frappe.db.count("Comment")
        log_notification_comment("MEMBER-NOPE-12345", "Some subject")
        after = frappe.db.count("Comment")
        self.assertEqual(after, before, "Missing member should be silently skipped")

    def test_log_notification_comments_batch_iterates(self):
        m2 = self.create_test_member(
            first_name="Batch", last_name="Comment", email="batch.comment@test.invalid",
            birth_date="1992-02-02",
        )
        before1 = frappe.db.count("Comment", {"reference_name": self.member.name})
        before2 = frappe.db.count("Comment", {"reference_name": m2.name})

        log_notification_comments_batch(
            [
                {"member": self.member.name, "subject": "Created"},
                {"member": m2.name, "subject": "Cancelled"},
                {"member": "MEMBER-NOPE-999", "subject": "Skipped"},
            ]
        )

        self.assertEqual(
            frappe.db.count("Comment", {"reference_name": self.member.name}), before1 + 1
        )
        self.assertEqual(frappe.db.count("Comment", {"reference_name": m2.name}), before2 + 1)

    def test_log_notification_comments_batch_handles_bad_input(self):
        # Malformed entry (missing "member"/"subject") must not raise — the outer
        # try/except swallows and logs.
        log_notification_comments_batch([{"wrong_key": "value"}])

    # ------------------------------------------------------------------
    # _get_bank_name exception fallback
    # ------------------------------------------------------------------

    def test_get_bank_name_returns_unknown_on_bad_iban(self):
        self.assertEqual(self.manager._get_bank_name(None), "Unknown Bank")
        self.assertEqual(self.manager._get_bank_name("GARBAGE"), "Unknown Bank")
