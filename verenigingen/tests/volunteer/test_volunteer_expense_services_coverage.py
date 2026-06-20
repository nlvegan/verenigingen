"""
Coverage-focused tests for the three volunteer-expense service modules:

1. services/volunteer/expense_submission_service.py
   - VolunteerExpenseSubmissionService organization-access / cost-center /
     receipt-attach / grouped-submission branches against real DB fixtures.
2. services/volunteer/volunteer_expense_portal_utils.py
   - statistics, organizations, validation, status mapping, context building.
3. services/volunteer/native_expense_helpers.py
   - approver lookup / employee-approver sync / setup validation / readiness,
     including the literal-format-string prod bugs fixed in this sweep.

All tests use real Volunteer/Member/Chapter/Team/Expense Category fixtures
created via the canonical EnhancedTestCase factories. Expected values are
derived from the data each test creates. No business-logic mocking.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------
class _ExpenseFixtureMixin:
    """Helpers shared across the expense-service test classes."""

    def _company(self):
        return frappe.db.get_single_value("Verenigingen Settings", "company") or "_Test Company"

    def _expense_account(self):
        """Return a real expense (non-group) account for the configured company."""
        acct = frappe.db.get_value(
            "Account",
            {"company": self._company(), "root_type": "Expense", "is_group": 0},
            "name",
        )
        self.assertIsNotNone(acct, "Test company must have at least one expense account")
        return acct

    def _make_expense_category(self, *, with_account=True, policy_covered=0, is_active=1, name_hint="Cat"):
        """Create a real Expense Category and track it for cleanup.

        expense_account is a mandatory field on Expense Category, so even the
        ``with_account=False`` variant must be inserted WITH an account and then
        have it cleared via db.set_value to exercise the missing-account branch.
        """
        cat = frappe.new_doc("Expense Category")
        # category_name carries the descriptive label; use a keyword-bearing hint
        # so the policy keyword-matching fallback can be exercised deterministically.
        cat.category_name = f"{name_hint} {frappe.generate_hash(length=6)}"
        cat.is_active = is_active
        cat.policy_covered = policy_covered
        cat.expense_account = self._expense_account()
        cat.insert(ignore_permissions=True)
        self.factory.track_document("Expense Category", cat.name, priority=0)
        if not with_account:
            frappe.db.set_value("Expense Category", cat.name, "expense_account", "")
            cat.reload()
        return cat

    def _add_chapter_member(self, chapter_name, member_name):
        """Attach a member to a chapter via the Chapter Member child table.

        Runs as the default test user (Administrator), so no permission bypass
        is needed.
        """
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append("members", {"member": member_name, "enabled": 1})
        chapter.save()
        return chapter

    def _make_employee(self, *, expense_approver=None, name_hint="EmpApr"):
        """Create a minimal real Employee (no expense_approver by default)."""
        gender = frappe.db.get_value("Gender", {}, "name") or "Other"
        emp = frappe.new_doc("Employee")
        emp.first_name = f"{name_hint}{frappe.generate_hash(length=5)}"
        emp.gender = gender
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = "2020-01-01"
        emp.status = "Active"
        emp.company = self._company()
        if expense_approver:
            emp.expense_approver = expense_approver
        emp.insert(ignore_permissions=True)
        self.factory.track_document("Employee", emp.name, priority=0)
        return emp


# ---------------------------------------------------------------------------
# 1. VolunteerExpenseSubmissionService — access / cost-center / receipts
# ---------------------------------------------------------------------------
class TestExpenseSubmissionServiceDeep(_ExpenseFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="ExpDeep", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    def _svc(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            get_expense_submission_service,
        )

        return get_expense_submission_service(self.volunteer.name)

    # -- volunteer_name property resolution --

    def test_volunteer_name_returns_explicit(self):
        svc = self._svc()
        self.assertEqual(svc.volunteer_name, self.volunteer.name)

    def test_volunteer_doc_lazy_load(self):
        svc = self._svc()
        self.assertEqual(svc.volunteer_doc.name, self.volunteer.name)

    def test_settings_and_company_properties(self):
        svc = self._svc()
        self.assertIsNotNone(svc.settings)
        self.assertEqual(svc.company, self._company())

    # -- _validate_request: additional expense line validation --

    def test_validate_request_bad_additional_line(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            ExpenseSubmissionRequest,
        )

        cat = self._make_expense_category()
        svc = self._svc()
        req = ExpenseSubmissionRequest(
            description="Primary",
            amount=10.0,
            expense_date="2025-01-01",
            organization_type="National",
            category=cat.name,
            additional_expenses=[{"description": "", "amount": 0, "category": cat.name}],
        )
        errors = svc._validate_request(req)
        # additional line is line 2, missing description -> error referencing "Line 2"
        self.assertTrue(any("Line 2" in e for e in errors), errors)

    def test_validate_expense_line_missing_account(self):
        svc = self._svc()
        cat = self._make_expense_category(with_account=False)
        err = svc._validate_expense_line({"description": "x", "amount": 5, "category": cat.name}, 3)
        self.assertIsNotNone(err)
        self.assertIn("expense account", err.lower())

    def test_validate_expense_line_valid(self):
        svc = self._svc()
        cat = self._make_expense_category()
        err = svc._validate_expense_line({"description": "x", "amount": 5, "category": cat.name}, 2)
        self.assertIsNone(err)

    # -- _validate_organization_access: chapter --

    def test_chapter_access_denied_without_membership(self):
        chapter = self.ensure_test_chapter("ExpAccessChap")
        svc = self._svc()
        err = svc._validate_chapter_access(chapter.name)
        self.assertIsNotNone(err)
        self.assertIn("Chapter membership required", err)

    def test_chapter_access_allowed_with_membership(self):
        chapter = self.ensure_test_chapter("ExpAccessChap2")
        self._add_chapter_member(chapter.name, self.member.name)
        svc = self._svc()
        self.assertIsNone(svc._validate_chapter_access(chapter.name))

    # -- _validate_organization_access: team --

    def test_team_access_denied_without_membership(self):
        team = self.create_test_team(team_name="ExpAccessTeam")
        svc = self._svc()
        err = svc._validate_team_access(team.name)
        self.assertIsNotNone(err)
        self.assertIn("Team membership required", err)

    def test_team_access_allowed_with_membership(self):
        team = self.create_test_team(team_name="ExpAccessTeam2")
        self.create_test_team_member(team.name, self.volunteer.name)
        svc = self._svc()
        self.assertIsNone(svc._validate_team_access(team.name))

    # -- _validate_national_access --

    def test_national_access_policy_covered_allowed(self):
        cat = self._make_expense_category(policy_covered=1, name_hint="Travel")
        svc = self._svc()
        # policy_covered=1 -> allowed regardless of board membership
        self.assertIsNone(svc._validate_national_access(cat.name))

    def test_national_access_no_board_chapter_configured(self):
        # When national_board_chapter is not set, non-policy national expense is allowed.
        if frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"):
            self.skipTest("national_board_chapter configured on this site")
        cat = self._make_expense_category(policy_covered=0, name_hint="Luxury")
        svc = self._svc()
        self.assertIsNone(svc._validate_national_access(cat.name))

    # -- _is_policy_covered_expense database vs keyword --

    def test_is_policy_covered_db_field(self):
        cat = self._make_expense_category(policy_covered=1, name_hint="Luxury")
        svc = self._svc()
        self.assertTrue(svc._is_policy_covered_expense(cat.name))

    def test_is_policy_covered_keyword_only(self):
        svc = self._svc()
        # category that does not exist as a doctype -> falls to keyword matching
        self.assertTrue(svc._is_policy_covered_expense("Phone bill"))
        self.assertFalse(svc._is_policy_covered_expense("Gala tickets"))

    # -- _validate_organization_access dispatch --

    def test_validate_org_access_dispatch_chapter(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            ExpenseSubmissionRequest,
        )

        chapter = self.ensure_test_chapter("ExpDispatchChap")
        svc = self._svc()
        req = ExpenseSubmissionRequest(
            description="x",
            amount=1,
            expense_date="2025-01-01",
            organization_type="Chapter",
            category="y",
            chapter=chapter.name,
        )
        # no membership -> error returned
        self.assertIsNotNone(svc._validate_organization_access(req))

    # -- _resolve_organization national requires board chapter --

    def test_resolve_organization_national_no_board_raises(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            ExpenseSubmissionRequest,
        )

        if frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"):
            self.skipTest("national_board_chapter configured on this site")
        svc = self._svc()
        req = ExpenseSubmissionRequest(
            description="x",
            amount=1,
            expense_date="2025-01-01",
            organization_type="National",
            category="y",
        )
        with self.assertRaises(frappe.ValidationError):
            svc._resolve_organization(req)

    # -- _get_cost_center returns a real cost center --

    def test_get_cost_center_national(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            ExpenseSubmissionRequest,
        )

        svc = self._svc()
        req = ExpenseSubmissionRequest(
            description="x",
            amount=1,
            expense_date="2025-01-01",
            organization_type="National",
            category="y",
        )
        cc = svc._get_cost_center(req)
        self.assertTrue(frappe.db.exists("Cost Center", cc))

    # -- _attach_receipt: real base64 attach success --

    def test_attach_base64_receipt_creates_file(self):
        """The base64 branch decodes content and inserts a real File attached to
        the expense claim name (File does not enforce attached_to_name existence)."""
        import base64

        svc = self._svc()
        claim_name = f"EC-RCPT-{frappe.generate_hash(length=8)}"
        content = base64.b64encode(b"hello-receipt").decode()

        with self.assertNoErrorLog():
            res = svc._attach_receipt(
                claim_name,
                {"file_content": content, "file_name": "receipt.png"},
            )

        self.assertTrue(res["success"], res)
        # A real File row exists attached to that claim name with the decoded content.
        file_name = frappe.db.get_value(
            "File",
            {"attached_to_doctype": "Expense Claim", "attached_to_name": claim_name},
            "name",
        )
        self.assertIsNotNone(file_name)
        self.factory.track_document("File", file_name, priority=0)

    def test_attach_frappe_file_format_dispatch(self):
        """The Frappe-upload branch (file_url + frappe_file_name) re-points an
        existing File at the expense claim."""
        svc = self._svc()
        # Create a real File first by attaching it (via the base64 helper) to a
        # throwaway claim name, then re-point it through the Frappe-upload branch.
        import base64

        seed_claim = f"EC-SEED-{frappe.generate_hash(length=8)}"
        # Use a .png name: Frappe validates PDF headers, so junk .pdf bytes are
        # rejected; .png content is not header-validated here.
        svc._attach_receipt(
            seed_claim,
            {"file_content": base64.b64encode(b"seed-bytes").decode(), "file_name": "upload.png"},
        )
        src_name = frappe.db.get_value(
            "File",
            {"attached_to_doctype": "Expense Claim", "attached_to_name": seed_claim},
            "name",
        )
        self.assertIsNotNone(src_name)
        self.factory.track_document("File", src_name, priority=0)
        src = frappe.get_doc("File", src_name)

        claim_name = f"EC-RCPT2-{frappe.generate_hash(length=8)}"
        with self.assertNoErrorLog():
            res = svc._attach_receipt(
                claim_name,
                {"file_url": src.file_url, "frappe_file_name": src.name},
            )
        self.assertTrue(res["success"], res)
        src.reload()
        self.assertEqual(src.attached_to_doctype, "Expense Claim")
        self.assertEqual(src.attached_to_name, claim_name)

    def test_attach_receipt_no_valid_format(self):
        svc = self._svc()
        res = svc._attach_receipt("EC-NONEXISTENT", {"unrelated": "data"})
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    # -- submit_multiple_expenses_grouped: validation aggregation --

    def test_grouped_validation_errors(self):
        svc = self._svc()
        # missing required fields -> aggregated validation errors, no claims
        result = svc.submit_multiple_expenses_grouped(
            [{"description": "", "amount": 0, "expense_date": "", "organization_type": "", "category": ""}]
        )
        self.assertFalse(result.success)
        self.assertTrue(result.errors)

    def test_grouped_total_amount_limit(self):
        from frappe.utils import today

        cat = self._make_expense_category(name_hint="Travel")
        svc = self._svc()
        # Three per-line-valid lines (each <= 5,000, recent date) whose sum
        # exceeds 10,000 -> rejected by the aggregate total-amount guard.
        expenses = [
            {
                "description": f"Line{i}",
                "amount": 4000,
                "expense_date": today(),
                "organization_type": "National",
                "category": cat.name,
            }
            for i in range(3)
        ]
        result = svc.submit_multiple_expenses_grouped(expenses)
        self.assertFalse(result.success)
        self.assertIn("10,000", result.error_message)

    def test_grouped_invalid_input_type(self):
        svc = self._svc()
        result = svc.submit_multiple_expenses_grouped("not-a-list")
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# 2. volunteer_expense_portal_utils
# ---------------------------------------------------------------------------
class TestVolunteerExpensePortalUtils(_ExpenseFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="PortalUtil", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    # -- statistics --

    def test_get_empty_statistics_shape(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_empty_statistics,
        )

        stats = get_empty_statistics()
        for key in (
            "total_submitted",
            "total_approved",
            "pending_amount",
            "pending_count",
            "approved_count",
            "total_count",
        ):
            self.assertEqual(stats[key], 0)

    def test_statistics_no_employee_returns_empty(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_volunteer_expense_statistics,
        )

        # Fresh volunteer has no employee_id.
        self.assertFalse(self.volunteer.employee_id)
        stats, debug = get_volunteer_expense_statistics(self.volunteer.name)
        self.assertEqual(stats["total_count"], 0)
        self.assertIn("No employee_id", debug)

    def test_statistics_nonexistent_volunteer(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_volunteer_expense_statistics,
        )

        stats, debug = get_volunteer_expense_statistics("NONEXISTENT-VOL-XYZ")
        self.assertEqual(stats["total_count"], 0)
        self.assertIn("not found", debug)

    # -- organizations --

    def test_get_volunteer_organizations_chapter_and_team(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_volunteer_organizations,
        )

        chapter = self.ensure_test_chapter("PortalOrgChap")
        self._add_chapter_member(chapter.name, self.member.name)
        team = self.create_test_team(team_name="PortalOrgTeam")
        self.create_test_team_member(team.name, self.volunteer.name)

        orgs = get_volunteer_organizations(self.volunteer.name)
        chapter_names = [c["name"] for c in orgs["chapters"]]
        team_names = [t["name"] for t in orgs["teams"]]
        self.assertIn(chapter.name, chapter_names)
        self.assertIn(team.name, team_names)

    def test_get_volunteer_organizations_nonexistent(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_volunteer_organizations,
        )

        orgs = get_volunteer_organizations("NONEXISTENT-VOL-ORG")
        self.assertEqual(orgs, {"chapters": [], "teams": []})

    # -- categories / thresholds / national --

    def test_get_expense_categories_active_only(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_expense_categories,
        )

        active = self._make_expense_category(is_active=1, name_hint="ActiveCat")
        inactive = self._make_expense_category(is_active=0, name_hint="InactiveCat")
        names = [c["name"] for c in get_expense_categories()]
        self.assertIn(active.name, names)
        self.assertNotIn(inactive.name, names)

    def test_get_approval_thresholds(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_approval_thresholds,
        )

        t = get_approval_thresholds()
        self.assertEqual(t["basic_limit"], 100.0)
        self.assertEqual(t["financial_limit"], 500.0)

    def test_get_national_chapter_none_when_unset(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_national_chapter,
        )

        if frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"):
            self.skipTest("national_board_chapter configured on this site")
        self.assertIsNone(get_national_chapter())

    # -- status mapping / status class --

    def test_map_status_combinations(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            map_erpnext_status_to_volunteer_status,
        )

        self.assertEqual(map_erpnext_status_to_volunteer_status("Draft"), "Draft")
        self.assertEqual(map_erpnext_status_to_volunteer_status("Submitted", "Approved"), "Approved")
        self.assertEqual(map_erpnext_status_to_volunteer_status("Submitted", "Rejected"), "Rejected")
        self.assertEqual(map_erpnext_status_to_volunteer_status("Submitted", None), "Submitted")
        self.assertEqual(map_erpnext_status_to_volunteer_status("Paid"), "Reimbursed")
        self.assertEqual(map_erpnext_status_to_volunteer_status("Cancelled"), "Rejected")
        self.assertEqual(map_erpnext_status_to_volunteer_status("Weird"), "Weird")

    def test_get_status_class(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_status_class,
        )

        self.assertEqual(get_status_class("Approved"), "badge-success")
        self.assertEqual(get_status_class("Rejected"), "badge-danger")
        self.assertEqual(get_status_class("Unknown"), "badge-secondary")

    # -- get_volunteer_expenses_from_claims --

    def test_expenses_from_claims_no_employee(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_volunteer_expenses_from_claims,
        )

        self.assertEqual(get_volunteer_expenses_from_claims(self.volunteer.name), [])

    def test_expenses_from_claims_nonexistent(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_volunteer_expenses_from_claims,
        )

        self.assertEqual(get_volunteer_expenses_from_claims("NONEXISTENT-VOL-CLM"), [])

    # -- validate_volunteer_organization_access --

    def test_validate_org_access_chapter_direct(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_volunteer_organization_access,
        )

        chapter = self.ensure_test_chapter("PortalAccessChap")
        # The volunteer's member is a direct Chapter Member -> access granted.
        # (Regression: the check previously filtered Chapter Member on a phantom
        # `volunteer` column, which never matched and denied genuine members.)
        self._add_chapter_member(chapter.name, self.member.name)
        result = validate_volunteer_organization_access(self.volunteer.name, "Chapter", chapter.name)
        self.assertTrue(result)

    def test_validate_org_access_chapter_denied_without_membership(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_volunteer_organization_access,
        )

        chapter = self.ensure_test_chapter("PortalAccessChapDeny")
        # No chapter membership and no team-fallback -> access denied.
        result = validate_volunteer_organization_access(self.volunteer.name, "Chapter", chapter.name)
        self.assertFalse(result)

    def test_validate_org_access_team_direct(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_volunteer_organization_access,
        )

        team = self.create_test_team(team_name="PortalAccessTeam")
        self.create_test_team_member(team.name, self.volunteer.name)
        self.assertTrue(validate_volunteer_organization_access(self.volunteer.name, "Team", team.name))

    def test_validate_org_access_team_denied(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_volunteer_organization_access,
        )

        team = self.create_test_team(team_name="PortalAccessTeam2")
        self.assertFalse(validate_volunteer_organization_access(self.volunteer.name, "Team", team.name))

    def test_validate_org_access_national_open(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_volunteer_organization_access,
        )

        self.assertTrue(validate_volunteer_organization_access(self.volunteer.name, "National", "National"))

    def test_validate_org_access_unknown_type(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_volunteer_organization_access,
        )

        self.assertFalse(validate_volunteer_organization_access(self.volunteer.name, "Nonsense", "X"))

    # -- is_policy_covered_expense (module-level) --

    def test_module_is_policy_covered_db_field(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            is_policy_covered_expense,
        )

        cat = self._make_expense_category(policy_covered=1, name_hint="Luxury")
        self.assertTrue(is_policy_covered_expense(cat.name))

    def test_module_is_policy_covered_keyword(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            is_policy_covered_expense,
        )

        cat = self._make_expense_category(policy_covered=0, name_hint="Travel")
        self.assertTrue(is_policy_covered_expense(cat.name))

    def test_module_is_policy_covered_nonexistent_category(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            is_policy_covered_expense,
        )

        # get_doc on a missing category -> exception path -> returns False.
        # The function logs a "Policy Coverage Check" error, which is the
        # documented behaviour; mark it expected so the tearDown guard ignores it.
        self.expectErrorLog("Policy Coverage Check")
        self.assertFalse(is_policy_covered_expense("NONEXISTENT-CATEGORY-XYZ"))

    # -- validate_expense_data (rich validator) --

    def test_validate_expense_data_all_good(self):
        from frappe.utils import today

        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        cat = self._make_expense_category(name_hint="Travel")
        errors = validate_expense_data(
            {
                "description": "Train",
                "amount": 25,
                "expense_date": today(),
                "organization_type": "National",
                "category": cat.name,
            },
            1,
        )
        self.assertEqual(errors, [])

    def test_validate_expense_data_amount_too_high(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        cat = self._make_expense_category(name_hint="Travel")
        errors = validate_expense_data(
            {
                "description": "Pricey",
                "amount": 6000,
                "expense_date": "2025-01-01",
                "organization_type": "National",
                "category": cat.name,
            },
            1,
        )
        self.assertTrue(any(e["field"] == "amount" for e in errors))

    def test_validate_expense_data_future_date(self):
        from frappe.utils import add_days, getdate, today

        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        cat = self._make_expense_category(name_hint="Travel")
        future = add_days(getdate(today()), 5)
        errors = validate_expense_data(
            {
                "description": "Future",
                "amount": 10,
                "expense_date": str(future),
                "organization_type": "National",
                "category": cat.name,
            },
            1,
        )
        self.assertTrue(any("future" in e["error"].lower() for e in errors))

    def test_validate_expense_data_invalid_amount_format(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        errors = validate_expense_data(
            {
                "description": "Bad",
                "amount": "not-a-number",
                "expense_date": "2025-01-01",
                "organization_type": "National",
                "category": None,
            },
            1,
        )
        self.assertTrue(any(e["field"] == "amount" for e in errors))

    def test_validate_expense_data_invalid_category(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        errors = validate_expense_data(
            {
                "description": "x",
                "amount": 10,
                "expense_date": "2025-01-01",
                "organization_type": "National",
                "category": "NONEXISTENT-CATEGORY-ABC",
            },
            2,
        )
        self.assertTrue(any(e["field"] == "category" for e in errors))

    def test_validate_expense_data_chapter_required(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        cat = self._make_expense_category(name_hint="Travel")
        errors = validate_expense_data(
            {
                "description": "x",
                "amount": 10,
                "expense_date": "2025-01-01",
                "organization_type": "Chapter",
                "category": cat.name,
            },
            1,
        )
        self.assertTrue(any(e["field"] == "chapter" for e in errors))

    def test_validate_expense_data_bad_receipt_type(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            validate_expense_data,
        )

        cat = self._make_expense_category(name_hint="Travel")
        errors = validate_expense_data(
            {
                "description": "x",
                "amount": 10,
                "expense_date": "2025-01-01",
                "organization_type": "National",
                "category": cat.name,
                "receipt_attachment": {"file_name": "virus.exe"},
            },
            1,
        )
        self.assertTrue(any(e["field"] == "receipt_attachment" for e in errors))

    # -- theme settings fallback --

    def test_get_theme_settings_returns_object(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
            get_theme_settings,
        )

        theme = get_theme_settings()
        # Either an Owl Theme Settings single or the fallback _dict; both expose
        # the keys the templates read.
        self.assertTrue(hasattr(theme, "background_color"))


# ---------------------------------------------------------------------------
# 3. native_expense_helpers
# ---------------------------------------------------------------------------
class TestNativeExpenseHelpersDeep(_ExpenseFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="NativeHelp", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    # -- get_volunteer_expense_approver: real volunteer (no assignments) --

    def test_get_approver_real_volunteer(self):
        from verenigingen.services.volunteer.native_expense_helpers import (
            get_volunteer_expense_approver,
        )

        approver = get_volunteer_expense_approver(self.volunteer.name)
        # Returns a non-empty approver string (Administrator fallback at minimum).
        self.assertTrue(approver)

    # -- update_employee_approver: volunteer without employee_id --

    def test_update_employee_approver_no_employee_id(self):
        from verenigingen.services.volunteer.native_expense_helpers import (
            update_employee_approver,
        )

        # Pass the real Volunteer doc; it has no employee_id -> returns None.
        self.assertFalse(self.volunteer.employee_id)
        self.assertIsNone(update_employee_approver(self.volunteer))

    def test_update_employee_approver_employee_missing(self):
        from verenigingen.services.volunteer.native_expense_helpers import (
            update_employee_approver,
        )

        # Point at a non-existent employee id -> the exists() guard returns None.
        self.volunteer.employee_id = "EMP-DOES-NOT-EXIST"
        self.assertIsNone(update_employee_approver(self.volunteer))

    # -- validate_expense_approver_setup: shape + literal-format bug --

    def test_validate_setup_shape(self):
        from verenigingen.services.volunteer.native_expense_helpers import (
            validate_expense_approver_setup,
        )

        result = validate_expense_approver_setup()
        self.assertIn("valid", result)
        self.assertIsInstance(result["issues"], list)
        self.assertIsInstance(result["employees_without_approvers"], list)

    def test_validate_setup_issue_strings_are_formatted(self):
        """Regression: issue strings must interpolate counts, not emit literal
        '{len(...)}'.  Prior to the fix these were plain strings missing the
        f-prefix.  Seed a real Employee with NO expense_approver linked to a
        Volunteer so the 'employees_without_approvers' branch actually runs and
        produces an issue string -- otherwise the assertion loop is vacuous."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            validate_expense_approver_setup,
        )

        emp = self._make_employee(expense_approver=None)
        frappe.db.set_value("Volunteer", self.volunteer.name, "employee_id", emp.name)

        result = validate_expense_approver_setup()

        # The seeded employee-without-approver must surface a diagnostic issue.
        self.assertTrue(
            result["employees_without_approvers"],
            "Seeded approver-less employee should appear in the validation result",
        )
        self.assertTrue(result["issues"], "A non-empty issues list is expected")

        # Every issue string must have its counts interpolated (no placeholders),
        # and at least one must carry the real digit count.
        for issue in result["issues"]:
            self.assertNotIn("{len(", issue, f"Unformatted placeholder leaked: {issue!r}")
            self.assertNotIn("{", issue, f"Unformatted placeholder leaked: {issue!r}")
        self.assertTrue(
            any("employees without expense approvers" in i and i[0].isdigit() for i in result["issues"]),
            f"Expected an interpolated count in: {result['issues']!r}",
        )

    # -- is_native_expense_system_ready --

    def test_is_ready_returns_bool(self):
        from verenigingen.services.volunteer.native_expense_helpers import (
            is_native_expense_system_ready,
        )

        self.assertIsInstance(is_native_expense_system_ready(), bool)

    # -- refresh_all_expense_approvers: message must be formatted --

    def test_refresh_all_message_formatted(self):
        """Regression: the success message must interpolate counts, not return
        the literal '{updated_count}'/'{error_count}' placeholders."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            refresh_all_expense_approvers,
        )

        result = refresh_all_expense_approvers()
        self.assertTrue(result["success"])
        self.assertNotIn("{updated_count}", result["message"])
        self.assertNotIn("{error_count}", result["message"])
        # The interpolated counts should appear as their integer values.
        self.assertIn(str(result["updated"]), result["message"])
