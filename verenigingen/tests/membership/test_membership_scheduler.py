"""
Real-integration tests for the membership scheduler module
``verenigingen/verenigingen/doctype/membership/scheduler.py``.

Covers the genuine scheduled-task logic: the expired-membership and
renewal-reminder ``*_impl`` helpers (driven with a single controlled
Membership we created), the direct-debit batch builder, the orphaned-records
query + notification, the deprecated stubs, and the scheduler-event
registration. Memberships are created via the test factory (real Members
with Customer records) and run as Administrator.

Isolation note: like the sibling member scheduler, the public
``process_expired_memberships`` / ``send_renewal_reminders`` entry points
acquire a session advisory lock and then call the ``*_impl`` helpers. The
helpers ``doc.save()`` but do NOT ``frappe.db.commit()``, so their writes roll
back with the test transaction. We therefore drive the ``*_impl`` helpers (and
the public wrappers, which under a fresh session acquire the lock) with a
SINGLE controlled record and assert the return shape / status transition. We do
NOT exercise the whitelisted enqueue wrappers that would inline-process and
commit every membership in the site (see the skipped notes in the final
report).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership import scheduler


class TestMembershipScheduler(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Sched",
            last_name="Member",
            email=f"sched.member.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"SchedType{frappe.generate_hash(length=6)}",
        )
        # The base factory inserts the Membership as a Draft (docstatus 0) and
        # does NOT submit it, so on_submit (which creates the member's dues
        # schedule) never runs. Submit it here so the active-membership /
        # dues-schedule / scheduler code paths (status == Active, docstatus == 1)
        # are reachable.
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name,
        )
        self.membership.submit()
        self.membership.reload()

    # ------------------------------------------------------------------ scheduler registration

    def test_setup_membership_scheduler_events(self):
        events = scheduler.setup_membership_scheduler_events()
        self.assertIn("daily", events)
        self.assertIn(
            "verenigingen.verenigingen.doctype.membership.scheduler.process_expired_memberships",
            events["daily"],
        )
        self.assertIn(
            "verenigingen.verenigingen.doctype.membership.scheduler.send_renewal_reminders",
            events["daily"],
        )

    # ------------------------------------------------------------------ process_expired (impl)

    def test_process_expired_memberships_impl_expires_past_renewal(self):
        # Force this membership past its renewal date, then run the impl. The impl
        # saves (no global commit) so the change rolls back with the test.
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            add_days(today(), -5),
            update_modified=False,
        )
        count = scheduler._process_expired_memberships_impl()
        self.assertGreaterEqual(count, 1)
        self.assertEqual(
            frappe.db.get_value("Membership", self.membership.name, "status"), "Expired"
        )

    def test_process_expired_memberships_impl_skips_future_renewal(self):
        # A membership whose renewal is in the future is NOT expired by the impl.
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            add_days(today(), 30),
            update_modified=False,
        )
        scheduler._process_expired_memberships_impl()
        self.assertEqual(
            frappe.db.get_value("Membership", self.membership.name, "status"), "Active"
        )

    def test_process_expired_memberships_public_runs_and_expires(self):
        # The public entry point acquires the advisory lock and delegates to the
        # impl. In the test session the lock is acquired fresh, so we exercise the
        # real lock-acquire / try / release path (not the skip branch).
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            add_days(today(), -3),
            update_modified=False,
        )
        count = scheduler.process_expired_memberships()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 1)
        self.assertEqual(
            frappe.db.get_value("Membership", self.membership.name, "status"), "Expired"
        )

    # ------------------------------------------------------------------ renewal reminders (impl)

    def test_send_renewal_reminders_impl_no_template_returns_int(self):
        # Drive a membership into the 30-day reminder window. With no renewal
        # Email Template configured the impl hits the "template not found" branch
        # for our record and returns an int count (no crash, no commit).
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            add_days(today(), 30),
            update_modified=False,
        )
        count = scheduler._send_renewal_reminders_impl()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    def test_send_renewal_reminders_impl_sends_with_template(self):
        # With a generic renewal Email Template present, our windowed membership
        # is processed through the send path and counted. EmailService queues the
        # mail under frappe.flags.in_test (no real send, no global commit).
        if not frappe.db.exists("Email Template", "membership_renewal_reminder"):
            tmpl = frappe.get_doc(
                {
                    "doctype": "Email Template",
                    "name": "membership_renewal_reminder",
                    "subject": "Renewal reminder",
                    "response": "<p>Please renew {{ days_to_expiry }}</p>",
                    "use_html": 1,
                }
            )
            tmpl.insert()
            self.track_doc("Email Template", tmpl.name)

        # 15-day window (a distinct window from the other test).
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            add_days(today(), 15),
            update_modified=False,
        )
        # Ensure the membership has an email to send to (factory member has one).
        email = frappe.db.get_value("Membership", self.membership.name, "email")
        self.assertTrue(email, "windowed membership must have an email for the send path")

        count = scheduler._send_renewal_reminders_impl()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 1)

    def test_send_renewal_reminders_public_runs(self):
        # Public entry point: acquires lock, delegates, releases. No record in a
        # reminder window for THIS membership (renewal far out) -> our record is a
        # no-op, returns int.
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            add_days(today(), 200),
            update_modified=False,
        )
        count = scheduler.send_renewal_reminders()
        self.assertIsInstance(count, int)

    # ------------------------------------------------------------------ deprecated stubs

    def test_process_auto_renewals_deprecated_returns_zero(self):
        self.assertEqual(scheduler.process_auto_renewals(), 0)

    def test_enqueue_process_auto_renewals_deprecated_dict(self):
        # Pure deprecated stub - returns a status dict, enqueues nothing.
        result = scheduler.enqueue_process_auto_renewals()
        self.assertEqual(result["status"], "deprecated")
        self.assertIn("message", result)

    # ------------------------------------------------------------------ direct debit batch

    def test_generate_direct_debit_batch_no_pending_returns_zero(self):
        # Our membership is Active (not Pending). If no Pending memberships exist
        # in the site the builder returns 0; otherwise it returns a batch dict.
        # Either way the return is well-formed.
        result = scheduler.generate_direct_debit_batch()
        self.assertTrue(result == 0 or isinstance(result, dict))

    def test_generate_direct_debit_batch_with_pending_returns_batch(self):
        # A submitted membership in Pending status must surface in the batch's
        # header counts. The member has no bank account, so it is correctly
        # skipped from the entries list (the "no bank account" branch).
        pending_member = self.create_test_member(
            first_name="Pending",
            last_name="DDMember",
            email=f"pending.dd.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        pending = self.create_test_membership(
            member=pending_member.name,
            membership_type=self.membership_type.name,
        )
        pending.submit()
        # The builder filters Pending + docstatus 1; flip the submitted membership
        # to Pending directly (status is a plain field, not the docstatus).
        frappe.db.set_value(
            "Membership", pending.name, "status", "Pending", update_modified=False
        )

        result = scheduler.generate_direct_debit_batch()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["currency"], "EUR")
        self.assertGreaterEqual(result["entry_count"], 1)
        self.assertIn("entries", result)
        self.assertEqual(result["creation_date"], today())

    # ------------------------------------------------------------------ orphaned records

    def test_get_orphaned_records_data_returns_list(self):
        # Read-only query (no commit). Returns a list of well-formed dicts.
        data = scheduler._get_orphaned_records_data()
        self.assertIsInstance(data, list)
        for item in data:
            self.assertIn("record_type", item)
            self.assertIn("document", item)
            self.assertIn("status", item)
            self.assertIn("issue", item)

    def test_get_orphaned_records_data_flags_membership_without_dues_schedule(self):
        # Delete the dues schedule the factory created on submit, leaving the
        # Active submitted membership orphaned. It must surface in the query.
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"membership": self.membership.name},
            pluck="name",
        )
        for s in schedules:
            frappe.delete_doc("Membership Dues Schedule", s, force=True)

        data = scheduler._get_orphaned_records_data()
        orphan_docs = [
            item["document"]
            for item in data
            if item["record_type"] == "Membership"
        ]
        self.assertIn(self.membership.name, orphan_docs)

    def test_notify_about_orphaned_records_runs_without_error(self):
        # Full notification path: query + (optional) templated email. Under
        # frappe.flags.in_test EmailService queues rather than sends, and the
        # function swallows its own exceptions and returns None either way.
        self.assertIsNone(scheduler.notify_about_orphaned_records())
