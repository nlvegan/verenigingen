# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Real integration flow tests for the Procurios membership importer.

Creates real Members (with a procurios_id), real Membership Types wired to
real dues-schedule templates, and configures Verenigingen Settings with real
CSV dues-schedule templates. No business logic is mocked: the per-row
processor, MembershipImportService, and the Membership controller all run for
real, and we assert the observable effects (counters, created Membership
status, dues-schedule existence, error_log contents).
"""

import os
import tempfile

import frappe

from verenigingen.tests.utils.force_delete import force_delete

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.procurios_membership_import.procurios_membership_import import (
    process_import_background,
)

HEADER = "Debiteur Id,Debiteur Naam,Type,Looptijd,Ingangsdatum,Opgezegd,Einddatum,Normale prijs (type),Id"

SETTINGS_FIELDS = (
    "csv_monthly_dues_schedule",
    "csv_quarterly_dues_schedule",
    "csv_annual_dues_schedule",
)


class TestMembershipImportFlow(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._created_files = []
        self._created_imports = []
        self._created_users = []

        # Real Membership Types for the two mapped Procurios types.
        self.monthly_type = self.create_test_membership_type("ProcMonthly", amount=2.5)
        self.annual_type = self.create_test_membership_type("ProcAnnual", amount=20.0)

        # Real dues-schedule templates wired into Verenigingen Settings so the
        # active-membership path can resolve a template from payment_period.
        self._saved_settings = {
            f: frappe.db.get_single_value("Verenigingen Settings", f) for f in SETTINGS_FIELDS
        }
        settings = frappe.get_single("Verenigingen Settings")

        # Wire the CSV monthly template to the SAME membership type the active row
        # maps to (self.monthly_type), and make it a DISTINCT template from the
        # type's auto-created default. MembershipCreationService._resolve_dues_template
        # rejects a payment-period template whose membership_type differs from the
        # row's type and silently falls back to the type's default template. If the
        # CSV template were tied to an arbitrary type (or were the same as the
        # default), the "dues schedule created" assertion would pass even when the
        # payment_period -> csv_*_dues_schedule resolution is broken. The unique name
        # keeps the template tied to *this* test's unique membership type.
        self.monthly_template = self.ensure_dues_schedule_template(
            f"Procurios Monthly {self.monthly_type.name}",
            {
                "membership_type": self.monthly_type.name,
                "billing_frequency": "Monthly",
                "dues_rate": 2.5,
                "suggested_amount": 2.5,
                "minimum_amount": 1.25,
            },
        )
        settings.csv_monthly_dues_schedule = self.monthly_template.name
        settings.csv_quarterly_dues_schedule = self.ensure_dues_schedule_template("Procurios Quarterly").name
        settings.csv_annual_dues_schedule = self.ensure_dues_schedule_template("Procurios Annual").name
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        for name in self._created_imports:
            force_delete("Procurios Membership Import", name)
        for name in self._created_files:
            force_delete("File", name)
        for name in self._created_users:
            force_delete("User", name)
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in self._saved_settings.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    # ---- helpers ----

    def _make_csv_file(self, rows):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n")
            for r in rows:
                f.write(r + "\n")
        with open(path, "rb") as fh:
            filedoc = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": "procurios_memb_flow.csv",
                    "is_private": 1,
                    "content": fh.read(),
                }
            ).insert(ignore_permissions=True)
        os.unlink(path)
        self._created_files.append(filedoc.name)
        return filedoc.file_url

    def _make_import_doc(self, csv_url):
        return frappe.get_doc(
            {"doctype": "Procurios Membership Import", "csv_file": csv_url, "csv_delimiter": "Comma"}
        ).insert(ignore_permissions=True)

    def _run_import(self, rows, mapping, as_user=None):
        """Create + validate the import doc, apply the type mapping, SUBMIT it,
        then run the background processor synchronously. Returns the reloaded doc.

        This mirrors the production trigger: the real UI submits the import doc,
        and BaseCSVImport.on_submit enqueues process_import_background with
        now=False (which does NOT run inline in tests). We therefore submit the
        doc (docstatus=1) and then run the enqueued job by hand against the
        SUBMITTED doc, exactly as a worker would. Running the job on a submitted
        doc is what surfaces the post-submit child-table-write regression that a
        draft-only harness never caught.

        The doc prep (validate/save/submit) always runs as the current (admin)
        user; only the background processor runs as `as_user` when supplied, so
        tests can exercise the importer under a non-System-Manager identity.
        """
        url = self._make_csv_file(rows)
        doc = self._make_import_doc(url)
        self._created_imports.append(doc.name)

        # Populates membership_type_mapping from the CSV's distinct Type values.
        doc._validate_and_preview_csv()
        doc.reload()

        # The mapping must be complete BEFORE submit — membership_type_mapping is
        # not allow_on_submit, so it can only be written while docstatus=0.
        for child in doc.membership_type_mapping:
            if child.procurios_type in mapping:
                child.membership_type = mapping[child.procurios_type]
        doc.save()
        doc.submit()
        frappe.db.commit()

        if as_user:
            original_user = frappe.session.user
            try:
                frappe.set_user(as_user)
                process_import_background(doc.name, test_mode=False)
            finally:
                frappe.set_user(original_user)
        else:
            process_import_background(doc.name, test_mode=False)

        doc.reload()
        return doc

    def _make_non_sm_admin_user(self):
        """Create a user that can drive the importer but is NOT a System Manager.

        Two gates guard the background job:
        - ``prepare_background_import`` calls ``frappe.only_for(["System Manager",
          "Verenigingen Administrator"])`` — cleared by holding the
          *Verenigingen Administrator ROLE* (an atomic role that does NOT confer
          System Manager).
        - ``process_import_background`` is ``@critical_api`` (CRITICAL) — granted
          only through a role PROFILE (Rule 4). The *Verenigingen Treasurer*
          profile grants CRITICAL and, unlike the Verenigingen Administrator
          profile, does NOT bundle System Manager.

        Result: the user clears both gates yet ``frappe.get_roles`` excludes
        System Manager, so ``Membership.validate_dates``'s minimum-1-year rule
        still THROWS for it — proving the per-row Administrator elevation inside
        ``_create_historical_membership`` is load-bearing.
        """
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        email = "procurios.import.nonsm@example.com"
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Procurios",
                    "last_name": "NonSM",
                    "send_welcome_email": 0,
                }
            ).insert(ignore_permissions=True)
        self._created_users.append(email)

        # Assigning the profile syncs the user's roles to EXACTLY the profile's set.
        grant_matching_role_profiles(email, "Verenigingen Treasurer")

        # Add the Verenigingen Administrator ROLE directly (bypassing User.save,
        # which would re-strip it back to the profile's role set) so the
        # only_for(ADMIN_ROLES) gate passes. This role does NOT grant System Manager.
        if "Verenigingen Administrator" not in frappe.get_roles(email):
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": email,
                    "parenttype": "User",
                    "parentfield": "roles",
                    "role": "Verenigingen Administrator",
                }
            ).insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(user=email)
        return email

    # ---- tests ----

    def test_active_row_creates_membership_and_dues_schedule(self):
        member = self.create_test_member(procurios_id="900001")
        doc = self._run_import(
            ["900001,Test A,Maandlid,1 Maand,2022-11-27,,,2.5,900001"],
            {"Maandlid": self.monthly_type.name},
        )
        self.assertEqual(doc.memberships_created, 1)
        m = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "status", "procurios_membership_id"],
        )
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].status, "Active")
        self.assertEqual(m[0].procurios_membership_id, "900001")

        # Prove the dues schedule was built from the CSV monthly template resolved
        # via payment_period ("Maandelijks" -> csv_monthly_dues_schedule), NOT from
        # the membership type's fallback default template. Asserting mere existence
        # would pass even if the payment_period resolution silently fell back.
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0},
            ["name", "template_reference"],
            as_dict=True,
        )
        self.assertIsNotNone(schedule, "no dues schedule was created for the active member")
        self.assertEqual(
            schedule.template_reference,
            self.monthly_template.name,
            "dues schedule must come from the CSV payment-period template, not the "
            "membership type's fallback default",
        )

    def test_no_member_skips_and_logs(self):
        doc = self._run_import(
            ["999999,Nobody,Maandlid,1 Maand,2022-11-27,,,2.5,900002"],
            {"Maandlid": self.monthly_type.name},
        )
        self.assertEqual(doc.memberships_created, 0)
        self.assertEqual(doc.memberships_skipped, 1)
        self.assertIn("no Member with procurios_id=999999", doc.error_log)

    def test_cancelled_row_creates_historical_no_dues(self):
        member = self.create_test_member(procurios_id="900003")
        doc = self._run_import(
            ["900003,Test C,Jaarlid,1 Jaar,2018-01-01,2020-06-01,,20,900003"],
            {"Jaarlid": self.annual_type.name},
        )
        self.assertEqual(doc.memberships_created, 1)
        m = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "status"],
        )
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].status, "Cancelled")
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", {"member": member.name}))

    def test_idempotent_rerun_creates_nothing_new(self):
        member = self.create_test_member(procurios_id="900004")
        rows = ["900004,Test D,Maandlid,1 Maand,2022-11-27,,,2.5,900004"]
        first = self._run_import(rows, {"Maandlid": self.monthly_type.name})
        self.assertEqual(first.memberships_created, 1)

        second = self._run_import(rows, {"Maandlid": self.monthly_type.name})
        self.assertEqual(second.memberships_created, 0)
        self.assertEqual(frappe.db.count("Membership", {"member": member.name}), 1)

    def test_expired_row_creates_historical_expired(self):
        member = self.create_test_member(procurios_id="900007")
        # Einddatum in the past with no Opgezegd -> Expired. A historic 2018 start
        # + the annual period yields a past renewal_date, and NO cancellation_date
        # is stored, so Membership.set_status resolves to "Expired" (the cancellation
        # branch is skipped and the past-renewal branch is reached).
        doc = self._run_import(
            ["900007,Test G,Jaarlid,1 Jaar,2018-01-01,,2019-01-01,20,900007"],
            {"Jaarlid": self.annual_type.name},
        )
        self.assertEqual(doc.memberships_created, 1, msg=doc.error_log)
        m = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "status", "cancellation_date"],
        )
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].status, "Expired")
        self.assertFalse(m[0].cancellation_date, "Expired rows must not carry a cancellation_date")
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", {"member": member.name}))

    def test_admin_elevation_lets_short_cancelled_row_import(self):
        """The per-row Administrator elevation is load-bearing.

        A cancelled row whose cancellation is <12 months after the start date
        trips Membership.validate_dates' minimum-1-year throw for any
        non-System-Manager user. Running the whole import as a non-SM user, the
        row would error-skip if the elevation were removed; with the elevation it
        imports as Cancelled.
        """
        member = self.create_test_member(procurios_id="900006")
        user_email = self._make_non_sm_admin_user()
        self.assertNotIn(
            "System Manager",
            frappe.get_roles(user_email),
            "test user must NOT be a System Manager or the elevation would be untested",
        )

        # cancellation 2020-06-01 is only ~5 months after start 2020-01-01 (<12mo).
        doc = self._run_import(
            ["900006,Test F,Jaarlid,1 Jaar,2020-01-01,2020-06-01,,20,900006"],
            {"Jaarlid": self.annual_type.name},
            as_user=user_email,
        )
        self.assertEqual(doc.memberships_created, 1, msg=doc.error_log)
        m = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "status"],
        )
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].status, "Cancelled")

    def test_mixed_batch_active_cancelled_and_no_member(self):
        """One CSV file, three rows: an active (member exists), a cancelled
        (member exists), and a no-member row. Exercises the in-loop cache
        mutations that single-row tests never touch."""
        active_member = self.create_test_member(procurios_id="910001")
        cancelled_member = self.create_test_member(procurios_id="910002")

        doc = self._run_import(
            [
                "910001,Active One,Maandlid,1 Maand,2022-11-27,,,2.5,910001",
                "910002,Cancelled Two,Jaarlid,1 Jaar,2018-01-01,2020-06-01,,20,910002",
                "919999,Ghost Three,Maandlid,1 Maand,2022-11-27,,,2.5,910003",
            ],
            {"Maandlid": self.monthly_type.name, "Jaarlid": self.annual_type.name},
        )

        # Two created (active + cancelled historical), one skipped (no member).
        self.assertEqual(doc.memberships_created, 2, msg=doc.error_log)
        self.assertEqual(doc.memberships_skipped, 1)

        # Active member -> Active Membership + dues schedule.
        active = frappe.get_all(
            "Membership",
            filters={"member": active_member.name},
            fields=["name", "status", "procurios_membership_id"],
        )
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].status, "Active")
        self.assertEqual(active[0].procurios_membership_id, "910001")
        self.assertTrue(
            frappe.db.exists(
                "Membership Dues Schedule", {"member": active_member.name, "is_template": 0}
            ),
            "active member must get a dues schedule",
        )

        # Cancelled member -> Cancelled historical Membership, no dues schedule.
        cancelled = frappe.get_all(
            "Membership",
            filters={"member": cancelled_member.name},
            fields=["name", "status"],
        )
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0].status, "Cancelled")
        self.assertFalse(
            frappe.db.exists("Membership Dues Schedule", {"member": cancelled_member.name}),
            "historical cancelled member must NOT get a dues schedule",
        )

        # No-member row skipped and logged.
        self.assertIn("no Member with procurios_id=919999", doc.error_log)

        # Skipped summary reflects exactly the one no_member skip.
        self.assertIn("no_member: 1", doc.skipped_summary)

    def test_already_active_membership_skips_and_logs(self):
        member = self.create_test_member(procurios_id="900005")
        # Give the member a pre-existing active membership.
        self.create_test_membership(member=member.name, membership_type=self.monthly_type.name)
        doc = self._run_import(
            ["900005,Test E,Maandlid,1 Maand,2022-11-27,,,2.5,900005"],
            {"Maandlid": self.monthly_type.name},
        )
        self.assertEqual(doc.memberships_created, 0)
        self.assertIn("already has an active membership", doc.error_log)
