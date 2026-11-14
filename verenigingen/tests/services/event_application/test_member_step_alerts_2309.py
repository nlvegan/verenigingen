"""#2309 part 2: a PER-MEMBER MijnRood sync step that fails must tell staff, once a day per member+step+reason.

The event is consumed (still Applied) with only a message string, and MijnRood does not resend. Two keys:
``mijnrood_sync_step_failed`` (admin pair) and ``mijnrood_sync_money_step_failed`` (admin pair plus
Verenigingen Financial Manager) for Mollie / membership / dues. Alerts are queued during the event and sent
AFTER its commit (#2199's queue, generalised in part 1); "No Volunteer record" cascades are not alerted (the two
class F tests pin what that does and does not cover).

Real flows: real admin_member Changed events applied by the real dispatcher, the real notify_administrators,
read back from Notification Log and Staff Alert Event. Probe shortcuts, stated:
* the failure of each step is injected at the service boundary the step calls (address / Mollie / membership /
  dues / volunteer / role / board / team service) because the real causes (a broken Mollie customer, a
  Chapter validation error) are not reproducible on demand; the alert path itself is real;
* the role mapping is supplied by patching ``get_role_mapping`` where the volunteer service reads it;
* ``Member.status`` / ``Member.user`` are set directly, standing in for earlier sync steps not under test.
Only SMTP is stubbed.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync.services.event_application import volunteer_sync_service
from verenigingen.mijnrood_sync.services.event_application.dispatcher import (
    MijnRoodEventApplicationService as EventApplicationService,
    get_event_application_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application import test_config_fault_alerts_2309 as part1
from verenigingen.tests.services.event_application.test_config_fault_alerts_2309 import (
    _unused_division_id,
)

MEMBER_KEY = "mijnrood_sync_step_failed"
MONEY_KEY = "mijnrood_sync_money_step_failed"
KEYS = (MEMBER_KEY, MONEY_KEY)
SUBJECT = "MijnRood sync: %"
ROLE_ADMIN = "ROLE_ADMIN"
ROLE_DIVISION_CONTACT = "ROLE_DIVISION_CONTACT"

ADDRESS_SVC = "verenigingen.services.csv_import.address_import_service.AddressImportService"
MOLLIE_SVC = "verenigingen.services.csv_import.mollie_sync_service.MollieSyncService"
MEMBERSHIP_SVC = "verenigingen.services.csv_import.membership_import_service.MembershipImportService"
CREATE_VOLUNTEER = "verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member"


class TestMemberStepAlerts2309(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
        from verenigingen.tests.test_notification_registry_seed_1959 import _rows

        self._baseline_rows = [dict(r.as_dict()) for r in _rows().values()]
        self.addCleanup(self._restore_registry_rows)
        ensure_notification_registry_rows()
        self.addCleanup(self._purge)
        self._purge()

        suffix = frappe.generate_hash(length=6)
        self.member = self.create_test_member(first_name="Step", last_name=f"Fault{suffix}")
        self.admin_user = self.create_test_user_with_roles(
            email=f"stp2309.admin.{suffix}@example.com", roles=["Verenigingen Administrator"]
        ).name
        self.finance_user = self.create_test_user_with_roles(
            email=f"stp2309.fin.{suffix}@example.com", roles=["Verenigingen Financial Manager"]
        ).name
        self.bystander = self.create_test_user_with_roles(
            email=f"stp2309.other.{suffix}@example.com", roles=["Verenigingen Member"]
        ).name

    # ---- scaffolding --------------------------------------------------------------------------------
    def _purge(self):
        frappe.db.delete("Staff Alert Event", {"notification_key": ["in", KEYS]})
        frappe.db.delete("Notification Log", {"subject": ["like", SUBJECT]})
        for key in KEYS:
            for claim in frappe.cache.get_keys(f"*{key}*"):
                frappe.cache.delete(claim.decode() if isinstance(claim, bytes) else claim)

    def _subject(self, label, member=None):
        return f"MijnRood sync: {label} failed for {(member or self.member).name}"

    # The scaffolding is part 1's, shared rather than copied (the duplicate-helper gate counts copies).
    _restore_registry_rows = part1.TestConfigFaultAlerts2309._restore_registry_rows
    _sent = part1.TestConfigFaultAlerts2309._sent
    _recipients = part1.TestConfigFaultAlerts2309._recipients
    _alert_events = part1.TestConfigFaultAlerts2309._alert_events
    _apply = part1.TestConfigFaultAlerts2309._apply
    _purge_event = part1.TestConfigFaultAlerts2309._purge_event
    _member_fields = part1.TestConfigFaultAlerts2309._member_fields
    _apply_once_and_roll_back = part1.TestConfigFaultAlerts2309._apply_once_and_roll_back

    def _assert_applied(self, result):
        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", self.last_event_name, "status"), "Applied")

    # ---- member-event steps -------------------------------------------------------------------------
    def _address_event(self, member=None):
        return self._apply(
            new_data={**self._member_fields(), "address": "Teststraat 1", "city": "Zzcity2309"}, member=member
        )

    def _mollie_event(self, member=None):
        return self._apply(
            new_data={**self._member_fields(), "mollie_customer_id": "cst_2309", "mollie_subscription_id": "sub_2309"},
            member=member,
        )

    def _address_fault(self, text="addr-boom-2309"):
        # Mock justified: fault injection at the address service the step calls
        return patch(f"{ADDRESS_SVC}.create_or_update_address", side_effect=RuntimeError(text))

    def _mollie_fault(self, text="mollie-boom-2309"):
        # Mock justified: fault injection at the Mollie sync service the step calls
        return patch(f"{MOLLIE_SVC}.sync_mollie_data", side_effect=RuntimeError(text))

    def _failing_address(self, member=None, text="addr-boom-2309"):
        self.expectErrorLog("MijnRood Sync - Address Creation Failed")
        with self._address_fault(text):
            return self._address_event(member)

    def _failing_mollie(self, member=None, text="mollie-boom-2309"):
        self.expectErrorLog("MijnRood Sync - Mollie Sync Failed")
        with self._mollie_fault(text):
            return self._mollie_event(member)

    def test_a_failed_address_step_applies_the_event_and_alerts_the_admin_pair_once(self):
        result = self._failing_address()

        self._assert_applied(result)
        self.assertIn("Address creation failed", result["message"])
        subject = self._subject("address creation")
        self.assertEqual(self._sent(subject), len(self._recipients(subject)))
        (alert,) = self._alert_events(MEMBER_KEY)
        self.assertEqual((alert.outcome, alert.requires_action), ("Delivered", 1))
        body = frappe.db.get_value("Notification Log", {"subject": subject}, "email_content")
        self.assertIn("addr-boom-2309", body)
        self.assertIn(self.member.name, body)
        recipients = self._recipients(subject)
        self.assertIn(self.admin_user, recipients)
        self.assertNotIn("Administrator", recipients)
        self.assertNotIn(self.bystander, recipients)
        self.assertNotIn(self.finance_user, recipients, "a non-money step is for the admin pair only")
        self.assertEqual(self._alert_events(MONEY_KEY), [])

    def test_a_failed_money_step_reaches_a_financial_manager_too(self):
        result = self._failing_mollie()

        self._assert_applied(result)
        subject = self._subject("Mollie sync")
        recipients = self._recipients(subject)
        self.assertIn(self.admin_user, recipients)
        self.assertIn(self.finance_user, recipients, "money steps also go to Verenigingen Financial Manager")
        self.assertNotIn(self.bystander, recipients)
        self.assertNotIn("Administrator", recipients)
        (alert,) = self._alert_events(MONEY_KEY)
        self.assertEqual((alert.outcome, alert.requires_action), ("Delivered", 1))
        self.assertEqual(self._alert_events(MEMBER_KEY), [], "money steps use their own key")

    def test_the_same_member_step_and_reason_the_same_day_does_not_alert_again(self):
        self._failing_address()
        subject = self._subject("address creation")
        first = self._sent(subject)
        self.assertGreater(first, 0, "control: the first event must have alerted")

        self._failing_address()

        self.assertEqual(self._sent(subject), first)

    def test_the_same_step_failing_for_another_member_alerts_again(self):
        self._failing_address()
        other = self.create_test_member(first_name="Other", last_name=f"Step{frappe.generate_hash(length=6)}")
        self.member = other  # _member_fields now names the other member

        self._failing_address(member=other)

        self.assertGreater(self._sent(self._subject("address creation", other)), 0)

    def test_another_step_of_the_same_member_alerts_again(self):
        """Address and volunteer are both on the member key, same member, same reason text: only the step
        tells the two claims apart."""
        self._failing_address(text="same-reason-2309")
        self.expectErrorLog("MijnRood Sync - Volunteer Creation Failed")
        # Mock justified: fault injection at the volunteer creation the step calls
        with patch(CREATE_VOLUNTEER, side_effect=RuntimeError("same-reason-2309")):
            self._admin_role_event(create_volunteer=True)

        self.assertGreater(self._sent(self._subject("address creation")), 0)
        self.assertGreater(self._sent(self._subject("volunteer creation")), 0)

    def test_the_same_step_for_another_reason_alerts_again(self):
        self._failing_address(text="reason-one-2309")
        first = self._sent(self._subject("address creation"))

        self._failing_address(text="reason-two-2309")

        self.assertGreater(self._sent(self._subject("address creation")), first)

    def test_a_working_step_raises_no_alert(self):
        """Control: no fault injected, no alert (the mollie service accepts the ids)."""
        self.expectErrorLog("MijnRood Sync")
        result = self._apply(new_data=self._member_fields())

        self._assert_applied(result)
        self.assertEqual(self._sent(SUBJECT), 0)

    def test_a_claim_is_released_when_nothing_was_delivered(self):
        with patch(
            "verenigingen.utils.notification_helpers.notify_administrators",
            return_value={"success": True, "notifications_created": 0},
        ):
            self._failing_address()
        self.assertEqual(self._sent(self._subject("address creation")), 0, "control: nobody was reached")

        self._failing_address()

        self.assertGreater(self._sent(self._subject("address creation")), 0)

    def test_a_raising_alert_does_not_fail_the_event(self):
        self.expectErrorLog("MijnRood step-failure alert failed")
        with patch(
            "verenigingen.utils.notification_helpers.notify_administrators", side_effect=RuntimeError("x-2309")
        ):
            result = self._failing_address()

        self._assert_applied(result)

    # ---- after-commit: not sent inside an event that may roll back -----------------------------------
    def test_a_step_alert_survives_only_a_committed_event_and_a_rolled_back_one_re_alerts(self):
        """The address step fails, then the event itself raises (its first save) and rolls back. Sending the
        alert inline would take a claim the rollback cannot undo and the re-apply would stay silent."""
        from verenigingen.mijnrood_sync.doctype.mijnrood_sync_event.mijnrood_sync_event import (
            MijnRoodSyncEvent,
        )

        # Mock justified: fault injection. The address step has run before the event is saved.
        later = patch.object(MijnRoodSyncEvent, "save", side_effect=[RuntimeError("boom-2309")] + [None] * 5)
        self.expectErrorLog("MijnRood Sync - Address Creation Failed")
        # Mock justified: the real member update commits on its own, which would destroy the emulated
        # rollback's savepoint; the step under test is the address step that follows it.
        member_update = patch(
            "verenigingen.services.csv_import.member_import_service.MemberImportService.create_or_update_member",
            return_value=("updated", self.member.name),
        )
        with self._address_fault(), member_update:
            first = self._apply_once_and_roll_back(self._address_event, later)
            self.assertFalse(first["success"], first)
            subject = self._subject("address creation")
            self.assertEqual(self._sent(subject), 0, "control: the rollback took the first attempt")

            second = self._address_event()

        self._assert_applied(second)
        self.assertGreater(self._sent(subject), 0, "the re-apply must alert: no stale claim")

    def test_the_alert_is_still_sent_when_the_member_update_returns_failure_after_the_step(self):
        """A later failed (returned, not raised) step in the same event does not take back the alert."""
        self.expectErrorLog("MijnRood Sync - Address Creation Failed")
        # Mock justified: fault injection after the address step: the notes step returns a failure message
        # path is irrelevant; what matters is the event outcome does not discard the queued alert.
        with self._address_fault(), patch.object(
            EventApplicationService, "_record_event_failure"
        ), patch(
            "verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator."
            "MijnRoodRelatedRecordsOrchestrator._apply_mijnrood_comments",
            return_value="note step ran",
        ):
            result = self._address_event()

        self._assert_applied(result)
        self.assertGreater(self._sent(self._subject("address creation")), 0)

    # ---- the other member / money steps ---------------------------------------------------------------
    def _member_with_membership_in_schedule_state(self, with_schedule):
        frappe.db.set_value("Member", self.member.name, "status", "Active", update_modified=False)
        membership_type = self.create_test_membership_type()
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": membership_type.name,
                "start_date": frappe.utils.today(),
                "status": "Active",
            }
        ).insert()
        if not with_schedule:
            membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        has = bool(frappe.db.exists("Membership Dues Schedule", {"member": self.member.name, "is_template": 0}))
        self.assertEqual(has, with_schedule, "control: the fixture must leave the schedule state asked for")
        return membership

    def _dues_event_at_rate(self, rate_cents=1250):
        return self._apply(
            new_data={
                **self._member_fields(),
                "contribution_per_period_in_cents": rate_cents,
                "contribution_period": 0,
            }
        )

    def test_a_failed_membership_creation_alerts_on_the_money_key(self):
        frappe.db.set_value("Member", self.member.name, "status", "Active", update_modified=False)
        self.expectErrorLog("MijnRood Sync - Membership Creation Failed")
        # Mock justified: fault injection at the membership import service the step calls
        with patch(f"{MEMBERSHIP_SVC}.create_membership_from_csv", side_effect=RuntimeError("mship-boom-2309")):
            result = self._dues_event_at_rate()

        self._assert_applied(result)
        self.assertIn("Membership creation failed", result["message"])
        subject = self._subject("membership creation")
        self.assertIn(self.finance_user, self._recipients(subject))
        self.assertEqual(len(self._alert_events(MONEY_KEY)), 1)

    def test_a_failed_dues_backfill_alerts_on_the_money_key(self):
        self._member_with_membership_in_schedule_state(with_schedule=False)
        self.expectErrorLog("MijnRood Sync - Dues Schedule Backfill Failed")
        # Mock justified: fault injection. The template resolves; creating the schedule from it raises.
        with patch(
            "verenigingen.utils.csv.data_transformers.get_dues_schedule_template_from_payment_period",
            return_value="Some Template 2309",
        ), patch(
            "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule."
            "MembershipDuesSchedule.create_from_template",
            side_effect=RuntimeError("backfill-boom-2309"),
        ):
            result = self._dues_event_at_rate()

        self._assert_applied(result)
        self.assertIn("Dues schedule backfill failed", result["message"])
        self.assertIn(self.finance_user, self._recipients(self._subject("dues schedule backfill")))

    def test_a_failed_dues_rate_update_alerts_on_the_money_key(self):
        self._member_with_membership_in_schedule_state(with_schedule=True)
        self.expectErrorLog("MijnRood Sync - Dues Schedule Update Failed")
        failed = SimpleNamespace(
            success=False, message="rate-boom-2309", errors=["rate-boom-2309"], method_used="none"
        )
        # Mock justified: fault injection at the repository the step calls
        with patch(
            "verenigingen.repositories.dues_schedule_repository.DuesScheduleRepository.update_schedule_rate",
            return_value=failed,
        ):
            result = self._dues_event_at_rate(rate_cents=9900)

        self._assert_applied(result)
        self.assertIn("Dues schedule update failed", result["message"])
        self.assertIn(self.finance_user, self._recipients(self._subject("dues schedule rate update")))

    def _enable_account_creation(self):
        original = frappe.db.get_single_value("MijnRood Sync Settings", "create_member_accounts")
        frappe.db.set_single_value("MijnRood Sync Settings", "create_member_accounts", 1)
        self.addCleanup(
            frappe.db.set_single_value, "MijnRood Sync Settings", "create_member_accounts", original or 0
        )
        frappe.db.set_value("Member", self.member.name, "user", None, update_modified=False)

    def test_a_refused_account_creation_folds_into_the_member_key(self):
        self._enable_account_creation()
        self.expectErrorLog("MijnRood account creation refused")
        refusal = {"success": False, "error": {"code": "X", "message": "refused-2309", "errors": []}}
        # Mock justified: fault injection at the ACR queue the step calls
        with patch("verenigingen.utils.account_creation_manager.queue_account_creation_for_member", return_value=refusal):
            result = self._apply(new_data=self._member_fields())

        self._assert_applied(result)
        self.assertIn("Account creation not queued", result["message"])
        subject = self._subject("account creation")
        self.assertGreater(self._sent(subject), 0)
        self.assertNotIn(self.finance_user, self._recipients(subject))
        self.assertEqual(len(self._alert_events(MEMBER_KEY)), 1)

    def test_a_raised_account_creation_folds_into_the_member_key(self):
        self._enable_account_creation()
        self.expectErrorLog("MijnRood account creation failed")
        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            side_effect=RuntimeError("acr-boom-2309"),
        ):
            result = self._apply(new_data=self._member_fields())

        self._assert_applied(result)
        self.assertGreater(self._sent(self._subject("account creation")), 0)

    def test_an_account_blocked_by_a_real_failed_request_alerts(self):
        """The ACR pipeline only writes an Error Log row when a request fails (#2066), so a stuck Failed
        request is alerted from here. A real Failed ACR, failed through the real ``mark_failed()``."""
        self._enable_account_creation()
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": self.member.name,
                "email": self.member.email,
                "full_name": self.member.full_name,
                "role_profile": "Verenigingen Member",
                "business_justification": "test",
                "requested_roles": [{"role": "Verenigingen Member"}],
            }
        )
        request.insert()
        self.addCleanup(frappe.db.delete, "Account Creation Request", {"source_record": self.member.name})
        self.expectErrorLog("Account Creation Request failed")
        request.mark_failed("boom 2309", stage="User Creation")
        self.assertEqual(frappe.db.get_value("Account Creation Request", request.name, "status"), "Failed")
        self.expectErrorLog("MijnRood account creation blocked")

        result = self._apply(new_data=self._member_fields())

        self._assert_applied(result)
        self.assertIn(request.name, result["message"])
        subject = self._subject("account creation")
        self.assertGreater(self._sent(subject), 0)
        body = frappe.db.get_value("Notification Log", {"subject": subject}, "email_content")
        self.assertIn(request.name, body)

    # ---- volunteer-service steps ----------------------------------------------------------------------
    def _role_config(self, **config):
        return {
            "label": "Role",
            "create_volunteer": False,
            "verenigingen_role": None,
            "role_profile": None,
            "add_to_chapter_board": False,
            "chapter_role": None,
            "add_to_team": False,
            "default_team": None,
            **config,
        }

    def _admin_role_event(self, **config):
        return self._apply(
            new_data={"roles": json.dumps([ROLE_ADMIN])},
            old_data={"roles": "[]"},
            role_mapping={ROLE_ADMIN: self._role_config(**config)},
            with_id=False,
        )

    def _division_contact_event(self, division_ids, **config):
        return self._apply(
            new_data={"managed_division_ids": division_ids},
            role_mapping={ROLE_DIVISION_CONTACT: self._role_config(**config)},
            with_id=False,
        )

    def test_a_failed_volunteer_creation_alerts_and_its_no_volunteer_cascade_does_not(self):
        self.expectErrorLog("MijnRood Sync - Volunteer Creation Failed")
        # Mock justified: fault injection at the volunteer creation the step calls
        with patch(CREATE_VOLUNTEER, side_effect=RuntimeError("vol-boom-2309")):
            result = self._admin_role_event(create_volunteer=True)

        self._assert_applied(result)
        self.assertIn("Volunteer creation failed", result["message"])
        self.assertGreater(self._sent(self._subject("volunteer creation")), 0)
        self.assertEqual(len(self._alert_events(MEMBER_KEY)), 1)

    def test_the_skipped_volunteer_creation_alerts(self):
        with patch(CREATE_VOLUNTEER, return_value={"success": False, "error": "skip-reason-2309"}):
            result = self._admin_role_event(create_volunteer=True)

        self._assert_applied(result)
        self.assertIn("Volunteer creation skipped", result["message"])
        self.assertGreater(self._sent(self._subject("volunteer creation")), 0)

    def test_a_volunteer_whose_account_was_not_queued_alerts_as_an_account_failure(self):
        role = frappe.db.get_value("Role", {"disabled": 0}, "name")
        refused = {
            "success": True,
            "volunteer_name": "VOL-2309",
            "account_creation_queued": False,
            "account_creation_error": "acct-refused-2309",
        }
        with patch(CREATE_VOLUNTEER, return_value=refused):
            result = self._admin_role_event(create_volunteer=True, verenigingen_role=role)

        self._assert_applied(result)
        self.assertGreater(self._sent(self._subject("account creation")), 0)
        self.assertEqual(self._sent(self._subject("volunteer creation")), 0, "control: the volunteer exists")

    def _mapped_division_chapter(self):
        chapter = self.ensure_test_chapter(f"Test 2309 F {frappe.generate_hash(length=6)}")
        division = _unused_division_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", division)
        return division

    def test_a_board_add_after_a_failed_volunteer_creation_alerts_once_for_the_volunteer_only(self):
        """Class F, the real cascade: create_volunteer=1, creation fails, so the board add finds no Volunteer.
        Exactly one alert (the volunteer step); the cascade adds none."""
        division = self._mapped_division_chapter()
        self.expectErrorLog("MijnRood Sync - Volunteer Creation Failed")
        # Mock justified: fault injection at the volunteer creation the step calls
        with patch(CREATE_VOLUNTEER, side_effect=RuntimeError("vol-cascade-2309")):
            result = self._division_contact_event(
                [division], create_volunteer=True, add_to_chapter_board=True, chapter_role="Chair"
            )

        self._assert_applied(result)
        self.assertIn("Volunteer creation failed", result["message"])
        self.assertIn("No Volunteer record", result["message"], "control: the cascade path was taken")
        self.assertGreater(self._sent(self._subject("volunteer creation")), 0)
        self.assertEqual(self._sent(self._subject("chapter board addition")), 0)
        self.assertEqual(len(self._alert_events(MEMBER_KEY)), 1)

    def test_a_board_add_without_create_volunteer_is_not_alerted_a_known_gap(self):
        """Class F WITHOUT a cascade: add_to_chapter_board=1 and create_volunteer=0 (the settings validator
        allows it) never seats a Volunteer-less member and nothing is alerted, by the #2309 ruling. Pins the
        current silence so changing it is a decision, not an accident (issue filed for the gap)."""
        division = self._mapped_division_chapter()

        result = self._division_contact_event([division], add_to_chapter_board=True, chapter_role="Chair")

        self._assert_applied(result)
        self.assertIn("No Volunteer record", result["message"], "control: the F path was taken")
        self.assertEqual(self._sent(SUBJECT), 0)
        self.assertEqual(self._alert_events(MEMBER_KEY) + self._alert_events(MONEY_KEY), [])

    def test_a_failed_role_assignment_alerts(self):
        self.create_test_volunteer(self.member.name)
        frappe.db.set_value("Member", self.member.name, "user", self.admin_user, update_modified=False)
        role = frappe.db.get_value("Role", {"disabled": 0, "name": ["not in", frappe.get_roles(self.admin_user)]}, "name")
        # Mock justified: fault injection at the User role write the step calls
        with patch("frappe.core.doctype.user.user.User.add_roles", side_effect=RuntimeError("role-boom-2309")):
            result = self._admin_role_event(create_volunteer=True, verenigingen_role=role)

        self._assert_applied(result)
        self.assertIn("Role assignment failed", result["message"])
        self.assertGreater(self._sent(self._subject("role assignment")), 0)

    def test_a_failed_board_addition_alerts(self):
        self.create_test_volunteer(self.member.name)
        chapter = self.ensure_test_chapter(f"Test 2309 B {frappe.generate_hash(length=6)}")
        division = _unused_division_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", division)
        chapter_role = frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": f"T2309 {frappe.generate_hash(length=6)}", "is_active": 1}
        ).insert()
        self.expectErrorLog("MijnRood Sync - Chapter Board Addition Failed")
        # Mock justified: fault injection at the Chapter save the step performs
        with patch(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.save", side_effect=RuntimeError("board-boom-2309")
        ):
            result = self._division_contact_event(
                [division], add_to_chapter_board=True, chapter_role=chapter_role.name
            )

        self._assert_applied(result)
        self.assertIn("Chapter board addition failed", result["message"])
        self.assertGreater(self._sent(self._subject("chapter board addition")), 0)

    def test_a_failed_team_addition_alerts(self):
        self.create_test_volunteer(self.member.name)
        team = self.create_test_team(status="Active")
        self.expectErrorLog("MijnRood Sync - Team Addition Failed")
        # Mock justified: fault injection at the Team save the step performs
        with patch("verenigingen.verenigingen.doctype.team.team.Team.save", side_effect=RuntimeError("team-boom-2309")):
            result = self._division_contact_event(
                [_unused_division_id()], add_to_team=True, default_team=team.name
            )

        self._assert_applied(result)
        self.assertIn("Team addition failed", result["message"])
        self.assertGreater(self._sent(self._subject("team addition")), 0)

    # ---- registry -------------------------------------------------------------------------------------
    def test_the_money_key_row_carries_the_finance_audience_and_the_member_key_does_not(self):
        from verenigingen.notification_registry import NOTIFICATION_KEYS, REQUIRES_ACTION_KEYS

        self.assertIn("Verenigingen Financial Manager", NOTIFICATION_KEYS[MONEY_KEY]["recipient_roles"])
        self.assertIn("Verenigingen Administrator", NOTIFICATION_KEYS[MONEY_KEY]["recipient_roles"])
        self.assertIn("System Manager", NOTIFICATION_KEYS[MONEY_KEY]["recipient_roles"])
        self.assertNotIn("recipient_roles", NOTIFICATION_KEYS[MEMBER_KEY])
        self.assertTrue({MEMBER_KEY, MONEY_KEY} <= set(REQUIRES_ACTION_KEYS))

    def test_every_step_maps_to_exactly_one_key(self):
        from verenigingen.mijnrood_sync.services.event_application import member_step_alerts as m

        self.assertFalse(set(m.MONEY_STEPS) & set(m.MEMBER_STEPS))
        self.assertEqual({m.key_for(s) for s in m.MONEY_STEPS}, {MONEY_KEY})
        self.assertEqual({m.key_for(s) for s in m.MEMBER_STEPS}, {MEMBER_KEY})
        with self.assertRaises(ValueError):
            m.key_for("nonsense")
