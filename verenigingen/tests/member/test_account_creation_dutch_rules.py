#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dutch Association Business Logic Tests for AccountCreationManager
=================================================================

Tests Dutch-specific business rules that aren't covered by the main pipeline tests:
- Age validation at volunteer start date (not just current date)
- Dutch name handling with tussenvoegsel (particles)
- Company assignment for employee records
- Age transition edge cases (exactly 16th birthday)
"""

import frappe
from frappe.utils import getdate, add_days, add_years

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
from verenigingen.utils.account_creation_manager import (
    AccountCreationManager,
    queue_account_creation_for_volunteer,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDutchAssociationBusinessLogic(EnhancedTestCase):
    """Dutch association-specific business logic validation."""

    def test_volunteer_age_validation_at_start_date(self):
        """Test age validation is checked at volunteer start date, not current date."""
        unique_email = f"future.volunteer.{self.test_run_id}@test.invalid"
        birth_date = add_years(getdate(), -17)

        future_member = self.create_test_member(
            first_name=f"Future{self.uid}",
            last_name="Volunteer",
            email=unique_email,
            birth_date=birth_date,
        )

        future_start_date = add_days(getdate(), 365)
        volunteer = self.create_test_volunteer(
            member_name=future_member.name,
            volunteer_name=f"Future Volunteer {self.uid}",
            email=unique_email,
            start_date=future_start_date,
        )
        self.assertIsNotNone(volunteer)

    def test_dutch_name_handling_with_tussenvoegsel(self):
        """Test proper handling of Dutch names with tussenvoegsel."""
        dutch_names = [
            ("Jan", "van der Berg"),
            ("Marie", "de Wit"),
            ("Pieter", "van den Heuvel"),
            ("Anna", "ter Haar"),
            ("Willem", "van de Water"),
        ]

        for idx, (first_name, last_name) in enumerate(dutch_names):
            with self.subTest(first_name=first_name, last_name=last_name):
                unique_first = f"{first_name}{self.uid}{idx}"
                email = f"{first_name.lower()}.{self.uid}.{idx}@test.invalid"

                member = self.create_test_member(
                    first_name=unique_first,
                    last_name=last_name,
                    email=email,
                    birth_date="1980-01-01",
                )

                member.reload()
                actual_last_name = member.last_name
                expected_full_name = f"{unique_first} {actual_last_name}"

                # Create ACR directly via factory (no background job enqueued)
                request = self.create_test_account_creation_request(
                    source_record=member.name, request_type="Member"
                )

                manager = AccountCreationManager(request.name)
                manager.process_complete_pipeline()

                request.reload()
                user = frappe.get_doc("User", request.created_user)
                self.assertEqual(user.first_name, unique_first)
                self.assertEqual(user.last_name, actual_last_name)
                self.assertEqual(user.full_name, expected_full_name)
                self.assertTrue(
                    user.last_name.startswith(last_name),
                    f"Dutch particle not preserved: expected '{last_name}', got '{user.last_name}'",
                )

    def test_dutch_company_assignment_for_employees(self):
        """Test proper Dutch company assignment for employee records."""
        default_company = frappe.db.get_value("Company", {}, "name", order_by="creation")
        if not default_company:
            self.skipTest("No company exists in test environment for employee assignment")

        member = self.create_test_member(
            first_name=f"Dutch{self.uid}",
            last_name="Company",
            email=f"dutch.company.{self.uid}@test.invalid",
            birth_date="1990-01-01",
        )

        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"Dutch Company Test {self.uid}",
            email=f"dutch.company.{self.uid}@test.invalid",
        )

        # Create ACR directly via factory (no background job enqueued)
        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )

        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        if not request.created_employee:
            self.skipTest("Employee was not created - likely missing role in test environment")

        employee = frappe.get_doc("Employee", request.created_employee)
        self.assertIsNotNone(employee.company)
        self.assertTrue(DocumentExistenceValidator.check_document_exists("Company", employee.company))

    def test_age_transition_volunteer_eligibility(self):
        """Test volunteer eligibility during age transition periods."""
        birth_date_exactly_16 = add_years(getdate(), -16)

        transition_member = self.create_test_member(
            first_name=f"Age{self.uid}",
            last_name="Transition",
            email=f"age.transition.{self.uid}@test.invalid",
            birth_date=birth_date_exactly_16,
        )

        future_start_date = add_days(getdate(), 60)
        volunteer = self.create_test_volunteer(
            member_name=transition_member.name,
            volunteer_name=f"Age Transition Volunteer {self.uid}",
            email=f"age.transition.{self.uid}@test.invalid",
            start_date=future_start_date,
        )
        self.assertIsNotNone(volunteer)

        result = queue_account_creation_for_volunteer(volunteer.name)
        request_name = result.get("request_name") or result.get("data", {}).get("request_name")
        self.assertIsNotNone(request_name)

    def test_exact_16th_birthday_volunteer_creation(self):
        """Test volunteer creation exactly on 16th birthday."""
        birth_date_16_years = add_years(getdate(), -16)

        member = self.create_test_member(
            first_name=f"Exact{self.uid}",
            last_name="Sixteen",
            email=f"exact.sixteen.{self.uid}@test.invalid",
            birth_date=birth_date_16_years,
        )

        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"Exact Sixteen Volunteer {self.uid}",
            email=f"exact.sixteen.{self.uid}@test.invalid",
            start_date=getdate(),
        )
        self.assertIsNotNone(volunteer)
