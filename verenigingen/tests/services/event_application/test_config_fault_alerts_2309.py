"""#2309 part 1: MijnRood sync CONFIGURATION faults must tell staff, once a day per fault.

A division id no Chapter owns / a mapped Chapter that is gone (A), a role-mapping target (Role, Chapter
Role, Team) that is missing or an inactive Team (B), a payment period with no dues template (C): the event
is consumed with only a message string and MijnRood does not resend. Each now raises a registered staff
alert (admin pair, never the Administrator user), queued during the event and sent AFTER its commit
(#2199's queue), deduplicated by a 24h Redis claim per FAULT, not per member.

Real flows: real admin_member Changed events applied by the real dispatcher, the real notify_administrators,
read back from Notification Log (recipients, subject) and Staff Alert Event. Probe shortcuts, stated:
* the role mapping is supplied by patching ``get_role_mapping`` where the volunteer service reads it
  (the real source is a Single plus a Redis cache; saving it would need a committing test);
* ``Member.user`` and ``Member.status`` / ``linked_member`` are set directly, standing in for earlier sync
  steps (account creation, activation) that are not under test;
* the unmapped division / missing Chapter are real states (no Chapter row owns the id; a Sync State row
  names a Chapter that does not exist).
Only SMTP is stubbed.
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync.services.event_application import volunteer_sync_service
from verenigingen.mijnrood_sync.services.event_application.dispatcher import (
    MijnRoodEventApplicationService as EventApplicationService,
    get_event_application_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

KEYS = (
    "mijnrood_division_unmapped",
    "mijnrood_role_mapping_invalid",
    "mijnrood_dues_template_unresolved",
)
SUBJECT_PREFIXES = (
    "MijnRood division %",
    "MijnRood role mapping invalid%",
    "MijnRood payment period %",
)
ROLE_ADMIN = "ROLE_ADMIN"
ROLE_DIVISION_CONTACT = "ROLE_DIVISION_CONTACT"


def _unused_division_id():
    return 8000000 + int(frappe.generate_hash(length=4), 16) % 900000


class TestConfigFaultAlerts2309(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
        from verenigingen.tests.test_notification_registry_seed_1959 import _rows

        # A site installed before the keys existed has no row until migrate seeds it: seed the way migrate
        # does and put the Single's rows back exactly as they were.
        self._baseline_rows = [dict(r.as_dict()) for r in _rows().values()]
        self.addCleanup(self._restore_registry_rows)
        ensure_notification_registry_rows()
        self.addCleanup(self._purge)
        self._purge()

        suffix = frappe.generate_hash(length=6)
        self.member = self.create_test_member(first_name="Config", last_name=f"Fault{suffix}")
        self.admin_user = self.create_test_user_with_roles(
            email=f"cfg2309.admin.{suffix}@example.com", roles=["Verenigingen Administrator"]
        ).name
        self.finance_user = self.create_test_user_with_roles(
            email=f"cfg2309.fin.{suffix}@example.com", roles=["Verenigingen Financial Manager"]
        ).name
        self.bystander = self.create_test_user_with_roles(
            email=f"cfg2309.other.{suffix}@example.com", roles=["Verenigingen Member"]
        ).name

    # ---- scaffolding --------------------------------------------------------------------------------
    def _restore_registry_rows(self):
        config = frappe.get_single("Verenigingen Email Configuration")
        config.notification_types = []
        for row in self._baseline_rows:
            config.append(
                "notification_types",
                {k: v for k, v in row.items() if k not in ("name", "creation", "modified", "idx")},
            )
        config.save()

    def _purge(self):
        frappe.db.delete("Staff Alert Event", {"notification_key": ["in", KEYS]})
        for prefix in SUBJECT_PREFIXES:
            frappe.db.delete("Notification Log", {"subject": ["like", prefix]})
        for key in KEYS:
            for claim in frappe.cache.get_keys(f"*{key}*"):
                frappe.cache.delete(claim.decode() if isinstance(claim, bytes) else claim)

    def _sent(self, subject_like):
        return frappe.db.count("Notification Log", {"subject": ["like", subject_like]})

    def _recipients(self, subject_like):
        return set(
            frappe.get_all("Notification Log", {"subject": ["like", subject_like]}, pluck="for_user")
        )

    def _alert_events(self, key):
        return frappe.get_all(
            "Staff Alert Event",
            {"notification_key": key},
            ["name", "subject", "outcome", "requires_action"],
        )

    def _apply(
        self, new_data=None, old_data=None, changed_fields=None, role_mapping=None, member=None, with_id=True
    ):
        """A real Changed admin_member event, applied by the real dispatcher. ``with_id=False`` makes a
        role-only event (the synthetic division-contact shape): ``id`` maps to member_id, which would send
        it down the member-update path instead of straight to role processing."""
        member = member or self.member
        mid = 6000000 + int(frappe.generate_hash(length=4), 16)
        event = frappe.get_doc(
            {
                "doctype": "MijnRood Sync Event",
                "mijnrood_table": "admin_member",
                "event_type": "Changed",
                "mijnrood_row_id": mid,
                "status": "Approved",
                "linked_member": member.name,
                "new_data": json.dumps({**({"id": mid} if with_id else {}), **(new_data or {})}),
                "old_data": json.dumps({**({"id": mid} if with_id else {}), **(old_data or {})}),
                "changed_fields": json.dumps(changed_fields or []),
            }
        ).insert()
        self.addCleanup(self._purge_event, event.name)
        self.last_event_name = event.name
        mapping = patch.object(volunteer_sync_service, "get_role_mapping", return_value=role_mapping or {})
        # Mock justified: External Service - SMTP delivery, not business logic
        with mapping, patch("frappe.sendmail"):
            return get_event_application_service().apply_event(event.name)

    def _purge_event(self, name):
        if frappe.db.exists("MijnRood Sync Event", name):
            frappe.delete_doc("MijnRood Sync Event", name, force=True)

    def _member_fields(self):
        return {
            "first_name": self.member.first_name,
            "last_name": self.member.last_name,
            "email": self.member.email,
            "current_membership_status_id": 1,
        }

    # ---- class A: division unmapped / chapter missing -----------------------------------------------
    def _move_to_division(self, division_id):
        return self._apply(
            new_data=self._member_fields(),
            changed_fields=[{"field": "division_id", "old": 1, "new": division_id}],
        )

    def _unmapped_subject(self, division_id):
        return f"MijnRood division {division_id}: unmapped"

    def test_an_unmapped_division_still_applies_the_event_and_alerts_staff_once(self):
        division = _unused_division_id()

        result = self._move_to_division(division)

        self.assertTrue(result["success"], result)
        self.assertIn(f"Division ID {division} does not match any Chapter", result["message"])
        self.assertEqual(
            frappe.db.get_value("MijnRood Sync Event", self.last_event_name, "status"), "Applied"
        )
        self.assertEqual(self._sent(self._unmapped_subject(division)), len(self._recipients(self._unmapped_subject(division))))
        (alert,) = self._alert_events("mijnrood_division_unmapped")
        self.assertEqual(alert.outcome, "Delivered", alert)
        self.assertEqual(alert.requires_action, 1)
        body = frappe.db.get_value(
            "Notification Log", {"subject": self._unmapped_subject(division)}, "email_content"
        )
        self.assertIn(str(division), body)
        self.assertIn(self.member.name, body)

    def test_the_alert_goes_to_the_admin_pair_and_never_to_administrator(self):
        division = _unused_division_id()
        self._move_to_division(division)

        recipients = self._recipients(self._unmapped_subject(division))

        self.assertIn(self.admin_user, recipients, "a Verenigingen Administrator must be told")
        # Not discriminating on its own: notify_administrators drops the Administrator user by name whether
        # or not the caller passes exclude_users (which only adds email-shared accounts). The audience mutant
        # that this test does catch is a changed recipient role, via the assertIn above.
        self.assertNotIn("Administrator", recipients, "ruling 2026-11-01: staff alerts skip Administrator")
        self.assertNotIn(self.bystander, recipients, "control: a user outside the admin pair is not told")
        # A Financial Manager exists, so a key re-pointed at that role would reach THEM and not the pair
        # (without one the resolver falls back to the Admin category and hides the wrong audience).
        self.assertNotIn(self.finance_user, recipients, "configuration faults are for the admin pair")

    def test_the_same_unmapped_division_the_same_day_does_not_alert_again(self):
        division = _unused_division_id()
        self._move_to_division(division)
        first = self._sent(self._unmapped_subject(division))
        self.assertGreater(first, 0, "control: the first event must have alerted")

        self._move_to_division(division)

        self.assertEqual(self._sent(self._unmapped_subject(division)), first)

    def test_a_different_unmapped_division_alerts_again(self):
        first, second = _unused_division_id(), _unused_division_id() + 1
        self._move_to_division(first)

        self._move_to_division(second)

        self.assertGreater(self._sent(self._unmapped_subject(first)), 0)
        self.assertGreater(self._sent(self._unmapped_subject(second)), 0)

    def test_a_missing_mapped_chapter_alerts_under_its_own_reason(self):
        """The division resolves (Sync State names a Chapter) to a Chapter that does not exist."""
        division = _unused_division_id()
        ghost = f"Ghost Chapter {frappe.generate_hash(length=6)}"
        state = frappe.get_doc(
            {
                "doctype": "MijnRood Sync State",
                "state_key": f"admin_division:{division}",
                "mijnrood_table": "admin_division",
                "mijnrood_row_id": division,
                "raw_data": json.dumps({"name": ghost}),
            }
        ).insert()
        self.addCleanup(frappe.delete_doc, "MijnRood Sync State", state.name, force=True)

        result = self._move_to_division(division)

        self.assertIn(f"Chapter '{ghost}' does not exist", result["message"])
        self.assertGreater(self._sent(f"MijnRood division {division}: chapter missing"), 0)
        self.assertEqual(self._sent(self._unmapped_subject(division)), 0, "control: not the unmapped reason")

    def test_a_mapped_division_raises_no_alert(self):
        """Control: a resolvable division is not a fault."""
        chapter = self.ensure_test_chapter(f"Test 2309 Mapped {frappe.generate_hash(length=6)}")
        division = _unused_division_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", division)

        result = self._move_to_division(division)

        self.assertIn(chapter.name, result["message"], result)
        self.assertEqual(self._alert_events("mijnrood_division_unmapped"), [])

    # ---- the alert survives the event's own rollbacks, and is not sent inside it ---------------------
    def test_the_alert_is_still_sent_when_the_member_update_then_fails(self):
        division = _unused_division_id()
        # Mock justified: fault injection at the member-import boundary: the update after the chapter step
        # is refused, so apply_changed_member returns failure and the event is not Applied.
        refused = patch(
            "verenigingen.services.csv_import.member_import_service.MemberImportService.create_or_update_member",
            return_value=("failed", None),
        )
        with refused:
            result = self._move_to_division(division)

        self.assertFalse(result["success"], result)
        self.assertGreater(
            self._sent(self._unmapped_subject(division)), 0, "the alert was rolled back with the event"
        )

    def _apply_once_and_roll_back(self, apply, fault):
        """Apply once under ``fault`` with a full rollback emulated (rollback to a savepoint taken before the
        apply: the harness holds its fixtures in one uncommitted transaction, a real rollback() would delete
        the member). Recording the failure commits, so it is stubbed."""
        self.expectErrorLog("MijnRood Event Application Failed")
        frappe.db.savepoint("full_rollback_2309")
        real_rollback = frappe.db.rollback
        # Mock justified: recording the failure on the event commits and destroys the emulated savepoint.
        with fault, patch.object(EventApplicationService, "_record_event_failure"), patch.object(
            frappe.db, "rollback", side_effect=lambda **kw: real_rollback(save_point="full_rollback_2309")
        ):
            return apply()

    def _assert_a_rolled_back_event_alerts_on_its_re_apply(self, apply, subject_like, fault=None):
        # Mock justified: fault injection; an unexpected exception after the faulty step.
        fault = fault or patch(
            "verenigingen.services.csv_import.member_import_service.MemberImportService.create_or_update_member",
            side_effect=RuntimeError("boom-2309"),
        )
        first = self._apply_once_and_roll_back(apply, fault)
        self.assertFalse(first["success"], first)
        self.assertEqual(self._sent(subject_like), 0, "control: the rollback took the first attempt")

        second = apply()

        self.assertTrue(second["success"], second)
        self.assertGreater(self._sent(subject_like), 0, "the re-apply must alert: no stale claim")

    def test_a_rolled_back_division_event_alerts_when_re_applied(self):
        division = _unused_division_id()
        self._assert_a_rolled_back_event_alerts_on_its_re_apply(
            lambda: self._move_to_division(division), self._unmapped_subject(division)
        )

    def test_a_claim_is_released_when_nothing_was_delivered(self):
        division = _unused_division_id()
        with patch(
            "verenigingen.utils.notification_helpers.notify_administrators",
            return_value={"success": True, "notifications_created": 0},
        ):
            self._move_to_division(division)
        self.assertEqual(self._sent(self._unmapped_subject(division)), 0, "control: nobody was reached")

        self._move_to_division(division)

        self.assertGreater(self._sent(self._unmapped_subject(division)), 0)

    def test_a_raising_alert_does_not_fail_the_event(self):
        division = _unused_division_id()
        self.expectErrorLog("MijnRood division alert failed")
        with patch(
            "verenigingen.utils.notification_helpers.notify_administrators", side_effect=RuntimeError("x-2309")
        ):
            result = self._move_to_division(division)

        self.assertTrue(result["success"], result)
        self.assertEqual(
            frappe.db.get_value("MijnRood Sync Event", self.last_event_name, "status"), "Applied"
        )

    # ---- class A and B on the volunteer path ---------------------------------------------------------
    def _raise_after_role_processing(self):
        """Mock justified: fault injection. Every step that queues an alert has run before the event is
        saved; the first save raises, so apply_event rolls back with the alert still queued."""
        from verenigingen.mijnrood_sync.doctype.mijnrood_sync_event.mijnrood_sync_event import (
            MijnRoodSyncEvent,
        )

        return patch.object(MijnRoodSyncEvent, "save", side_effect=[RuntimeError("boom-2309")] + [None] * 5)

    def _give_member_a_volunteer(self):
        self.create_test_volunteer(self.member.name)

    def _division_contact(self, division_ids, **config):
        mapping = {
            ROLE_DIVISION_CONTACT: {
                "label": "Division contact",
                "create_volunteer": False,
                "verenigingen_role": None,
                "role_profile": None,
                "add_to_chapter_board": False,
                "chapter_role": None,
                "add_to_team": False,
                "default_team": None,
                **config,
            }
        }
        return self._apply(
            new_data={"managed_division_ids": division_ids}, role_mapping=mapping, with_id=False
        )

    def test_the_board_add_for_an_unmapped_division_alerts_like_the_chapter_step(self):
        division = _unused_division_id()

        result = self._division_contact([division], add_to_chapter_board=True, chapter_role="Chair")

        self.assertIn(f"Division ID {division} does not match any Chapter", result["message"])
        self.assertGreater(self._sent(self._unmapped_subject(division)), 0)

    def test_the_orchestrator_and_the_board_add_share_one_claim_for_the_same_fault(self):
        """One unmapped division is one fault, however many steps trip over it: a single alert a day."""
        division = _unused_division_id()
        self._move_to_division(division)
        first = self._sent(self._unmapped_subject(division))

        self._division_contact([division], add_to_chapter_board=True, chapter_role="Chair")

        self.assertEqual(self._sent(self._unmapped_subject(division)), first)

    def test_the_board_add_for_a_missing_mapped_chapter_alerts(self):
        division = _unused_division_id()
        ghost = f"Ghost Board Chapter {frappe.generate_hash(length=6)}"
        state = frappe.get_doc(
            {
                "doctype": "MijnRood Sync State",
                "state_key": f"admin_division:{division}",
                "mijnrood_table": "admin_division",
                "mijnrood_row_id": division,
                "raw_data": json.dumps({"name": ghost}),
            }
        ).insert()
        self.addCleanup(frappe.delete_doc, "MijnRood Sync State", state.name, force=True)

        result = self._division_contact([division], add_to_chapter_board=True, chapter_role="Chair")

        self.assertIn(f"Chapter '{ghost}' does not exist", result["message"])
        self.assertGreater(self._sent(f"MijnRood division {division}: chapter missing"), 0)

    def _mapped_division(self):
        chapter = self.ensure_test_chapter(f"Test 2309 Board {frappe.generate_hash(length=6)}")
        division = _unused_division_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", division)
        return division

    def test_a_missing_chapter_role_alerts_naming_the_role(self):
        self._give_member_a_volunteer()
        division = self._mapped_division()
        role = f"No Such Chapter Role {frappe.generate_hash(length=6)}"

        result = self._division_contact([division], add_to_chapter_board=True, chapter_role=role)

        self.assertIn(f"Chapter Role '{role}' does not exist", result["message"])
        subject = f"MijnRood role mapping invalid: Chapter Role '{role}' does not exist"
        self.assertGreater(self._sent(subject), 0)
        (alert,) = self._alert_events("mijnrood_role_mapping_invalid")
        self.assertEqual((alert.outcome, alert.requires_action), ("Delivered", 1))
        self.assertIn(self.admin_user, self._recipients(subject))
        self.assertNotIn("Administrator", self._recipients(subject))

    def test_the_same_missing_chapter_role_for_another_member_does_not_alert_again(self):
        self._give_member_a_volunteer()
        division = self._mapped_division()
        role = f"No Such Chapter Role {frappe.generate_hash(length=6)}"
        subject = f"MijnRood role mapping invalid: Chapter Role '{role}' does not exist"
        self._division_contact([division], add_to_chapter_board=True, chapter_role=role)
        first = self._sent(subject)
        self.assertGreater(first, 0, "control: the first event must have alerted")

        other = self.create_test_member(first_name="Other", last_name=f"Cfg{frappe.generate_hash(length=6)}")
        self.create_test_volunteer(other.name)
        self.member = other
        self._division_contact([division], add_to_chapter_board=True, chapter_role=role)

        self.assertEqual(self._sent(subject), first, "dedupe is per fault, not per member")

    def test_a_different_missing_chapter_role_alerts_again(self):
        self._give_member_a_volunteer()
        division = self._mapped_division()
        first_role = f"No Such Chapter Role A {frappe.generate_hash(length=6)}"
        second_role = f"No Such Chapter Role B {frappe.generate_hash(length=6)}"
        self._division_contact([division], add_to_chapter_board=True, chapter_role=first_role)

        self._division_contact([division], add_to_chapter_board=True, chapter_role=second_role)

        for role in (first_role, second_role):
            self.assertGreater(
                self._sent(f"MijnRood role mapping invalid: Chapter Role '{role}' does not exist"), 0, role
            )

    def test_a_valid_chapter_role_raises_no_alert(self):
        """Control: a Chapter Role that exists is not a fault."""
        self._give_member_a_volunteer()
        division = self._mapped_division()
        role = frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": f"Test2309 {frappe.generate_hash(length=6)}", "is_active": 1}
        ).insert()
        self._division_contact([division], add_to_chapter_board=True, chapter_role=role.name)

        self.assertEqual(self._alert_events("mijnrood_role_mapping_invalid"), [])

    def test_a_missing_role_alerts(self):
        self._give_member_a_volunteer()
        frappe.db.set_value("Member", self.member.name, "user", self.admin_user)  # stands in for account creation
        role = f"No Such Role {frappe.generate_hash(length=6)}"
        mapping = {
            ROLE_ADMIN: {
                "label": "Admin",
                "create_volunteer": True,
                "verenigingen_role": role,
                "role_profile": None,
                "add_to_chapter_board": False,
                "chapter_role": None,
                "add_to_team": False,
                "default_team": None,
            }
        }

        result = self._apply(
            new_data={"roles": json.dumps([ROLE_ADMIN])},
            old_data={"roles": "[]"},
            role_mapping=mapping,
            with_id=False,
        )

        self.assertIn(f"Role '{role}' does not exist", result["message"])
        self.assertGreater(
            self._sent(f"MijnRood role mapping invalid: Role '{role}' does not exist"), 0
        )

    def test_a_missing_team_alerts(self):
        self._give_member_a_volunteer()
        team = f"No Such Team {frappe.generate_hash(length=6)}"

        result = self._apply(
            new_data={"managed_division_ids": [_unused_division_id()]},
            role_mapping=self._role_mapping(add_to_team=True, default_team=team),
            with_id=False,
        )

        self.assertIn(f"Team '{team}' does not exist", result["message"])
        self.assertGreater(
            self._sent(f"MijnRood role mapping invalid: Team '{team}' does not exist"), 0
        )

    def _role_mapping(self, **config):
        return {
            ROLE_DIVISION_CONTACT: {
                "label": "Division contact",
                "create_volunteer": False,
                "verenigingen_role": None,
                "role_profile": None,
                "add_to_chapter_board": False,
                "chapter_role": None,
                "add_to_team": False,
                "default_team": None,
                **config,
            }
        }

    def test_an_inactive_team_alerts_with_its_own_reason(self):
        self._give_member_a_volunteer()
        team = self.create_test_team(status="Inactive")
        self.assertEqual(frappe.db.get_value("Team", team.name, "status"), "Inactive", "control")

        result = self._apply(
            new_data={"managed_division_ids": [_unused_division_id()]},
            role_mapping=self._role_mapping(add_to_team=True, default_team=team.name),
            with_id=False,
        )

        self.assertIn(f"Team '{team.name}' is not active", result["message"])
        self.assertGreater(
            self._sent(f"MijnRood role mapping invalid: Team '{team.name}' is not active"), 0
        )

    def test_a_rolled_back_role_mapping_event_alerts_when_re_applied(self):
        self._give_member_a_volunteer()
        team = f"No Such Team {frappe.generate_hash(length=6)}"
        mapping = self._role_mapping(add_to_team=True, default_team=team)
        div = _unused_division_id()
        fault = self._raise_after_role_processing()
        self._assert_a_rolled_back_event_alerts_on_its_re_apply(
            lambda: self._apply(new_data={"managed_division_ids": [div]}, role_mapping=mapping, with_id=False),
            f"MijnRood role mapping invalid: Team '{team}' does not exist",
            fault=fault,
        )

    # ---- class C: dues template unresolved -------------------------------------------------------------
    def _dues_event(self):
        """A Changed event carrying a monthly contribution for an Active member whose Membership has no
        dues schedule: the backfill resolves the template from Verenigingen Settings."""
        return self._apply(
            new_data={
                **self._member_fields(),
                "contribution_per_period_in_cents": 1250,
                "contribution_period": 0,
            }
        )

    def _member_with_membership_but_no_schedule(self):
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
        membership.flags.skip_dues_schedule_creation = True  # else on_submit builds the schedule we need absent
        membership.submit()
        self.assertFalse(
            frappe.db.exists("Membership Dues Schedule", {"member": self.member.name, "is_template": 0}),
            "control: the fixture must leave the membership without a dues schedule",
        )
        return membership

    def _blank_monthly_template_setting(self):
        original = frappe.db.get_single_value("Verenigingen Settings", "csv_monthly_dues_schedule")
        if original:
            frappe.db.set_single_value("Verenigingen Settings", "csv_monthly_dues_schedule", "")
            self.addCleanup(
                frappe.db.set_single_value, "Verenigingen Settings", "csv_monthly_dues_schedule", original
            )

    def test_an_unresolved_dues_template_alerts_once_per_payment_period(self):
        self._blank_monthly_template_setting()
        self._member_with_membership_but_no_schedule()

        result = self._dues_event()

        self.assertIn("Dues schedule backfill skipped", result["message"], result)
        subject = "MijnRood payment period 'Maandelijks' has no dues template"
        first = self._sent(subject)
        self.assertGreater(first, 0)
        (alert,) = self._alert_events("mijnrood_dues_template_unresolved")
        self.assertEqual((alert.outcome, alert.requires_action), ("Delivered", 1))
        recipients = self._recipients(subject)
        self.assertIn(self.admin_user, recipients)
        self.assertNotIn("Administrator", recipients)
        self.assertNotIn(self.bystander, recipients)
        self.assertNotIn(self.finance_user, recipients)

        self._dues_event()

        self.assertEqual(self._sent(subject), first, "the same period the same day must not alert twice")

    def test_a_rolled_back_dues_event_alerts_when_re_applied(self):
        self._blank_monthly_template_setting()
        self._member_with_membership_but_no_schedule()
        # Mock justified: the real member update commits on its own, which would destroy the emulated
        # rollback's savepoint; the step under test is the dues backfill that follows it.
        member_update = patch(
            "verenigingen.services.csv_import.member_import_service.MemberImportService.create_or_update_member",
            return_value=("updated", self.member.name),
        )
        with member_update:
            self._assert_a_rolled_back_event_alerts_on_its_re_apply(
                self._dues_event,
                "MijnRood payment period 'Maandelijks' has no dues template",
                fault=self._raise_after_role_processing(),
            )
