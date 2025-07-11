# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Setup helpers for creating consistent test environments
"""

import frappe
from frappe.utils import today


class TestEnvironmentSetup:
    """Helper class to set up test environments with chapters and teams"""

    @staticmethod
    def create_test_chapters():
        """Create standard test chapters for testing"""
        chapters = []

        # Get the actual test region name (it might be slugified)
        test_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
        if not test_region:
            # Create test region if it doesn't exist
            region = frappe.get_doc(
                {
                    "doctype": "Region",
                    "region_name": "Test Region",
                    "region_code": "TR",
                    "country": "Netherlands",
                    "is_active": 1,
                    "postal_code_patterns": "1000-9999",  # Cover all test postal codes
                }
            )
            region.insert(ignore_permissions=True)
            test_region = region.name

        # Amsterdam Chapter
        if not frappe.db.exists("Chapter", "Test Amsterdam Chapter"):
            amsterdam = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "Test Amsterdam Chapter",
                    "chapter_name": "Test Amsterdam Chapter",  # Add chapter_name field
                    "short_name": "TAC",  # Add short_name field
                    "region": test_region,
                    "postal_codes": "1000-1099",
                    "introduction": "Test chapter for Amsterdam area",
                    "published": 1,
                    "country": "Netherlands",  # Add country field
                }
            )
            amsterdam.insert(ignore_permissions=True)
            chapters.append(amsterdam)
        else:
            chapters.append(frappe.get_doc("Chapter", "Test Amsterdam Chapter"))

        # Rotterdam Chapter
        if not frappe.db.exists("Chapter", "Test Rotterdam Chapter"):
            rotterdam = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "Test Rotterdam Chapter",
                    "chapter_name": "Test Rotterdam Chapter",  # Add chapter_name field
                    "short_name": "TRC",  # Add short_name field
                    "region": test_region,
                    "postal_codes": "3000-3099",
                    "introduction": "Test chapter for Rotterdam area",
                    "published": 1,
                    "country": "Netherlands",  # Add country field
                }
            )
            rotterdam.insert(ignore_permissions=True)
            chapters.append(rotterdam)
        else:
            chapters.append(frappe.get_doc("Chapter", "Test Rotterdam Chapter"))

        return chapters

    @staticmethod
    def create_test_teams(chapter=None):
        """Create standard test teams"""
        teams = []

        # Events Team
        if not frappe.db.exists("Team", "Test Events Team"):
            events_team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": "Test Events Team",
                    "description": "Team responsible for organizing events",
                    "status": "Active",
                    "team_type": "Operational Team",
                    "start_date": today(),
                    "objectives": "Organize and execute association events",
                    "is_association_wide": 0 if chapter else 1,
                    "chapter": chapter.name if chapter else None,
                }
            )
            events_team.insert(ignore_permissions=True)
            teams.append(events_team)

        # Communications Team
        if not frappe.db.exists("Team", "Test Communications Team"):
            comm_team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": "Test Communications Team",
                    "description": "Team responsible for internal and external communications",
                    "status": "Active",
                    "team_type": "Operational Team",
                    "start_date": today(),
                    "objectives": "Manage association communications and PR",
                    "is_association_wide": 1,
                }
            )
            comm_team.insert(ignore_permissions=True)
            teams.append(comm_team)

        return teams

    @staticmethod
    def create_standard_test_environment():
        """Create a complete test environment with chapters, teams, and membership types"""
        environment = {}

        # Create chapters
        environment["chapters"] = TestEnvironmentSetup.create_test_chapters()

        # Create teams (one per chapter + association-wide)
        environment["teams"] = []
        for chapter in environment["chapters"]:
            chapter_teams = TestEnvironmentSetup.create_test_teams(chapter)
            environment["teams"].extend(chapter_teams)

        # Create association-wide teams
        association_teams = TestEnvironmentSetup.create_test_teams()
        environment["teams"].extend(association_teams)

        # Create membership types
        environment["membership_types"] = TestEnvironmentSetup.create_test_membership_types()

        # Create volunteer interest areas
        environment["interest_areas"] = TestEnvironmentSetup.create_volunteer_interest_areas()

        return environment

    @staticmethod
    def create_test_membership_types():
        """Create standard membership types for testing"""
        types = []

        configs = [
            {
                "name": "Test Regular Membership",
                "period": "Annual",
                "amount": 100.00,
                "enforce_minimum": True,
            },
            {"name": "Test Student Membership", "period": "Annual", "amount": 50.00, "enforce_minimum": True},
            {
                "name": "Test Monthly Membership",
                "period": "Monthly",
                "amount": 10.00,
                "enforce_minimum": False,
            },
            {"name": "Test Daily Membership", "period": "Daily", "amount": 2.00, "enforce_minimum": False},
            # Add simplified names that personas expect
            {"name": "Annual", "period": "Annual", "amount": 100.00, "enforce_minimum": True},
            {"name": "Monthly", "period": "Monthly", "amount": 10.00, "enforce_minimum": False},
        ]

        for config in configs:
            if not frappe.db.exists("Membership Type", config["name"]):
                membership_type = frappe.get_doc(
                    {
                        "doctype": "Membership Type",
                        "membership_type_name": config["name"],
                        "amount": config["amount"],
                        "currency": "EUR",
                        "subscription_period": config["period"],
                        "enforce_minimum_period": config["enforce_minimum"],
                    }
                )
                membership_type.insert(ignore_permissions=True)
                types.append(membership_type)

        return types

    @staticmethod
    def create_volunteer_interest_areas():
        """Create standard volunteer interest areas"""
        areas = []

        area_names = [
            "Event Planning",
            "Technical Support",
            "Community Outreach",
            "Fundraising",
            "Administration",
            "Communications",
        ]

        for area_name in area_names:
            # Since Volunteer Interest Area is a child table, we need to create
            # Volunteer Interest Category instead
            if not frappe.db.exists("Volunteer Interest Category", area_name):
                category = frappe.get_doc(
                    {"doctype": "Volunteer Interest Category", "category_name": area_name}
                )
                category.insert(ignore_permissions=True)
                areas.append(category)

        return areas

    @staticmethod
    def cleanup_test_environment():
        """Clean up test environment data"""
        # Clean in reverse dependency order
        cleanup_order = [
            ("Team Member", {"volunteer": ["like", "Test%"]}),
            ("Team", {"team_name": ["like", "Test%"]}),
            ("Volunteer Assignment", {"role": ["like", "Test%"]}),
            ("Volunteer Expense", {"description": ["like", "Test%"]}),
            ("Volunteer", {"volunteer_name": ["like", "Test%"]}),
            ("Membership", {"member": ["like", "Assoc-Member-Test%"]}),
            ("Chapter Member", {"member": ["like", "Assoc-Member-Test%"]}),
            ("Member", {"first_name": ["like", "Test%"]}),
            ("Chapter", {"name": ["like", "Test%"]}),
            ("Membership Type", {"membership_type_name": ["like", "Test%"]}),
            (
                "Volunteer Interest Area",
                {
                    "name": [
                        "in",
                        [
                            "Event Planning",
                            "Technical Support",
                            "Community Outreach",
                            "Fundraising",
                            "Administration",
                            "Communications",
                        ],
                    ]
                },
            ),
        ]

        for doctype, filters in cleanup_order:
            try:
                records = frappe.get_all(doctype, filters=filters)
                for record in records:
                    frappe.delete_doc(doctype, record.name, force=True)
            except Exception as e:
                print(f"Error cleaning up {doctype}: {e}")
