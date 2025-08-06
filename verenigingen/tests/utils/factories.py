# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Test Data Factories for Verenigingen
Provides factories for creating consistent test data
"""

import random
from datetime import datetime

import frappe
from frappe.utils import random_string, today


class TestUserFactory:
    """Factory for creating test users with specific roles and permissions"""

    @staticmethod
    def create_member_user(email=None, member_name=None):
        """Create a user with member role"""
        if not email:
            email = f"member.{random_string(8)}@test.com"

        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Test",
                "last_name": "Member",
                "enabled": 1,
                "new_password": "test123"}
        )

        user.append("roles", {"role": "Member"})
        user.insert()

        # Link to member if provided
        if member_name:
            member = frappe.get_doc("Member", member_name)
            member.user = user.name
            member.save()

        return user

    @staticmethod
    def create_volunteer_user(email=None, volunteer_name=None):
        """Create a user with volunteer role"""
        if not email:
            email = f"volunteer.{random_string(8)}@test.com"

        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Test",
                "last_name": "Verenigingen Volunteer",
                "enabled": 1,
                "new_password": "test123"}
        )

        user.append("roles", {"role": "Verenigingen Volunteer"})
        user.append("roles", {"role": "Member"})
        user.insert()

        return user

    @staticmethod
    def create_admin_user(email=None):
        """Create a user with admin roles"""
        if not email:
            email = f"admin.{random_string(8)}@test.com"

        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Test",
                "last_name": "Admin",
                "enabled": 1,
                "new_password": "test123"}
        )

        user.append("roles", {"role": "Verenigingen Administrator"})
        user.append("roles", {"role": "System Manager"})
        user.insert()

        return user


class TestStateManager:
    """Manager for tracking and validating state transitions"""

    def __init__(self):
        self._states = {}
        self._transitions = []

    def record_state(self, entity_type, entity_name, state):
        """Record current state of an entity"""
        key = f"{entity_type}:{entity_name}"
        previous_state = self._states.get(key)

        self._states[key] = state

        if previous_state and previous_state != state:
            self._transitions.append(
                {
                    "entity_type": entity_type,
                    "entity_name": entity_name,
                    "from_state": previous_state,
                    "to_state": state,
                    "timestamp": datetime.now()}
            )

    def get_state(self, entity_type, entity_name):
        """Get current state of an entity"""
        key = f"{entity_type}:{entity_name}"
        return self._states.get(key)

    def get_transitions(self, entity_type=None, entity_name=None):
        """Get state transitions, optionally filtered"""
        transitions = self._transitions

        if entity_type:
            transitions = [t for t in transitions if t["entity_type"] == entity_type]

        if entity_name:
            transitions = [t for t in transitions if t["entity_name"] == entity_name]

        return transitions

    def validate_transition(self, entity_type, entity_name, expected_from, expected_to):
        """Validate that a specific transition occurred"""
        transitions = self.get_transitions(entity_type, entity_name)

        for transition in transitions:
            if transition["from_state"] == expected_from and transition["to_state"] == expected_to:
                return True

        return False

    def clear(self):
        """Clear all recorded states and transitions"""
        self._states.clear()
        self._transitions.clear()


class TestCleanupManager:
    """Manager for dependency-aware cleanup with rollback support"""

    def __init__(self):
        self._cleanup_stack = []
        self._dependencies = {}

    def register(self, doctype, name, dependencies=None):
        """Register a document for cleanup with optional dependencies"""
        self._cleanup_stack.append({"doctype": doctype, "name": name, "timestamp": datetime.now()})

        if dependencies:
            self._dependencies[f"{doctype}:{name}"] = dependencies

    def cleanup(self, rollback_on_error=True):
        """Clean up all registered documents in reverse order"""
        errors = []

        # Sort by dependencies and timestamp
        sorted_stack = self._sort_by_dependencies()

        for item in reversed(sorted_stack):
            try:
                if frappe.db.exists(item["doctype"], item["name"]):
                    # Check if document is submitted and needs to be cancelled first
                    doc = frappe.get_doc(item["doctype"], item["name"])
                    if hasattr(doc, "docstatus") and doc.docstatus == 1:
                        doc.cancel()
                    frappe.delete_doc(item["doctype"], item["name"], force=True)
            except Exception as e:
                errors.append({"doctype": item["doctype"], "name": item["name"], "error": str(e)})

                if rollback_on_error:
                    # Rollback and stop cleanup
                    frappe.db.rollback()
                    raise Exception(f"Cleanup failed: {errors}")

        return errors

    def _sort_by_dependencies(self):
        """Sort cleanup stack considering dependencies"""
        # Simple topological sort
        sorted_list = []
        visited = set()

        def visit(item_key):
            if item_key in visited:
                return

            visited.add(item_key)

            # Visit dependencies first
            deps = self._dependencies.get(item_key, [])
            for dep in deps:
                visit(dep)

            # Find item in stack
            doctype, name = item_key.split(":", 1)
            for item in self._cleanup_stack:
                if item["doctype"] == doctype and item["name"] == name:
                    sorted_list.append(item)
                    break

        # Visit all items
        for item in self._cleanup_stack:
            visit(f"{item['doctype']}:{item['name']}")

        return sorted_list

    def clear(self):
        """Clear the cleanup stack"""
        self._cleanup_stack.clear()
        self._dependencies.clear()


class TestDataBuilder:
    """Fluent interface for building complex test scenarios"""

    def __init__(self):
        self._data = {}
        self._cleanup_manager = TestCleanupManager()

    def with_chapter(self, name=None, region=None, postal_codes=None):
        """Add a chapter to the test data"""
        if not name:
            name = f"Test Chapter {random_string(8)}"

        if not region:
            # Get the actual test region name (it might be slugified)
            region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
            if not region:
                # Create test region if it doesn't exist
                test_region = frappe.get_doc(
                    {
                        "doctype": "Region",
                        "region_name": "Test Region",
                        "region_code": "TR",
                        "country": "Netherlands",
                        "is_active": 1}
                )
                test_region.insert()
                region = test_region.name

        if not postal_codes:
            postal_codes = f"{random.randint(1000, 9999)}"

        # Check if chapter already exists
        if frappe.db.exists("Chapter", name):
            chapter = frappe.get_doc("Chapter", name)
        else:
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": name,
                    "region": region,
                    "postal_codes": postal_codes,
                    "introduction": "Test chapter"}
            )
            chapter.insert()

        self._data["chapter"] = chapter
        self._cleanup_manager.register("Chapter", chapter.name)

        return self

    def with_member(self, first_name=None, last_name=None, email=None, **kwargs):
        """Add a member to the test data"""
        if not first_name:
            first_name = f"Test{random_string(4)}"

        if not last_name:
            last_name = f"Member{random_string(4)}"

        if not email:
            email = f"test.{random_string(8)}@example.com"

        member_data = {
            "doctype": "Member",
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "contact_number": "+31612345678",
            "payment_method": "Bank Transfer",
            "status": "Active"}
        member_data.update(kwargs)

        # Link to chapter if available
        if "chapter" in self._data:
            member_data["primary_chapter"] = self._data["chapter"].name

        member = frappe.get_doc(member_data)
        member.insert()

        # Add to chapter if chapter exists
        if "chapter" in self._data:
            try:
                chapter = frappe.get_doc("Chapter", self._data["chapter"].name)
                chapter.append(
                    "members",
                    {"member": member.name, "chapter_join_date": today(), "enabled": 1, "status": "Active"},
                )
                chapter.save()
            except frappe.LinkValidationError:
                # Skip chapter update if there are stale member references
                # This is acceptable for test data - member still gets created
                pass

        self._data["member"] = member
        self._cleanup_manager.register("Member", member.name)

        return self

    def with_membership(self, membership_type=None, payment_method=None, **kwargs):
        """Add a membership to the test data"""
        if "member" not in self._data:
            raise ValueError("Must create member before membership")

        if not membership_type:
            # Create a default membership type
            membership_type = self._create_default_membership_type()

        membership_data = {
            "doctype": "Membership",
            "member": self._data["member"].name,
            "membership_type": membership_type,
            "start_date": today(),
            "status": "Active"}
        membership_data.update(kwargs)

        membership = frappe.get_doc(membership_data)
        membership.insert()
        membership.submit()  # Memberships are submittable documents

        self._data["membership"] = membership
        self._cleanup_manager.register(
            "Membership", membership.name, dependencies=[f"Member:{self._data['member'].name}"]
        )

        return self

    def with_volunteer_profile(self, **kwargs):
        """Add a volunteer profile to the test data"""
        if "member" not in self._data:
            raise ValueError("Must create member before volunteer profile")

        volunteer_data = {
            "doctype": "Volunteer",
            "volunteer_name": self._data["member"].full_name,
            "email": f"volunteer.{random_string(8)}@example.com",
            "member": self._data["member"].name,
            "status": "Active",
            "start_date": today()}
        volunteer_data.update(kwargs)

        volunteer = frappe.get_doc(volunteer_data)
        volunteer.insert()

        self._data["volunteer"] = volunteer
        self._cleanup_manager.register(
            "Verenigingen Volunteer", volunteer.name, dependencies=[f"Member:{self._data['member'].name}"]
        )

        return self

    def with_team_assignment(self, team_name=None, role="Member", **kwargs):
        """Add a team assignment to the volunteer"""
        if "volunteer" not in self._data:
            raise ValueError("Must create volunteer before team assignment")

        # Create team if not exists
        if not team_name:
            team_name = f"Test Team {random_string(8)}"

        if not frappe.db.exists("Team", team_name):
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": team_name,
                    "status": "Active",
                    "team_type": "Project Team",
                    "start_date": today()}
            )
            if "chapter" in self._data:
                team.chapter = self._data["chapter"].name
            team.insert()
            self._cleanup_manager.register("Team", team.name)
        else:
            team = frappe.get_doc("Team", team_name)

        # Add volunteer to team
        team.append(
            "team_members",
            {
                "volunteer": self._data["volunteer"].name,
                "volunteer_name": self._data["volunteer"].volunteer_name,
                "role": role,
                "role_type": kwargs.get("role_type", "Team Member"),
                "from_date": kwargs.get("from_date", today()),
                "is_active": 1,
                "status": "Active"},
        )
        team.save()

        if "teams" not in self._data:
            self._data["teams"] = []
        self._data["teams"].append(team)

        return self

    def with_expense(self, amount, description, **kwargs):
        """Add an expense to the volunteer"""
        if "volunteer" not in self._data:
            raise ValueError("Must create volunteer before expense")

        expense_data = {
            "doctype": "Volunteer Expense",
            "volunteer": self._data["volunteer"].name,
            "amount": amount,
            "description": description,
            "expense_date": today(),
            "status": "Draft",
            "organization_type": "Chapter",  # Default to Chapter
        }

        # Try to get or create a default expense category
        expense_categories = frappe.get_all("Expense Category", limit=1)
        if expense_categories:
            expense_data["category"] = expense_categories[0].name
        else:
            # Create a default test expense category if none exist
            expense_account = frappe.get_all(
                "Account", filters={"account_type": "Expense Account", "is_group": 0}, limit=1
            )
            if expense_account:
                test_category = frappe.get_doc(
                    {
                        "doctype": "Expense Category",
                        "category_name": "Test Expenses",
                        "expense_account": expense_account[0].name}
                )
                test_category.insert()
                expense_data["category"] = test_category.name

        # If chapter exists in test data, use it
        if "chapter" in self._data:
            expense_data["chapter"] = self._data["chapter"].name
        else:
            # Try to get chapter from volunteer's member record
            volunteer = self._data["volunteer"]
            if hasattr(volunteer, "member") and volunteer.member:
                member = frappe.get_doc("Member", volunteer.member)
                if hasattr(member, "primary_chapter") and member.primary_chapter:
                    expense_data["chapter"] = member.primary_chapter

        # Allow override from kwargs
        expense_data.update(kwargs)

        expense = frappe.get_doc(expense_data)
        expense.insert()

        if "expenses" not in self._data:
            self._data["expenses"] = []
        self._data["expenses"].append(expense)

        self._cleanup_manager.register(
            "Volunteer Expense", expense.name, dependencies=[f"Volunteer:{self._data['volunteer'].name}"]
        )

        return self

    def with_sepa_mandate(self, iban=None, **kwargs):
        """Add a SEPA mandate to the member"""
        if "member" not in self._data:
            raise ValueError("Must create member before SEPA mandate")

        if not iban:
            iban = f"NL{random.randint(10, 99)}TEST{random.randint(1000000000, 9999999999)}"

        # This would create the actual SEPA mandate
        # Implementation depends on SEPA mandate structure

        return self

    def build(self):
        """Build and return the test data"""
        return self._data

    def cleanup(self):
        """Clean up all created test data"""
        return self._cleanup_manager.cleanup()

    def _create_default_membership_type(self):
        """Create a default membership type for testing"""
        name = f"Test Membership {random_string(8)}"

        if not frappe.db.exists("Membership Type", name):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": name,
                    "amount": 100,
                    "currency": "EUR",
                    "billing_frequency": "Monthly"  # Default to Monthly for test data
                }
            )
            membership_type.insert()
            self._cleanup_manager.register("Membership Type", membership_type.name)

            return membership_type.name

        return name
