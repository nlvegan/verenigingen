"""Coverage sweep for verenigingen/utils/validation_utilities.py.

Targets the under-covered surface: DateRangeValidator, the historical-date
window validator, QueryBuilder filter generation / active-record queries, and
DocumentExistenceValidator. Real-DB integration where the code touches the DB;
filter-generation is asserted against the module's own status config and
verified by running the generated filters against real fixtures.
"""

from datetime import date

import frappe
from dateutil.relativedelta import relativedelta
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation_utilities import (
    AgeValidator,
    DateRangeValidator,
    DocumentExistenceValidator,
    QueryBuilder,
    ValidationError,
    calculate_age,
    count_active_records,
    get_active_records_filters,
    get_all_active_records,
    validate_date_range,
    validate_document_exists,
    validate_historical_date_window,
    validate_member_age,
    validate_minimum_age,
    validate_volunteer_age,
)


class TestDateRangeValidator(EnhancedTestCase):
    def test_valid_future_range(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), 1), add_days(today(), 10), throw_on_error=False
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["duration_days"], 9)

    def test_end_before_start_rejected(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), 10), add_days(today(), 1), throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("after start date", result["message"])

    def test_end_before_start_throws(self):
        with self.assertRaises(ValidationError):
            DateRangeValidator.validate_date_range(
                add_days(today(), 10), add_days(today(), 1), throw_on_error=True
            )

    def test_equal_dates_rejected_by_default(self):
        d = add_days(today(), 5)
        result = DateRangeValidator.validate_date_range(d, d, throw_on_error=False)
        self.assertFalse(result["valid"])

    def test_equal_dates_allowed_when_flag_set(self):
        d = add_days(today(), 5)
        result = DateRangeValidator.validate_date_range(
            d, d, allow_equal_dates=True, throw_on_error=False
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["duration_days"], 0)

    def test_allow_equal_but_end_before_start_rejected(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), 5), add_days(today(), 1), allow_equal_dates=True, throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("cannot be before", result["message"])

    def test_past_start_rejected_by_default(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), -5), add_days(today(), 5), throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("past", result["message"])

    def test_past_start_allowed_when_flag_set(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), -5), add_days(today(), 5), allow_past_start=True, throw_on_error=False
        )
        self.assertTrue(result["valid"])

    def test_min_duration_enforced(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), 1), add_days(today(), 3), min_duration_days=10, throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("at least", result["message"])

    def test_max_duration_enforced(self):
        result = DateRangeValidator.validate_date_range(
            add_days(today(), 1), add_days(today(), 100), max_duration_days=10, throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("cannot exceed", result["message"])

    # --- boolean comparison helpers --------------------------------------
    def test_is_date_today_or_future(self):
        self.assertTrue(DateRangeValidator.is_date_today_or_future(today()))
        self.assertTrue(DateRangeValidator.is_date_today_or_future(add_days(today(), 1)))
        self.assertFalse(DateRangeValidator.is_date_today_or_future(add_days(today(), -1)))

    def test_is_date_before(self):
        self.assertTrue(DateRangeValidator.is_date_before(add_days(today(), -1), today()))
        self.assertFalse(DateRangeValidator.is_date_before(today(), add_days(today(), -1)))

    def test_is_date_in_past(self):
        self.assertTrue(DateRangeValidator.is_date_in_past(add_days(today(), -1)))
        self.assertFalse(DateRangeValidator.is_date_in_past(today()))

    def test_is_date_today_or_past(self):
        self.assertTrue(DateRangeValidator.is_date_today_or_past(today()))
        self.assertTrue(DateRangeValidator.is_date_today_or_past(add_days(today(), -1)))
        self.assertFalse(DateRangeValidator.is_date_today_or_past(add_days(today(), 1)))

    def test_is_date_today_or_before(self):
        self.assertTrue(DateRangeValidator.is_date_today_or_before(today(), today()))
        self.assertTrue(DateRangeValidator.is_date_today_or_before(add_days(today(), -1), today()))
        self.assertFalse(DateRangeValidator.is_date_today_or_before(add_days(today(), 1), today()))

    def test_is_date_in_future(self):
        self.assertTrue(DateRangeValidator.is_date_in_future(add_days(today(), 1)))
        self.assertFalse(DateRangeValidator.is_date_in_future(today()))

    def test_is_date_today_or_after(self):
        self.assertTrue(DateRangeValidator.is_date_today_or_after(today(), today()))
        self.assertTrue(DateRangeValidator.is_date_today_or_after(add_days(today(), 1), today()))
        self.assertFalse(DateRangeValidator.is_date_today_or_after(add_days(today(), -1), today()))

    def test_helpers_accept_date_objects(self):
        # The is_date_* helpers branch on isinstance(str); pass real date objects.
        self.assertTrue(DateRangeValidator.is_date_in_future(date.today() + relativedelta(days=2)))
        self.assertTrue(DateRangeValidator.is_date_before(date(2000, 1, 1), date(2001, 1, 1)))


class TestHistoricalDateWindow(EnhancedTestCase):
    def test_within_window_valid(self):
        result = DateRangeValidator.validate_historical_date_window(
            add_days(today(), -100), max_years_past=10, max_days_future=0, throw_on_error=False
        )
        self.assertTrue(result["valid"])

    def test_too_far_in_past_rejected(self):
        result = DateRangeValidator.validate_historical_date_window(
            add_days(today(), -365 * 12), max_years_past=10, throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("years in the past", result["message"])

    def test_too_far_in_past_throws(self):
        with self.assertRaises(ValidationError):
            DateRangeValidator.validate_historical_date_window(
                add_days(today(), -365 * 12), max_years_past=10, throw_on_error=True
            )

    def test_too_far_in_future_rejected(self):
        result = DateRangeValidator.validate_historical_date_window(
            add_days(today(), 60), max_days_future=30, throw_on_error=False
        )
        self.assertFalse(result["valid"])
        self.assertIn("days in the future", result["message"])

    def test_no_constraints_always_valid(self):
        result = DateRangeValidator.validate_historical_date_window(
            add_days(today(), -365 * 50), throw_on_error=False
        )
        self.assertTrue(result["valid"])

    def test_field_name_humanized_in_message(self):
        result = DateRangeValidator.validate_historical_date_window(
            add_days(today(), 60), max_days_future=0, field_name="sign_date", throw_on_error=False
        )
        self.assertIn("Sign Date", result["message"])


class TestQueryBuilderFilters(EnhancedTestCase):
    """Filter generation, asserted against the module's status config and then
    verified by running the filters against a real fixture."""

    def test_active_filters_single_active_value(self):
        # Member: single active value "Active", no docstatus.
        filters = QueryBuilder.get_active_records_filters("Member")
        self.assertEqual(filters, {"status": "Active"})

    def test_active_filters_multi_active_value_uses_in(self):
        # Sales Invoice: multiple active values -> ["in", [...]] + docstatus.
        filters = QueryBuilder.get_active_records_filters("Sales Invoice")
        self.assertEqual(filters["status"][0], "in")
        self.assertEqual(filters["docstatus"], 1)

    def test_active_filters_include_draft_drops_docstatus(self):
        filters = QueryBuilder.get_active_records_filters("Sales Invoice", include_draft=True)
        self.assertNotIn("docstatus", filters)

    def test_active_filters_merge_additional(self):
        filters = QueryBuilder.get_active_records_filters("Member", {"chapter": "X"})
        self.assertEqual(filters["status"], "Active")
        self.assertEqual(filters["chapter"], "X")

    def test_active_filters_status_only_doctype(self):
        # Payment Entry: status_field None -> docstatus only.
        filters = QueryBuilder.get_active_records_filters("Payment Entry")
        self.assertNotIn("status", filters)
        self.assertEqual(filters["docstatus"], 1)

    def test_active_filters_unknown_doctype_fallback(self):
        # User has a docstatus column but no status -> falls back to docstatus=1.
        filters = QueryBuilder.get_active_records_filters("User")
        self.assertEqual(filters.get("docstatus"), 1)
        self.assertNotIn("status", filters)

    def test_inactive_filters_single_value(self):
        # SEPA Mandate inactive set has 3 entries -> ["in", [...]].
        filters = QueryBuilder.get_inactive_records_filters("SEPA Mandate")
        self.assertEqual(filters["status"][0], "in")

    def test_inactive_filters_membership_includes_cancelled_docstatus(self):
        filters = QueryBuilder.get_inactive_records_filters("Membership")
        self.assertEqual(filters["status"][0], "in")
        self.assertEqual(filters["docstatus"], ["in", [0, 2]])

    def test_inactive_filters_unknown_doctype_fallback(self):
        # ToDo is not in DOCTYPE_STATUS_CONFIG but has a "status" column, so the
        # fallback applies status != "Active".
        filters = QueryBuilder.get_inactive_records_filters("ToDo")
        self.assertEqual(filters.get("status"), ["!=", "Active"])

    def test_get_all_active_records_runs_against_fixture(self):
        member = self.create_test_member()
        records = QueryBuilder.get_all_active_records(
            "Member", fields=["name", "status"], additional_filters={"name": member.name}
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], member.name)
        self.assertEqual(records[0]["status"], "Active")

    def test_get_all_active_records_filters_alias(self):
        member = self.create_test_member()
        # Backward-compat: pass via 'filters' alias instead of additional_filters.
        records = QueryBuilder.get_all_active_records("Member", filters={"name": member.name})
        self.assertEqual(len(records), 1)

    def test_inactive_member_excluded_from_active_query(self):
        member = self.create_test_member()
        member.status = "Suspended"
        member.save()
        records = QueryBuilder.get_all_active_records("Member", additional_filters={"name": member.name})
        self.assertEqual(len(records), 0, "Suspended member must not appear in active query")

    def test_count_active_records_matches_independent(self):
        member = self.create_test_member()
        # Scope by name so the count is deterministic on any site.
        count = QueryBuilder.count_active_records("Member", {"name": member.name})
        self.assertEqual(count, 1)
        independent = frappe.db.count("Member", {"name": member.name, "status": "Active"})
        self.assertEqual(count, independent)

    def test_exists_active_record_true_and_false(self):
        member = self.create_test_member()
        self.assertTrue(QueryBuilder.exists_active_record("Member", member.name))
        member.status = "Quit"
        member.save()
        self.assertFalse(QueryBuilder.exists_active_record("Member", member.name))


class TestDocumentExistenceValidator(EnhancedTestCase):
    def test_validate_exists_true(self):
        member = self.create_test_member()
        self.assertTrue(DocumentExistenceValidator.validate_document_exists("Member", member.name))

    def test_validate_missing_throws(self):
        with self.assertRaises(frappe.DoesNotExistError):
            DocumentExistenceValidator.validate_document_exists("Member", "NO-SUCH-MEMBER-0001")

    def test_validate_missing_no_throw_returns_false(self):
        self.assertFalse(
            DocumentExistenceValidator.validate_document_exists(
                "Member", "NO-SUCH-MEMBER-0001", throw_on_error=False
            )
        )

    def test_validate_missing_custom_error(self):
        with self.assertRaises(frappe.DoesNotExistError) as ctx:
            DocumentExistenceValidator.validate_document_exists(
                "Member", "NO-SUCH-MEMBER-0001", custom_error="my custom message"
            )
        self.assertIn("my custom message", str(ctx.exception))

    def test_check_document_exists(self):
        member = self.create_test_member()
        self.assertTrue(DocumentExistenceValidator.check_document_exists("Member", member.name))
        self.assertFalse(DocumentExistenceValidator.check_document_exists("Member", "NOPE-0001"))

    def test_validate_active_document_exists_true(self):
        member = self.create_test_member()
        self.assertTrue(
            DocumentExistenceValidator.validate_active_document_exists("Member", member.name)
        )

    def test_validate_active_document_inactive_throws(self):
        member = self.create_test_member()
        member.status = "Quit"
        member.save()
        with self.assertRaises(frappe.DoesNotExistError):
            DocumentExistenceValidator.validate_active_document_exists("Member", member.name)

    def test_validate_active_document_inactive_no_throw(self):
        member = self.create_test_member()
        member.status = "Quit"
        member.save()
        self.assertFalse(
            DocumentExistenceValidator.validate_active_document_exists(
                "Member", member.name, throw_on_error=False
            )
        )


class TestConvenienceFunctions(EnhancedTestCase):
    """Module-level convenience wrappers."""

    def test_calculate_age_wrapper(self):
        birth = date.today() - relativedelta(years=30)
        self.assertAlmostEqual(calculate_age(birth), 30, places=1)

    def test_validate_minimum_age_pass_and_fail(self):
        ok, age = validate_minimum_age(date.today() - relativedelta(years=20), min_age=18)
        self.assertTrue(ok)
        self.assertAlmostEqual(age, 20, places=1)
        fail, _age = validate_minimum_age(date.today() - relativedelta(years=10), min_age=18)
        self.assertFalse(fail)

    def test_validate_member_age_wrapper(self):
        result = validate_member_age(date.today() - relativedelta(years=25), "Regular")
        self.assertTrue(result.is_valid)

    def test_validate_volunteer_age_wrapper(self):
        result = validate_volunteer_age(date.today() - relativedelta(years=25))
        self.assertTrue(result.is_valid)
        too_young = validate_volunteer_age(date.today() - relativedelta(years=10))
        self.assertFalse(too_young.is_valid)

    def test_validate_date_range_wrapper(self):
        result = validate_date_range(
            add_days(today(), 1), add_days(today(), 5), throw_on_error=False
        )
        self.assertTrue(result["valid"])

    def test_validate_historical_date_window_wrapper(self):
        result = validate_historical_date_window(
            add_days(today(), -100), max_years_past=10, throw_on_error=False
        )
        self.assertTrue(result["valid"])

    def test_get_active_records_filters_wrapper(self):
        self.assertEqual(get_active_records_filters("Member"), {"status": "Active"})

    def test_get_all_active_records_wrapper(self):
        member = self.create_test_member()
        records = get_all_active_records("Member", additional_filters={"name": member.name})
        self.assertEqual(len(records), 1)

    def test_count_active_records_wrapper(self):
        member = self.create_test_member()
        self.assertEqual(count_active_records("Member", {"name": member.name}), 1)

    def test_validate_document_exists_wrapper(self):
        member = self.create_test_member()
        self.assertTrue(validate_document_exists("Member", member.name))
        with self.assertRaises(frappe.DoesNotExistError):
            validate_document_exists("Member", "NOPE-0001")


class TestAgeValidatorExtraBranches(EnhancedTestCase):
    """Branches not covered by the existing test_validation_utilities.py."""

    def test_membership_type_adult_uses_voting_context(self):
        # "adult" routes to the voting context (different error wording).
        result = AgeValidator.validate_membership_age_for_type(
            date.today() - relativedelta(years=10), "Adult", throw_on_error=False
        )
        self.assertFalse(result.is_valid)

    def test_under_18_warning_for_regular_membership(self):
        # 17yo passes a min-16 rule but earns the under-18 parental-consent warning.
        result = AgeValidator.validate_age(
            date.today() - relativedelta(years=17), context="membership", throw_on_error=False
        )
        self.assertTrue(result.is_valid)
        self.assertIsNotNone(result.warning)
        self.assertIn("under 18", result.warning.lower())

    def test_over_100_warning(self):
        # 105yo is under the 120 max for membership but triggers the >100 warning.
        result = AgeValidator.validate_age(
            date.today() - relativedelta(years=105), context="membership", throw_on_error=False
        )
        self.assertTrue(result.is_valid)
        self.assertIn("over 100", result.warning.lower())

    def test_validate_age_throws_on_future_date_even_when_no_throw_requested_for_range(self):
        # calculate_age raises on a future birth date; with throw_on_error=False
        # validate_age catches it and returns an invalid result.
        result = AgeValidator.validate_age(
            add_days(today(), 365), context="membership", throw_on_error=False
        )
        self.assertFalse(result.is_valid)
        self.assertIn("future", result.message.lower())

    def test_unknown_context_falls_back_to_membership_min_age(self):
        # An unknown context maps to the membership setting field.
        min_age = AgeValidator._get_configurable_min_age("totally_unknown_context")
        expected = int(
            frappe.db.get_single_value("Verenigingen Settings", "minimum_membership_age")
        )
        self.assertEqual(min_age, expected)
