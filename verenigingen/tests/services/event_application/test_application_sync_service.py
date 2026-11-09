"""MijnRood applications are Membership Application Submissions, approved through approve_application (#1855).

Driven through real flows: MijnRood Sync Event rows applied by MijnRoodEventApplicationService.apply_event
(the New application event stages a record; the Approved event approves it), then the approval core's own
outputs are read back. Probe shortcuts, stated: the status mapping and dues templates are the site settings
this test seeds (restored on cleanup); the "approved locally first" and "rejected locally" tests move the
application with the real approve_application / reject_application endpoints, not a db write; the
"superseded" test uses the real confirm path of the full form.
"""

import json
from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.api.membership_application_review import approve_application, reject_application
from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.dispatcher import get_event_application_service
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase

SUBMISSION = "Membership Application Submission"


class MijnRoodApplicationCase(ApprovalCase):
    def setUp(self):
        super().setUp()
        self._row = 930000 + int(frappe.generate_hash(length=4), 16)
        self.division_id = self._row
        self.chapter.db_set("mijnrood_division_id", self.division_id)
        self.chapter.db_set("published", 1)
        annual = self._annual_template()
        self._set_setting("csv_annual_dues_schedule", annual)
        self._set_setting("default_membership_type", self.membership_type.name)
        self._set_mollie_free_settings()

    def _set_setting(self, fieldname, value):
        original = frappe.db.get_single_value("Verenigingen Settings", fieldname)
        frappe.db.set_single_value("Verenigingen Settings", fieldname, value)
        frappe.db.commit()
        self.addCleanup(self._restore_setting, fieldname, original)

    def _restore_setting(self, fieldname, original):
        frappe.db.set_single_value("Verenigingen Settings", fieldname, original)
        frappe.db.commit()

    def _set_mollie_free_settings(self):
        """Accounts are not under test: the setting that queues one per synced member stays off."""
        original = frappe.db.get_single_value("MijnRood Sync Settings", "create_member_accounts")
        frappe.db.set_single_value("MijnRood Sync Settings", "create_member_accounts", 0)
        frappe.db.commit()
        self.addCleanup(self._restore_accounts_setting, original)

    def _restore_accounts_setting(self, original):
        frappe.db.set_single_value("MijnRood Sync Settings", "create_member_accounts", original)
        frappe.db.commit()

    def _annual_template(self):
        schedule_name = f"Annual Template {self.membership_type.name}"
        existing = frappe.db.get_value("Membership Dues Schedule", {"schedule_name": schedule_name})
        if existing:
            return existing
        return (
            frappe.get_doc(
                {
                    "doctype": "Membership Dues Schedule",
                    "schedule_name": schedule_name,
                    "is_template": 1,
                    "membership_type": self.membership_type.name,
                    "status": "Active",
                    "billing_frequency": "Annual",
                    "dues_rate": 5.0,
                    "currency": "EUR",
                    "minimum_amount": 0,
                    "suggested_amount": 5.0,
                }
            )
            .insert()
            .name
        )

    # --- builders -------------------------------------------------------

    def _application_row(self, **overrides):
        self._row += 1
        row = {
            "id": self._row,
            "first_name": "Mijn",
            "last_name": "Rood",
            "email": self.email,
            "preferred_division_id": self.division_id,
            "iban": "NL91ABNA0417164300",
            "address": "Straat 1",
            "city": "Utrecht",
            "post_code": "3500AA",
            "country": "Netherlands",
            "date_of_birth": "1990-01-01",
            "registration_time": today(),
            "contribution_per_period_in_cents": 3000,  # above the type's 25.00 minimum
            "contribution_period": 2,
        }
        row.update(overrides)
        return row

    def _mijnrood_member_row(self, application, **overrides):
        self._row += 1
        row = dict(
            application,
            id=self._row,
            current_membership_status_id=1,
            division_id=self.division_id,
        )
        row.update(overrides)
        return row

    def _sync_event(self, event_type, table, new_data, old_data=None, changed_fields=None):
        self._row += 1
        event = frappe.get_doc(
            {
                "doctype": "MijnRood Sync Event",
                "mijnrood_table": table,
                "event_type": event_type,
                "mijnrood_row_id": self._row,
                "status": "Approved",
                "new_data": json.dumps(new_data),
                "old_data": json.dumps(old_data or {}),
                "changed_fields": json.dumps(changed_fields or []),
            }
        ).insert()
        frappe.db.commit()
        self.addCleanup(self._delete_event, event.name)
        return event.name

    def _delete_event(self, name):
        if frappe.db.exists("MijnRood Sync Event", name):
            frappe.delete_doc("MijnRood Sync Event", name, ignore_permissions=True, force=True)
        frappe.db.commit()

    def _apply_sync_event(self, event_name, user=None):
        # Mock justified: External Service - SMTP delivery, not business logic
        with patch("frappe.sendmail"):
            if user:
                with self.as_user(user):
                    return get_event_application_service().apply_event(event_name)
            return get_event_application_service().apply_event(event_name)

    def _stage(self, application=None, **overrides):
        application = application or self._application_row(**overrides)
        event = self._sync_event("New", "admin_membership_application", application)
        result = self._apply_sync_event(event)
        self.assertTrue(result["success"], result)
        name = frappe.db.get_value(SUBMISSION, {"application_id": f"MR-APP-{application['id']}"})
        self.assertTrue(name, "no application was staged")
        self.track_doc(SUBMISSION, name)
        return application, name

    def _approved_event(self, application, **overrides):
        return self._sync_event(
            "Approved", "admin_member", self._mijnrood_member_row(application, **overrides), old_data=application
        )

    def _members_of_email(self):
        return frappe.get_all("Member", {"email": self.email}, ["name", "status", "application_status"])


class TestStageApplication(MijnRoodApplicationCase):
    def test_new_application_event_stages_a_pending_review_record_and_no_member(self):
        application, name = self._stage()

        record = frappe.get_doc(SUBMISSION, name)
        self.assertEqual((record.status, record.source), ("Pending Review", "MijnRood"))
        self.assertEqual(record.application_id, f"MR-APP-{application['id']}")
        self.assertEqual(record.chapter, self.chapter.name)
        self.assertEqual(record.email, self.email)
        payload = json.loads(record.payload)
        self.assertEqual(payload["address_line1"], "Straat 1")
        self.assertEqual(payload["postal_code"], "3500AA")
        self.assertEqual(payload["custom_contribution_fee"], 30.0)
        self.assertEqual(self._members_of_email(), [], "staging an application must not create a Member")
        self.assertEqual(frappe.db.count("Address", {"email_id": self.email}), 0)

    def test_staging_the_same_application_twice_keeps_one_record(self):
        application, _name = self._stage()
        self._stage(application)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 1)

    def test_application_of_an_active_member_is_not_staged(self):
        member = self.create_test_member(email=self.email)
        # Probe shortcut: a Member's application_status defaults to "Pending" (a Select with no default),
        # which would let this application reapply; a real approved member reads "Approved".
        frappe.db.set_value("Member", member.name, "application_status", "Approved")
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Active")
        application = self._application_row()
        event = self._sync_event("New", "admin_membership_application", application)

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event, "linked_member"), member.name)

    def test_new_application_with_no_data_fails(self):
        event = frappe.get_doc(
            {
                "doctype": "MijnRood Sync Event",
                "mijnrood_table": "admin_membership_application",
                "event_type": "New",
                "mijnrood_row_id": 1,
                "status": "Approved",
            }
        )
        result = get_application_sync_service().apply_new_membership_application(event)
        self.assertFalse(result["success"])


class TestChangedApplication(MijnRoodApplicationCase):
    def test_changed_event_updates_the_pending_review_payload(self):
        application, name = self._stage()
        changed = dict(application, first_name="Veranderd", city="Zeist")

        event = self._sync_event(
            "Changed",
            "admin_membership_application",
            changed,
            changed_fields=[{"field": "first_name", "old": "Mijn", "new": "Veranderd"}],
        )
        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
        self.assertEqual((payload["first_name"], payload["city"]), ("Veranderd", "Zeist"))
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "applicant_name"), "Veranderd Rood")

    def test_changed_preferred_division_moves_the_application_chapter(self):
        other = self.factory.ensure_test_chapter(
            f"Other Chapter {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        other.db_set({"mijnrood_division_id": self.division_id + 1, "published": 1})
        application, name = self._stage()

        event = self._sync_event(
            "Changed",
            "admin_membership_application",
            dict(application, preferred_division_id=self.division_id + 1),
            changed_fields=[{"field": "preferred_division_id", "old": self.division_id, "new": self.division_id + 1}],
        )
        self.assertTrue(self._apply_sync_event(event)["success"])

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "chapter"), other.name)

    def test_changed_event_leaves_a_decided_application_alone(self):
        application, name = self._stage()
        self._approve_as(name)
        before = frappe.db.get_value(SUBMISSION, name, "payload")

        event = self._sync_event("Changed", "admin_membership_application", dict(application, first_name="Nee"))
        result = self._apply_sync_event(event)

        self.assertTrue(result["success"])
        self.assertIn("already Approved", result["message"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "payload"), before)

    def test_changed_event_for_an_unknown_application_fails(self):
        event = self._sync_event(
            "Changed", "admin_membership_application", self._application_row(email="nobody@example.org")
        )
        result = self._apply_sync_event(event)
        self.assertFalse(result["success"])
        self.assertIn("No application found", result["message"])


class TestFindApplication(MijnRoodApplicationCase):
    def test_found_by_application_id_then_by_email_of_a_mijnrood_application_only(self):
        application, name = self._stage()
        service = get_application_sync_service()

        self.assertEqual(service._find_application({"id": application["id"]}, {}, {"email": "x@y.nl"}), name)
        self.assertEqual(service._find_application({}, {}, {"email": self.email.upper()}), name)
        self.assertIsNone(service._find_application({"id": 1}, {}, {"email": "nobody@example.org"}))

    def test_email_fallback_ignores_a_web_form_application(self):
        web_form = self._stage_and_confirm()  # full form, same email
        self.assertEqual(frappe.db.get_value(SUBMISSION, web_form, "source"), "Full Form")
        self.assertIsNone(get_application_sync_service()._find_application({}, {}, {"email": self.email}))


    def test_email_fallback_skips_decided_mijnrood_applications(self):
        """Control: both decided states, each a real MijnRood row of the same email, are skipped."""
        from verenigingen.services.member.application.application_record import record_external_application

        payload = {"first_name": "Mijn", "last_name": "Rood", "email": self.email}
        superseded = record_external_application("MijnRood", self.email, payload, f"MR-APP-{self._row + 1}")
        rejected = record_external_application("MijnRood", self.email, payload, f"MR-APP-{self._row + 2}")
        self.track_doc(SUBMISSION, superseded)
        self.track_doc(SUBMISSION, rejected)
        frappe.get_doc(SUBMISSION, rejected).set_status("Rejected")
        self.assertEqual(frappe.db.get_value(SUBMISSION, superseded, "status"), "Superseded")
        self.assertEqual(frappe.db.get_value(SUBMISSION, rejected, "status"), "Rejected")

        self.assertIsNone(get_application_sync_service()._find_application({}, {}, {"email": self.email}))


class TestStagingEntryPoints(MijnRoodApplicationCase):
    def test_a_board_member_is_refused_at_every_real_entry_point_and_nothing_is_staged(self):
        """Least-privileged caller. Staging runs as the system, so the gate is the entry point: a board
        member (no read on MijnRood Sync Event, not admin) cannot apply a New application event."""
        from frappe.handler import run_doc_method

        from verenigingen.mijnrood_sync.services.event_application import dispatcher

        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        event = self._sync_event("New", "admin_membership_application", self._application_row())
        calls = (
            lambda: run_doc_method(method="apply_event", dt="MijnRood Sync Event", dn=event),
            lambda: run_doc_method(method="approve_and_apply", dt="MijnRood Sync Event", dn=event),
            lambda: dispatcher.batch_apply([event]),
            lambda: dispatcher.batch_approve_and_apply([event]),
        )
        for call in calls:
            with self.as_user(board.user), self.assertRaises(frappe.PermissionError):
                call()

        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)


class TestPromotion(MijnRoodApplicationCase):
    def test_approved_event_approves_through_the_approval_core(self):
        application, name = self._stage()
        event = self._approved_event(application)

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event, "status"), "Applied")
        record = frappe.get_doc(SUBMISSION, name)
        self.assertEqual(record.status, "Approved")
        (member_row,) = self._members_of_email()
        self.assertEqual(record.member, member_row.name)
        member = frappe.get_doc("Member", member_row.name)
        self.assertEqual((member.status, member.application_status), ("Active", "Approved"))
        # what only the approval core records: who approved, and when
        self.assertEqual(member.reviewed_by, frappe.session.user)
        self.assertEqual(record.reviewed_by, frappe.session.user)
        self.assertTrue(member.review_date)
        # MijnRood's own data is laid over the approved Member
        new_id = json.loads(frappe.db.get_value("MijnRood Sync Event", event, "new_data"))["id"]
        self.assertEqual(str(member.member_id), str(new_id))
        self.assertEqual(member.iban.replace(" ", ""), "NL91ABNA0417164300")

    def test_promotion_builds_membership_dues_chapter_and_first_invoice(self):
        application, name = self._stage()
        self.assertTrue(self._apply_sync_event(self._approved_event(application))["success"])

        member = frappe.db.get_value("Member", {"email": self.email}, ["name", "customer"], as_dict=True)
        self.assertTrue(
            frappe.db.exists("Membership", {"member": member.name, "status": "Active", "docstatus": 1})
        )
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0},
            ["billing_frequency", "dues_rate"],
        )
        # MijnRood reported 30.00 per year (cents 3000, period 2): the schedule keeps that choice
        self.assertEqual([(s.billing_frequency, s.dues_rate) for s in schedules], [("Annual", 30.0)])
        chapter_rows = frappe.db.sql(
            "select status, enabled from `tabChapter Member` where parent=%s and member=%s",
            (self.chapter.name, member.name),
            as_dict=True,
        )
        self.assertEqual([(r.status, r.enabled) for r in chapter_rows], [("Active", 1)])
        # maintainer ruling (#1855, 2026-11-02): approval creates the first invoice, as a web-form approval does
        self.assertEqual(frappe.db.count("Sales Invoice", {"customer": member.customer, "docstatus": 1}), 1)
        self.assertEqual(frappe.db.count("Address", {"email_id": self.email}), 1)

    def test_approved_locally_first_then_event_only_syncs(self):
        application, name = self._stage()
        self._approve_as(name)
        (member_row,) = self._members_of_email()
        event = self._approved_event(application)

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual([m.name for m in self._members_of_email()], [member_row.name])
        new_id = json.loads(frappe.db.get_value("MijnRood Sync Event", event, "new_data"))["id"]
        self.assertEqual(str(frappe.db.get_value("Member", member_row.name, "member_id")), str(new_id))

    def test_rejected_locally_is_not_resurrected(self):
        application, name = self._stage()
        self._reject_as(name)
        event = self._approved_event(application)

        result = self._apply_sync_event(event)

        self.assertFalse(result["success"])
        self.assertIn("resolve it manually", result["message"])
        self.assertEqual(self._members_of_email(), [])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Rejected")
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event, "status"), "Approved")

    def test_superseded_by_a_web_form_application_is_not_approved(self):
        application, name = self._stage()
        self._stage_and_confirm()  # confirming supersedes the MijnRood one
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Superseded")

        result = self._apply_sync_event(self._approved_event(application))

        self.assertFalse(result["success"])
        self.assertEqual(self._members_of_email(), [])

    def test_a_status_that_is_not_active_approves_nothing(self):
        application, name = self._stage()
        result = self._apply_sync_event(self._approved_event(application, current_membership_status_id=3))

        self.assertFalse(result["success"], result)
        self.assertIn("not an active status", result["message"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertEqual(self._members_of_email(), [])

    def test_unseen_application_falls_through_to_a_plain_member(self):
        application = self._application_row()
        result = self._apply_sync_event(self._approved_event(application))

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        self.assertEqual(len(self._members_of_email()), 1)

    def test_a_chapter_board_member_of_another_chapter_cannot_promote(self):
        """Least-privileged caller: the approval's chapter scope applies to whoever applies the event."""
        other = self.factory.ensure_test_chapter(
            f"Foreign Chapter {frappe.generate_hash(length=6)}", {"short_name": "FOR", "country": "Netherlands"}
        )
        board = self.create_test_board_member(other.name, permissions_level="Admin")
        application, name = self._stage()
        event = self._approved_event(application)

        result = self._apply_sync_event(event, user=board.user)

        self.assertFalse(result["success"], result)
        self.assertIn("permission", result["message"].lower())
        self.assertEqual(self._members_of_email(), [])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")


class TestApplyTimeSafetyNet(MijnRoodApplicationCase):
    def test_new_member_row_promotes_the_pending_mijnrood_application(self):
        application, name = self._stage()
        event = self._sync_event("New", "admin_member", self._mijnrood_member_row(application))

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Approved")
        self.assertEqual(len(self._members_of_email()), 1)

    def test_new_member_row_does_not_touch_a_web_form_application(self):
        web_form = self._stage_and_confirm()
        application = self._application_row()
        event = self._sync_event("New", "admin_member", self._mijnrood_member_row(application))

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, web_form, "status"), "Pending Review")
        self.assertEqual(len(self._members_of_email()), 1)


ALERT_KEY = "mijnrood_disabled_default_type"


class TestDisabledDefaultMembershipType(MijnRoodApplicationCase):
    """#2094: the type MijnRood applications get is the site's default; when it is disabled the application
    is still staged (maintainer ruling) and staff are told once, so a reviewer can pick a valid type.

    Real flows throughout: the type is disabled through its own save, the New event is applied by the real
    service, the alert is the real notify_administrators and is read back from Staff Alert Event rows
    (MyISAM: they survive rollback, so every test removes its own in cleanup). Only SMTP is stubbed.
    """

    def setUp(self):
        super().setUp()
        from verenigingen.mijnrood_sync.services.event_application import application_sync_service as svc

        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
        from verenigingen.tests.test_notification_registry_seed_1959 import _rows

        # A site installed before the key existed has no row until migrate seeds it (#2037); seed the way
        # migrate does and put the Single's rows back exactly as they were (singleton_backup skips child
        # tables, #2029).
        self._baseline_rows = [dict(r.as_dict()) for r in _rows().values()]
        self.addCleanup(self._put_back_rows)
        ensure_notification_registry_rows()
        self._alert_claim = svc.disabled_type_alert_claim_key(self.membership_type.name)
        frappe.cache.delete(self._alert_claim)
        self.addCleanup(frappe.cache.delete, self._alert_claim)
        self.addCleanup(self._delete_alert_events)

    def _put_back_rows(self):
        config = frappe.get_single("Verenigingen Email Configuration")
        config.notification_types = []
        for row in self._baseline_rows:
            config.append(
                "notification_types",
                {k: v for k, v in row.items() if k not in ("name", "creation", "modified", "idx")},
            )
        config.save()

    def _delete_alert_events(self):
        # MyISAM: the delete is not transactional, so it needs no commit
        frappe.db.delete("Staff Alert Event", {"notification_key": ALERT_KEY})

    def _disable(self, membership_type):
        doc = frappe.get_doc("Membership Type", membership_type.name)
        doc.is_active = 0
        doc.save()
        self.assertEqual(frappe.db.get_value("Membership Type", membership_type.name, "is_active"), 0)

    def _alerts(self):
        return frappe.get_all(
            "Staff Alert Event",
            {"notification_key": ALERT_KEY},
            ["name", "subject", "outcome", "recipient_count", "requires_action"],
        )

    def test_disabled_default_type_is_staged_with_that_type_and_one_alert(self):
        self._disable(self.membership_type)

        _application, name = self._stage()

        record = frappe.get_doc(SUBMISSION, name)
        self.assertEqual(record.status, "Pending Review")
        self.assertEqual(record.membership_type, self.membership_type.name)
        (alert,) = self._alerts()
        self.assertIn(self.membership_type.name, alert.subject)
        self.assertEqual(alert.outcome, "Delivered", alert)
        self.assertEqual(alert.requires_action, 1)

    def test_a_second_applicant_within_the_window_raises_no_second_alert(self):
        self._disable(self.membership_type)
        self._stage()
        other = self._application_row(email=self._fresh_applicant_email())

        _application, second = self._stage(other)

        self.assertEqual(frappe.db.get_value(SUBMISSION, second, "status"), "Pending Review")
        self.assertEqual(len(self._alerts()), 1)

    def test_an_active_default_type_is_staged_with_no_alert(self):
        _application, name = self._stage()

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "membership_type"), self.membership_type.name)
        self.assertEqual(self._alerts(), [])

    def test_a_changed_event_that_lands_on_a_disabled_default_type_alerts_too(self):
        application, name = self._stage()
        self.assertEqual(self._alerts(), [])
        self._disable(self.membership_type)
        event = self._sync_event("Changed", "admin_membership_application", dict(application, city="Zeist"))

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual(len(self._alerts()), 1)

    def test_a_blank_default_type_is_not_reported_as_disabled(self):
        self._set_setting("default_membership_type", None)

        self._stage()

        self.assertEqual(self._alerts(), [])

    def test_a_board_member_can_approve_the_staged_application_into_another_valid_type(self):
        """Least-privileged real caller; the staged row's own type is the disabled one."""
        other_type = self.factory.ensure_membership_type(
            f"Approval Type B {frappe.generate_hash(length=6)}", {"amount": 25.00, "billing_period": "Monthly"}
        )
        other_type.get_or_create_membership_item()
        self._disable(self.membership_type)
        _application, name = self._stage()
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

        result = self._approve_as(name, user=board.user, membership_type=other_type.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Approved")
        (member,) = self._members_of_email()
        self.assertEqual(member.status, "Active")

    def _set_key_enabled(self, enabled):
        config = frappe.get_single("Verenigingen Email Configuration")
        (row,) = [r for r in config.notification_types if r.notification_key == ALERT_KEY]
        row.enabled = enabled
        config.save()

    def test_an_alert_that_reaches_nobody_releases_the_claim_so_the_next_application_alerts(self):
        self._disable(self.membership_type)
        self._set_key_enabled(0)  # real outcome: notify_administrators skips a disabled key
        self._stage()
        self.assertFalse(frappe.cache.get(self._alert_claim), "an undelivered alert must not hold the claim")
        self.assertFalse([a for a in self._alerts() if a.outcome == "Delivered"])
        self._set_key_enabled(1)

        self._stage(self._application_row(email=self._fresh_applicant_email()))

        self.assertEqual([a.outcome for a in self._alerts() if a.outcome == "Delivered"], ["Delivered"])
        self.assertTrue(frappe.cache.get(self._alert_claim), "control: the delivered alert holds the claim")

    def test_a_failing_alert_keeps_the_staging_releases_the_claim_and_logs(self):
        from verenigingen.mijnrood_sync.services.event_application import application_sync_service as svc

        self._disable(self.membership_type)
        self.addCleanup(frappe.db.delete, "Error Log", {"method": "MijnRood disabled-type alert failed"})
        # Mock justified: forces the delivery step itself to fail; the staging and claim are real
        with patch.object(svc, "_send_disabled_type_alert", side_effect=RuntimeError("boom 2094")):
            _application, name = self._stage()

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertFalse(frappe.cache.get(self._alert_claim))
        logged = frappe.get_all(
            "Error Log", {"method": "MijnRood disabled-type alert failed"}, ["error"], limit=5
        )
        self.assertTrue(any("boom 2094" in row.error for row in logged), logged)

    def test_a_redis_error_while_releasing_the_claim_does_not_undo_the_staging(self):
        from verenigingen.mijnrood_sync.services.event_application import application_sync_service as svc

        self._disable(self.membership_type)
        self.addCleanup(frappe.db.delete, "Error Log", {"method": "MijnRood disabled-type alert claim not released"})
        # Mock justified: forces the cache and the delivery step to fail; staging is real
        with patch.object(svc, "_send_disabled_type_alert", side_effect=RuntimeError("boom")), patch.object(
            frappe.cache, "delete", side_effect=ConnectionError("redis down")
        ):
            result = self._apply_sync_event(
                self._sync_event("New", "admin_membership_application", self._application_row())
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email, "status": "Pending Review"}), 1)
