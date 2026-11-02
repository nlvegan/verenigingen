# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Membership Application API functions
Tests the whitelisted API functions for membership applications

submit_application returns an OperationResult envelope (it never raises for
validation problems):
    {"success": True, "data": {"status": "confirmation_sent"}, ...}
    {"success": False, "error": {"message", "errors": [...]}, ...}

It is called with keyword arguments (def submit_application(**kwargs)).
"""


import json
from unittest import mock

import frappe
from frappe.utils import add_days, today

from verenigingen.api import membership_application
from verenigingen.services.member.approval.application_helpers import get_form_data
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.query_counter import count_queries as _count_queries


def _unique(prefix):
    return f"{prefix}_{frappe.generate_hash(length=8)}"


class TestMembershipApplicationAPI(VereningingenUnitTestCase):
    """Test Membership Application API functions"""

    def _valid_application_data(self, **overrides):
        suffix = frappe.generate_hash(length=8)
        data = {
            "first_name": "Test",
            "last_name": f"Applicant {suffix}",
            "email": f"applicant_{suffix}@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 25),  # 25 years old
            "address_line1": "Test Street 123",
            "postal_code": "1234AB",
            "city": "Amsterdam",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "payment_method": "Bank Transfer",
            "newsletter_opt_in": 1,
        }
        data.update(overrides)
        return data

    def test_submit_application_valid_data(self):
        """A valid application is staged: no Member exists until it is confirmed and approved (#1765)."""
        application_data = self._valid_application_data()

        result = membership_application.submit_application(**application_data)

        self.assertTrue(result["success"], msg=result.get("error"))
        self.assertEqual(result["data"], {"status": "confirmation_sent"})
        self.assertFalse(frappe.db.exists("Member", {"email": application_data["email"]}))
        rows = frappe.get_all(
            "Membership Application Submission",
            {"email": application_data["email"]},
            ["name", "status", "source"],
        )
        self.assertEqual([(r.status, r.source) for r in rows], [("Unconfirmed", "Full Form")])
        self.track_doc("Membership Application Submission", rows[0].name)

    def test_submit_application_duplicate_email(self):
        """A second application with the same email is staged too; confirming the second one
        supersedes the first (see test_application_record)."""
        email = _unique("existing") + "@example.com"

        for _attempt in range(2):
            result = membership_application.submit_application(**self._valid_application_data(email=email))
            self.assertTrue(result["success"], msg=result.get("error"))

        rows = frappe.get_all("Membership Application Submission", {"email": email}, pluck="name")
        self.assertEqual(len(rows), 2)
        for name in rows:
            self.track_doc("Membership Application Submission", name)

    def test_submit_application_special_characters(self):
        """Special characters in a name survive into the stored payload unchanged."""
        application_data = self._valid_application_data(first_name="José", last_name="O'Brien-García")

        result = membership_application.submit_application(**application_data)
        self.assertTrue(result["success"], msg=result.get("error"))

        row = frappe.get_all(
            "Membership Application Submission", {"email": application_data["email"]}, ["name", "payload"]
        )[0]
        self.track_doc("Membership Application Submission", row.name)
        payload = json.loads(row.payload)
        self.assertEqual((payload["first_name"], payload["last_name"]), ("José", "O'Brien-García"))

    def test_submit_application_missing_required_fields(self):
        """Test submitting application with missing required fields"""
        application_data = self._valid_application_data()
        del application_data["email"]

        result = membership_application.submit_application(**application_data)

        self.assertFalse(result["success"])
        error = result.get("error", {})
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        self.assertIn("missing required fields", message.lower())

    def test_submit_application_invalid_email_format(self):
        """Test submitting application with invalid email format"""
        application_data = self._valid_application_data(email="invalid-email-format")

        result = membership_application.submit_application(**application_data)

        self.assertFalse(result["success"])
        error = result.get("error", {})
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        self.assertIn("email", message.lower())

    def test_validate_postal_code(self):
        """Test postal code validation API"""
        result = membership_application.validate_postal_code("1234AB", "Netherlands")

        # validate_postal_code returns an OperationResult envelope
        self.assertIn("success", result)
        self.assertTrue(result["success"], msg=result.get("error"))

    def test_get_application_form_data_uses_cache_on_repeat_calls(self):
        """#439: get_application_form_data is `allow_guest=True` and, measured
        on test_site_1, issues ~11 SQL queries per Membership Type (239
        queries / 21 types; confirmed linear -- 895 queries / 81 types after
        adding 60 more). Every anonymous visitor to the application form pays
        this, unauthenticated and uncached, and the data it returns
        (membership types/chapters/volunteer areas/countries) is identical
        for every guest. The fix caches the response.

        This pins the *shape* -- a repeat call must be a small, near-constant
        cost, dramatically cheaper than the first -- rather than an exact
        query count that would rot as Membership Type fixtures accumulate or
        drain (CLAUDE.md: shared/leaked fixtures already make raw counts
        unstable across CI shards).
        """
        cache_key = membership_application.FORM_DATA_CACHE_KEY

        # Warm DocType meta / schema caches on tables get_form_data reads,
        # WITHOUT touching the fix's own cache key -- otherwise the "first"
        # (uncached) call below would already be a cache hit, and a cold
        # information_schema/table_columns lookup would also get misattributed
        # to the code under test rather than to warmup.
        # frappe.db.count(), not get_all(..., limit=1): the latter picks an
        # arbitrary existing row, which is exactly the order-dependence shape
        # scan_order_dependence.py's REUSE check exists to block (a test's
        # behaviour must not depend on what a preceding file in the shard left
        # in the DB). count() only needs the table to exist to warm the schema
        # cache -- it never reads a specific row.
        frappe.db.get_value("Membership Type", {"is_active": 1}, "name")
        frappe.db.count("Chapter")
        frappe.db.count("Country")
        frappe.db.count("Volunteer Interest Category")

        frappe.cache().delete_value(cache_key)
        self.addCleanup(frappe.cache().delete_value, cache_key)

        with _count_queries() as first_call:
            result_first = membership_application.get_application_form_data()
        self.assertTrue(result_first["success"], msg=result_first.get("error"))

        # Drop the in-process local-cache copy WITHOUT clearing Redis. A real
        # HTTP request gets a fresh frappe.local.cache (it's request-scoped),
        # so if this test only exercised that in-process dict, it would stay
        # green even with Redis unreachable -- which would not be the fix
        # #439 actually needs (every anonymous request is a separate process
        # in production). Forcing a Redis round-trip here proves the cache
        # survives a request boundary.
        frappe.local.cache.pop(frappe.cache().make_key(cache_key), None)

        with _count_queries() as second_call:
            result_second = membership_application.get_application_form_data()
        self.assertTrue(result_second["success"], msg=result_second.get("error"))

        # Compare against a genuinely fresh, uncached computation of the
        # underlying data -- not identity equality of a shared cached object
        # (get_cached_form_data returns a deep copy specifically so this
        # comparison is meaningful).
        fresh = get_form_data()
        self.assertTrue(result_second["data"]["membership_types"])
        self.assertEqual(
            result_second["data"]["membership_types"], fresh["membership_types"]
        )

        self.assertLessEqual(
            len(second_call.queries),
            15,
            msg=(
                "expected a cached repeat call to cost a small, constant "
                f"number of queries; got {len(second_call.queries)}: "
                + "\n".join(second_call.queries)
            ),
        )
        self.assertGreater(
            len(first_call.queries),
            len(second_call.queries) * 3,
            msg=(
                f"expected the first (uncached) call ({len(first_call.queries)} "
                f"queries) to cost meaningfully more than the cached repeat "
                f"call ({len(second_call.queries)} queries) -- caching does "
                "not appear to be working"
            ),
        )

    def test_get_cached_form_data_does_not_cache_a_failed_result(self):
        """A cached-but-wrong result would be served to every guest for the
        full TTL. get_form_data() catches failures per-section and can
        return success=True with empty lists on a transient error in one
        section -- caching must gate on the payload actually being
        non-empty, not on that (forced) success flag alone.
        """
        cache_key = membership_application.FORM_DATA_CACHE_KEY
        frappe.cache().delete_value(cache_key)
        self.addCleanup(frappe.cache().delete_value, cache_key)

        with mock.patch.object(
            membership_application,
            "get_form_data",
            return_value={"success": False, "error": "boom", "membership_types": []},
        ):
            result = membership_application.get_cached_form_data()

        self.assertTrue(result["success"])  # normalized for the envelope
        self.assertIsNone(
            frappe.cache().get_value(cache_key),
            msg="a failed/empty result must not be cached",
        )
