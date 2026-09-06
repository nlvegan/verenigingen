# Integration tests for verenigingen/setup/__init__.py
#
# These exercise the install/seed/setup functions against a real site database.
# They focus on idempotent, safe-to-rerun seed functions and read-only verifiers.
# All of the seed functions are guarded by `if not frappe.db.exists(...)` so they
# are safe to call repeatedly on an already-installed site (which test sites are).
#
# Strategy: assert on the *post-condition* (record exists / default is set) rather
# than on "created N new records", because on an installed test site the records
# already exist. Idempotency is asserted by running each seed twice and confirming
# the row count does not grow.

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod


class TestSetupSeedFunctions(FrappeTestCase):
    """Exercise the reference-data seed functions in setup/__init__.py."""

    # ----- membership types -------------------------------------------------

    def test_create_default_membership_types_seeds_all(self):
        setup_mod.create_default_membership_types()
        expected = ["Lid", "Huisgenootlid", "Aspirant", "Erelid", "Donateur"]
        for name in expected:
            self.assertTrue(
                frappe.db.exists("Membership Type", name),
                f"Membership Type '{name}' should exist after seeding",
            )

    def test_create_default_membership_types_field_values(self):
        setup_mod.create_default_membership_types()
        lid = frappe.get_doc("Membership Type", "Lid")
        self.assertEqual(lid.role_profile, "Verenigingen Member")
        self.assertEqual(int(lid.is_active), 1)
        self.assertEqual(float(lid.minimum_amount), 3.0)

    def test_create_default_membership_types_idempotent(self):
        setup_mod.create_default_membership_types()
        before = frappe.db.count("Membership Type")
        # second run must create nothing new and must report 0 created
        created = setup_mod.create_default_membership_types()
        after = frappe.db.count("Membership Type")
        self.assertEqual(before, after)
        self.assertEqual(created, 0)

    # ----- team roles -------------------------------------------------------

    def test_create_default_team_roles_seeds_all(self):
        setup_mod.create_default_team_roles()
        expected = [
            "Team Leader",
            "Team Member",
            "Coordinator",
            "Secretary",
            "Treasurer",
            "Verenigingen Auditor",
        ]
        for name in expected:
            self.assertTrue(
                frappe.db.exists("Team Role", name),
                f"Team Role '{name}' should exist after seeding",
            )

    def test_team_leader_role_flags(self):
        setup_mod.create_default_team_roles()
        leader = frappe.get_doc("Team Role", "Team Leader")
        self.assertEqual(int(leader.is_team_leader), 1)
        self.assertEqual(int(leader.is_unique), 1)
        self.assertEqual(leader.permissions_level, "Leader")

    def test_create_default_team_roles_idempotent(self):
        setup_mod.create_default_team_roles()
        before = frappe.db.count("Team Role")
        created = setup_mod.create_default_team_roles()
        after = frappe.db.count("Team Role")
        self.assertEqual(before, after)
        self.assertEqual(created, 0)

    # ----- regions ----------------------------------------------------------

    def test_create_default_regions_seeds_all(self):
        setup_mod.create_default_regions()
        expected = [
            "Noord-Holland",
            "Utrecht",
            "Zuid-Holland",
            "Gelderland",
            "Noord-Brabant",
            "Limburg",
        ]
        for name in expected:
            self.assertTrue(
                frappe.db.exists("Region", name),
                f"Region '{name}' should exist after seeding",
            )

    def test_region_field_values(self):
        setup_mod.create_default_regions()
        nh = frappe.get_doc("Region", "Noord-Holland")
        self.assertEqual(nh.region_code, "NH")
        self.assertEqual(nh.country, "Netherlands")
        self.assertEqual(nh.time_zone, "Europe/Amsterdam")

    def test_create_default_regions_idempotent(self):
        setup_mod.create_default_regions()
        before = frappe.db.count("Region")
        created = setup_mod.create_default_regions()
        after = frappe.db.count("Region")
        self.assertEqual(before, after)
        self.assertEqual(created, 0)

    # ----- teams ------------------------------------------------------------

    def test_create_default_teams_seeds_kascommissie(self):
        setup_mod.create_default_teams()
        self.assertTrue(frappe.db.exists("Team", "Kascommissie"))
        team = frappe.get_doc("Team", "Kascommissie")
        self.assertEqual(team.team_type, "Committee")
        self.assertEqual(int(team.is_association_wide), 1)

    def test_create_default_teams_idempotent(self):
        setup_mod.create_default_teams()
        before = frappe.db.count("Team")
        created = setup_mod.create_default_teams()
        after = frappe.db.count("Team")
        self.assertEqual(before, after)
        self.assertEqual(created, 0)

    # ----- payment modes ----------------------------------------------------

    def test_create_default_payment_modes_seeds_all(self):
        setup_mod.create_default_payment_modes()
        expected = ["Mollie", "Ponto", "Bank Transfer", "SEPA Direct Debit", "Cash"]
        for name in expected:
            self.assertTrue(
                frappe.db.exists("Mode of Payment", name),
                f"Mode of Payment '{name}' should exist after seeding",
            )

    def test_create_default_payment_modes_idempotent(self):
        setup_mod.create_default_payment_modes()
        before = frappe.db.count("Mode of Payment")
        created = setup_mod.create_default_payment_modes()
        after = frappe.db.count("Mode of Payment")
        self.assertEqual(before, after)
        self.assertEqual(created, 0)

    # ----- membership items -------------------------------------------------

    def test_create_membership_items(self):
        setup_mod.create_membership_items()
        self.assertTrue(frappe.db.exists("Item Group", "Memberships"))
        self.assertTrue(frappe.db.exists("Item", "MEMBERSHIP"))
        item = frappe.get_doc("Item", "MEMBERSHIP")
        self.assertEqual(int(item.is_stock_item), 0)
        self.assertEqual(int(item.is_sales_item), 1)

    def test_create_membership_items_idempotent(self):
        setup_mod.create_membership_items()
        before = frappe.db.count("Item")
        setup_mod.create_membership_items()
        after = frappe.db.count("Item")
        self.assertEqual(before, after)

    # ----- prerequisites ----------------------------------------------------

    def test_ensure_prerequisites(self):
        setup_mod.ensure_prerequisites()
        self.assertTrue(frappe.db.exists("Customer Group", "All Customer Groups"))
        self.assertTrue(frappe.db.exists("Item Group", "Services"))
        self.assertTrue(frappe.db.exists("UOM", "Nos"))

    # ----- background service user ------------------------------------------

    def test_create_background_service_user(self):
        setup_mod.create_background_service_user()
        email = "background.service@verenigingen.local"
        self.assertTrue(frappe.db.exists("User", email))
        user = frappe.get_doc("User", email)
        self.assertEqual(int(user.enabled), 1)
        roles = {r.role for r in user.roles}
        self.assertIn("Verenigingen Webhook User", roles)
        # NOTE: the seed requests user_type="System User", but the only assigned
        # role (Verenigingen Webhook User) has desk_access=0, so Frappe's
        # User.validate_user_type() downgrades the account to "Website User".
        # This is framework behavior, not something we assert a specific value
        # for here. Flagged for review in the task report.

    def test_create_background_service_user_idempotent(self):
        setup_mod.create_background_service_user()
        before = frappe.db.count("User")
        setup_mod.create_background_service_user()
        after = frappe.db.count("User")
        self.assertEqual(before, after)


class TestSetupSettings(FrappeTestCase):
    """Exercise the settings / document-category seed functions."""

    def test_create_default_verenigingen_settings_returns_doc(self):
        settings = setup_mod.create_default_verenigingen_settings()
        self.assertIsNotNone(settings)
        # frappe.db.exists("Verenigingen Settings", "Verenigingen Settings")
        # is unconditionally truthy for a Single (dt == dn short-circuits in
        # frappe.db.exists, see #889) and proves nothing about whether
        # seeding actually happened -- it is true on any site, seeded or
        # not. _seed_default_document_categories() runs unconditionally at
        # the end of create_default_verenigingen_settings() regardless of
        # its create-branch's guard, so assert that real, discriminating
        # post-condition instead.
        self.assertTrue(
            settings.board_document_categories,
            "create_default_verenigingen_settings() must leave board document categories seeded",
        )

    def test_settings_seed_only_writes_existing_fields(self):
        """Regression guard: the seed dict must not reference fields that no
        longer exist on the Verenigingen Settings doctype.

        Previously the seed set company_iban / company_bic / creditor_id /
        default_donation_type / enable_income_calculator, which were moved to
        the Verenigingen Payments Settings doctype (or removed). Frappe silently
        drops unknown keys passed to get_doc(), so the bug was invisible: the
        config the author intended to seed was never actually applied. This
        test asserts the live doctype carries every field the seed writes.
        """
        meta = frappe.get_meta("Verenigingen Settings")
        live_fields = {f.fieldname for f in meta.fields}
        # Fields the seed dict intends to populate (see
        # create_default_verenigingen_settings). All must exist on the doctype.
        seeded_fields = [
            "company",
            "company_name",
            "organization_email_domain",
            "member_contact_email",
            "support_email",
            "creation_user",
            "default_donor_type",
            "auto_create_donors",
            "minimum_donation_amount",
            "enable_chapter_management",
            "member_id_start",
            "last_member_id",
            "default_grace_period_days",
            "max_fee_adjustments_per_year",
            "automate_donation_payment_entries",
            "auto_cancel_sepa_mandates",
            "auto_end_board_positions",
            "send_termination_notifications",
        ]
        missing = [f for f in seeded_fields if f not in live_fields]
        self.assertEqual(
            missing,
            [],
            f"Settings seed writes fields that no longer exist on the doctype: {missing}",
        )

    def test_seed_default_document_categories(self):
        settings = setup_mod.create_default_verenigingen_settings()
        setup_mod._seed_default_document_categories(settings)
        settings.reload()
        names = {row.category_name for row in (settings.board_document_categories or [])}
        for cat in ["Policy", "Meeting Minutes", "Financial Report", "Intern Bulletin", "Other"]:
            self.assertIn(cat, names)

    def test_seed_default_document_categories_idempotent(self):
        settings = setup_mod.create_default_verenigingen_settings()
        setup_mod._seed_default_document_categories(settings)
        settings.reload()
        before = len(settings.board_document_categories or [])
        setup_mod._seed_default_document_categories(settings)
        settings.reload()
        after = len(settings.board_document_categories or [])
        self.assertEqual(before, after)


class TestSetupEmailTemplates(FrappeTestCase):
    """Email-template seed + verifier functions."""

    def test_setup_email_templates(self):
        setup_mod.setup_email_templates()
        self.assertTrue(frappe.db.exists("Email Template", "Termination Approval Required"))

    def test_setup_email_templates_idempotent(self):
        setup_mod.setup_email_templates()
        before = frappe.db.count("Email Template")
        setup_mod.setup_email_templates()
        after = frappe.db.count("Email Template")
        self.assertEqual(before, after)

    def test_create_application_email_templates(self):
        count = setup_mod.create_application_email_templates()
        self.assertIsInstance(count, int)
        self.assertTrue(frappe.db.exists("Email Template", "membership_application_confirmation"))

    def test_verify_email_templates_structure(self):
        # ensure at least the basic templates exist first
        setup_mod.create_application_email_templates()
        result = setup_mod.verify_email_templates()
        self.assertTrue(result["success"])
        self.assertIn("existing_basic_templates", result)
        self.assertIn("missing_basic_templates", result)
        self.assertIn("total_related_count", result)


class TestSetupDeprecatedAndVerifiers(FrappeTestCase):
    """Deprecated stubs and read-only status/verify functions."""

    def test_create_donation_types_manual_deprecated(self):
        result = setup_mod.create_donation_types_manual()
        self.assertFalse(result["success"])
        self.assertIn("removed", result["message"].lower())

    def test_verify_donation_type_setup_deprecated(self):
        result = setup_mod.verify_donation_type_setup()
        self.assertFalse(result["success"])

    def test_check_termination_system_status(self):
        result = setup_mod.check_termination_system_status()
        self.assertIsInstance(result, dict)

    def test_verify_app_dependencies(self):
        result = setup_mod.verify_app_dependencies()
        self.assertIsInstance(result, dict)
