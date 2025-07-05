# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Test Personas for Verenigingen Testing
Provides standard test personas as defined in the test suite plan
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.factories import TestDataBuilder


class TestPersonas:
    """Standard test personas for consistent testing scenarios"""

    @staticmethod
    def create_happy_path_hannah():
        """
        "Happy Path Hannah" - Everything works perfectly
        A member who goes through the entire process smoothly
        """
        builder = TestDataBuilder()

        # Create perfect scenario member
        test_data = (
            builder.with_chapter("Amsterdam")
            .with_member(
                first_name="Hannah",
                last_name="Happypath",
                email="hannah.happypath@example.com",
                contact_number="+31612345678",
                payment_method="SEPA Direct Debit",
                iban="NL91ABNA0417164300",
                bank_account_name="Hannah Happypath",
                status="Active",
            )
            .with_membership("Annual", payment_method="SEPA Direct Debit")
            .with_volunteer_profile()
            .with_team_assignment("Events Team", role="Event Coordinator")
            .with_expense(50.00, "Event supplies")
            .build()
        )

        return {
            **test_data,
            "persona": "Happy Path Hannah",
            "description": "Member with perfect workflow execution",
            "builder": builder,
        }

    @staticmethod
    def create_payment_problem_peter():
        """
        "Payment Problem Peter" - Various payment issues
        A member who encounters payment failures and recovery scenarios
        """
        builder = TestDataBuilder()

        test_data = (
            builder.with_chapter("Rotterdam")
            .with_member(
                first_name="Peter",
                last_name="Paymentproblem",
                email="peter.paymentproblem@example.com",
                contact_number="+31687654321",
                payment_method="SEPA Direct Debit",
                iban="NL01BANK0000000001",  # Problem IBAN
                bank_account_name="Peter Paymentproblem",
                status="Active",
            )
            .with_membership("Monthly", payment_method="SEPA Direct Debit")
            .build()
        )

        # Add payment failure history
        member = test_data["member"]

        # Create failed payment records
        try:
            for i in range(3):
                failure_log = frappe.get_doc(
                    {
                        "doctype": "Payment Failure Log",
                        "member": member.name,
                        "failure_date": add_days(today(), -30 + i * 10),
                        "failure_reason": f"Insufficient funds - attempt {i + 1}",
                        "amount": 25.00,
                        "retry_count": i,
                    }
                )
                failure_log.insert(ignore_permissions=True)
        except Exception:
            pass  # Doctype may not exist

        return {
            **test_data,
            "persona": "Payment Problem Peter",
            "description": "Member with recurring payment issues",
            "builder": builder,
        }

    @staticmethod
    def create_volunteer_victor():
        """
        "Volunteer Victor" - Active volunteer with expenses
        A highly active volunteer with multiple assignments and expenses
        """
        builder = TestDataBuilder()

        test_data = (
            builder.with_chapter("Utrecht")
            .with_member(
                first_name="Victor",
                last_name="Volunteer",
                email="victor.volunteer@example.com",
                contact_number="+31698765432",
                payment_method="Bank Transfer",
                status="Active",
            )
            .with_membership("Annual", payment_method="Bank Transfer")
            .with_volunteer_profile()
            .with_team_assignment("Events Team", role="Team Leader")
            .with_team_assignment("Outreach Team", role="Community Liaison")
            .with_expense(75.00, "Travel to community events")
            .with_expense(125.00, "Event supplies and materials")
            .with_expense(45.00, "Volunteer training materials")
            .build()
        )

        # Add volunteer activities
        volunteer = test_data["volunteer"]
        activities = [
            {
                "activity_name": "Community Outreach Event",
                "hours": 8.0,
                "activity_date": add_days(today(), -10),
                "description": "Organized community outreach event",
            },
            {
                "activity_name": "Volunteer Training Session",
                "hours": 4.0,
                "activity_date": add_days(today(), -5),
                "description": "Led volunteer training session",
            },
            {
                "activity_name": "Fundraising Campaign",
                "hours": 12.0,
                "activity_date": add_days(today(), -15),
                "description": "Coordinated fundraising campaign",
            },
        ]

        created_activities = []
        for activity_data in activities:
            activity = frappe.get_doc(
                {
                    "doctype": "Volunteer Activity",
                    "volunteer": volunteer.name,
                    **activity_data,
                    "status": "Completed",
                }
            )
            activity.insert(ignore_permissions=True)
            created_activities.append(activity)

        return {
            **test_data,
            "activities": created_activities,
            "persona": "Volunteer Victor",
            "description": "Highly active volunteer with multiple assignments",
            "builder": builder,
        }

    @staticmethod
    def create_terminated_tom():
        """
        "Terminated Tom" - Goes through termination process
        A member who goes through the complete termination workflow
        """
        builder = TestDataBuilder()

        test_data = (
            builder.with_chapter("Den Haag")
            .with_member(
                first_name="Tom",
                last_name="Terminated",
                email="tom.terminated@example.com",
                contact_number="+31611111111",
                payment_method="Bank Transfer",
                status="Active",
            )
            .with_membership(
                "Annual",
                payment_method="Bank Transfer",
                start_date=add_days(today(), -200),
                end_date=add_days(today(), 165),
            )
            .build()
        )

        # Prepare for termination
        member = test_data["member"]

        # Add termination reason and date
        member.termination_reason = "Personal circumstances"
        member.termination_date = today()
        member.status = "Terminated"
        member.save(ignore_permissions=True)

        return {
            **test_data,
            "persona": "Terminated Tom",
            "description": "Member going through termination process",
            "builder": builder,
        }

    @staticmethod
    def create_suspended_susan():
        """
        "Suspended Susan" - Suspension and reactivation scenario
        A member who experiences suspension and reactivation
        """
        builder = TestDataBuilder()

        test_data = (
            builder.with_chapter("Eindhoven")
            .with_member(
                first_name="Susan",
                last_name="Suspended",
                email="susan.suspended@example.com",
                contact_number="+31622222222",
                payment_method="SEPA Direct Debit",
                iban="NL91ABNA0417164300",
                status="Suspended",
            )
            .with_membership("Annual", payment_method="SEPA Direct Debit", status="Suspended")
            .build()
        )

        # Add suspension details
        member = test_data["member"]
        member.suspension_reason = "Payment arrears"
        member.suspension_date = add_days(today(), -30)
        member.save(ignore_permissions=True)

        return {
            **test_data,
            "persona": "Suspended Susan",
            "description": "Member with suspension and reactivation scenario",
            "builder": builder,
        }

    @staticmethod
    def create_all_personas():
        """Create all test personas and return them in a dictionary"""
        personas = {}

        personas["happy_path_hannah"] = TestPersonas.create_happy_path_hannah()
        personas["payment_problem_peter"] = TestPersonas.create_payment_problem_peter()
        personas["volunteer_victor"] = TestPersonas.create_volunteer_victor()
        personas["terminated_tom"] = TestPersonas.create_terminated_tom()
        personas["suspended_susan"] = TestPersonas.create_suspended_susan()

        return personas

    @staticmethod
    def cleanup_all_personas(personas):
        """Clean up all created personas"""
        for persona_name, persona_data in personas.items():
            if "builder" in persona_data:
                persona_data["builder"].cleanup()


class PersonaTestMixin:
    """Mixin class to provide persona functionality to test cases"""

    def setUp(self):
        """Set up personas for testing"""
        super().setUp()
        self.personas = {}

    def tearDown(self):
        """Clean up personas"""
        TestPersonas.cleanup_all_personas(self.personas)
        super().tearDown()

    def create_persona(self, persona_type):
        """Create a specific persona"""
        persona_methods = {
            "happy_path_hannah": TestPersonas.create_happy_path_hannah,
            "payment_problem_peter": TestPersonas.create_payment_problem_peter,
            "volunteer_victor": TestPersonas.create_volunteer_victor,
            "terminated_tom": TestPersonas.create_terminated_tom,
            "suspended_susan": TestPersonas.create_suspended_susan,
        }

        if persona_type in persona_methods:
            persona = persona_methods[persona_type]()
            self.personas[persona_type] = persona
            return persona
        else:
            raise ValueError(f"Unknown persona type: {persona_type}")

    def get_persona(self, persona_type):
        """Get an existing persona or create it if it doesn't exist"""
        if persona_type not in self.personas:
            return self.create_persona(persona_type)
        return self.personas[persona_type]
