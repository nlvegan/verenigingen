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

from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.tests.utils.cleanup_savepoint import (
    release_cleanup_savepoint,
    rollback_cleanup_attempt,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


def _ensure_volunteer_interest_category(category_name):
    """Create a Volunteer Interest Category if it does not exist yet.

    A fresh `run-tests --module` site does not seed these masters, so
    referencing them from a volunteer's interests child table would raise
    LinkValidationError. Idempotent: returns the existing name if present.
    """
    if frappe.db.exists("Volunteer Interest Category", category_name):
        return category_name
    frappe.get_doc(
        {"doctype": "Volunteer Interest Category", "category_name": category_name}
    ).insert(ignore_permissions=True)
    return category_name


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
        # ERPNext roles for financial operations
        user.append("roles", {"role": "Accounts Manager"})
        user.append("roles", {"role": "Sales Manager"})
        user.append("roles", {"role": "Accounts User"})
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

    def cleanup(self):
        """Delete every registered document in reverse order. Returns the failures.

        ONE UNDELETABLE DOCUMENT MUST NOT ABANDON THE REST OF THE CLEANUP. This
        method used to roll the whole transaction back and RAISE on the first
        document it could not delete, so every document still registered behind it
        was left on the site (#483).

        The raise cost more than this loop. Four of the five `tearDown`s that call
        `TestDataBuilder.cleanup()` call it BEFORE `super().tearDown()` and do not
        wrap it, so the exception skipped the base class's entire teardown as well:
        the drain, the Error Log capture, the leak report and the mock restoration.
        Three call sites in two of those suites also call it mid-test, where a
        transaction-wide rollback discards the test's own `setUp` -- and any uncommitted `setUpClass` fixture
        the class still needs, which is the #330 failure mode (measured in CI when
        the drain's rollback was widened that way: 6 of 12 shards red).

        So: a savepoint per document, and the failures come back as a list. The
        `rollback_on_error` parameter is gone rather than kept and ignored -- no
        caller ever passed it, and a parameter that no longer does what it says is
        how this repo has been misled before.

        WHAT CONTINUING COSTS, stated because it is not free: the loop deletes
        dependents before dependencies, so carrying on past a failed dependent can
        delete a link target the survivor still points at -- an orphan Membership
        whose Member is gone. That is narrower than what it replaces (a rollback
        that reaches other classes' uncommitted fixtures, and a raise that skips
        the caller's entire base teardown), so it is the better trade, not a free
        one. `self._dependencies` looks like it could prevent it by skipping the
        dependencies of anything that failed, and it cannot: the map is sparse --
        `with_membership` declares the Membership's dependency on the Member and
        says nothing about its Membership Type, which is the exact link #433 was
        about. Partial protection that reads as total is worse than none.

        NOT DONE HERE, on purpose:

        - **The ledger carve-out** that `VereningingenTestCase._cancel_if_submitted`
          documents at length. What this class is actually handed is Chapter, Member,
          Membership, Membership Type, Team, Team Role, plus two names that are not
          DocTypes on any test site (`Verenigingen Volunteer` and `Volunteer Expense`
          -- registered by `with_volunteer_profile` and `with_expense`, see #491).
          `SEPA Mandate` is in none of them: `with_sepa_mandate` is a no-op stub that
          registers nothing.
          Checked against `tabDocType`: of the six real ones only Membership is
          submittable, and none post GL or Payment Ledger rows, so there is nothing
          for the carve-out to protect yet. Register a voucher and there will be --
          that is #482, which has to fix the drains together.
        - **A lock-timeout retry.** `VereningingenTestCase._cleanup_document_with_retry`
          retries `QueryTimeoutError` three times at 0.5s; this returns the error on the
          first one. Not a regression -- the old code raised -- but the omission is
          deliberate rather than overlooked.
        - **`ignore_permissions` / `ignore_links` on the cancel**, which
          `_cancel_if_submitted` sets and explains at length. Not needed here yet:
          `_sort_by_dependencies` plus `reversed` yields Membership -> Membership Type ->
          Member -> Chapter, so a Membership is cancelled BEFORE its Membership Type is
          deleted and the #433 link hazard does not arise. It arises the moment that
          order changes.
        """
        errors = []

        # Sort by dependencies and timestamp
        sorted_stack = self._sort_by_dependencies()

        for item in reversed(sorted_stack):
            error = self._delete_registered_document(item)
            if error:
                errors.append(error)
                # Announced, not just returned: ALL EIGHT call sites discard the
                # returned list (five tearDowns, three mid-test), and the old raise was
                # at least loud. get_harness_logger rather than frappe.logger(), whose
                # records reach only logs/frappe.log -- a file CI never uploads (#485).
                get_harness_logger("test-cleanup-manager").error(
                    "Could not delete %s %s: %s", error["doctype"], error["name"], error["error"]
                )

        return errors

    @staticmethod
    def _delete_registered_document(item):
        """Delete one registered document. Returns an error dict, or None on success.

        The savepoint undoes this attempt and nothing else. `delete_doc` runs
        `on_trash` before it removes anything and a failure part-way through can
        leave the document mutated, so the attempt has to be undone -- but undoing
        it with `frappe.db.rollback()` discards every uncommitted row in the
        connection, including rows this cleanup does not own.

        The savepoint's UNDO is not exercised by the tests that pin this method.
        They fail the delete with `NestedSet.on_trash`, which calls
        `validate_if_child_exists()` before it writes anything, so there is nothing
        to roll back -- measured: zero mutations at the point of failure. What those
        tests pin is the SCOPE (a sibling row survives). Pinning the undo needs a
        document whose `on_trash` mutates before it throws.

        `is_submittable`, not `docstatus == 1` alone: erpnext calls `gle.submit()` on
        GL Entry, which is `is_submittable = 0`, and cancelling one of those raises --
        `VereningingenTestCase._cancel_if_submitted` documents the same guard at length.
        Nothing this class is handed today reaches it, which is exactly why the guard is
        cheaper than the bug.

        The shape is a class of 13 under `verenigingen/tests`: `docstatus == 1` leading
        to a cancel. This is the one fixed; the other 12 were assessed and left. Eleven
        are on doctypes that really are submittable (Membership, Sales Invoice, Donation,
        Bank Transaction); the twelfth,
        `EnhancedTestCase._cleanup_document_with_retry`, is generic over its argument
        and so has the same latent hole -- but it has zero callers.
        """
        savepoint = f"testcleanup_{frappe.generate_hash(length=8)}"
        # Whether the savepoint exists, tracked rather than assumed: undoing to a
        # savepoint that was never created raises 1305, and the undo now WARNS on
        # failure, so assuming it would turn "the existence check raised" into a
        # spurious warning about a savepoint nobody set.
        savepoint_taken = False
        try:
            # Inside the try, both of them: an existence check and a savepoint are
            # ordinary statements that can raise a deadlock or a lost connection, and
            # anything raised out of this method skips the caller's
            # `super().tearDown()` -- the #483 defect verbatim, on the two paths its
            # first fix left outside.
            if not DocumentExistenceValidator.check_document_exists(item["doctype"], item["name"]):
                return None
            frappe.db.savepoint(savepoint)
            savepoint_taken = True
            # Check if document is submitted and needs to be cancelled first
            if (
                frappe.get_meta(item["doctype"]).is_submittable
                and frappe.db.get_value(item["doctype"], item["name"], "docstatus") == 1
            ):
                frappe.get_doc(item["doctype"], item["name"]).cancel()
            frappe.delete_doc(item["doctype"], item["name"], force=True)
        except Exception as e:
            if savepoint_taken:
                rollback_cleanup_attempt(savepoint, e)
            return {"doctype": item["doctype"], "name": item["name"], "error": str(e)}

        release_cleanup_savepoint(savepoint)
        return None

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
        if DocumentExistenceValidator.check_document_exists("Chapter", name):
            # BORROWED, so deliberately NOT registered. A chapter that is already
            # here belongs to whoever built it -- typically the shared
            # `Test Amsterdam Chapter` from `tests/utils/setup_helpers.py`, which the
            # whole suite resolves. Registering it made `cleanup()` delete master data
            # this builder never created (#498).
            #
            # And that delete is NOT reliably undone. There is no per-TEST rollback in
            # the framework -- only `addClassCleanup(_rollback_db)`, per CLASS -- and
            # `VereningingenTestCase._rollback_once_before_draining` returns early
            # unless a tracked document still exists. Measured on test_site_5, same
            # committed borrowed chapter both ways:
            #
            #   cleanup() in tearDown, one tracked doc  -> rollback fires, chapter back
            #   cleanup() MID-TEST, then any commit     -> chapter GONE, committed
            #
            # Three suites call `cleanup()` mid-test (`test_member_api`,
            # `test_member_controller` x2). They build member-only today, so no chapter
            # is borrowed on that path -- which is the only reason this has not already
            # taken the shared chapter out from under a shard (#330/#390).
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
            self._cleanup_manager.register("Chapter", chapter.name)

        self._data["chapter"] = chapter

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

        member = frappe.get_doc(member_data)
        member.insert()

        # Add to chapter if chapter exists (chapter linkage is via Chapter Member child rows)
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
        elif not frappe.db.exists("Membership Type", membership_type):
            # Self-seed a named membership type that does not yet exist on the
            # (possibly isolated) test site, so personas/builders referencing a
            # specific type name do not fail with LinkValidationError.
            self._create_named_membership_type(membership_type)

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

        # Handle child table fields that need special formatting
        interests = kwargs.pop("interests", None)
        skills = kwargs.pop("skills", None)  # Map to skills_and_qualifications if provided
        kwargs.pop("availability", None)  # Not a valid field, ignore

        volunteer_data = {
            "doctype": "Volunteer",
            "volunteer_name": self._data["member"].full_name,
            "email": f"volunteer.{random_string(8)}@example.com",
            "member": self._data["member"].name,
            "status": "Active",
            "start_date": today(),
        }
        volunteer_data.update(kwargs)

        # Convert interests list to proper child table format
        if interests:
            # Volunteer Interest Area.interest_area is a Link to Volunteer Interest
            # Category. Ensure each referenced category exists (a fresh --module site
            # does not seed these masters) before assigning it.
            for item in interests:
                if isinstance(item, str):
                    _ensure_volunteer_interest_category(item)
            volunteer_data["interests"] = [
                {"interest_area": item} if isinstance(item, str) else item
                for item in interests
            ]

        # Convert skills string/list to proper child table format for skills_and_qualifications
        if skills:
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",")]
            volunteer_data["skills_and_qualifications"] = [
                {"volunteer_skill": item, "skill_category": "Other", "proficiency_level": "3 - Intermediate"}
                if isinstance(item, str) else item
                for item in skills
            ]

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

        if not DocumentExistenceValidator.check_document_exists("Team", team_name):
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

        # Get or create a team role
        team_role = kwargs.get("team_role", role)
        if not frappe.db.exists("Team Role", team_role):
            # Try common role names
            if frappe.db.exists("Team Role", "Team Member"):
                team_role = "Team Member"
            else:
                # Create a test team role
                team_role_doc = frappe.get_doc({
                    "doctype": "Team Role",
                    "role_name": team_role or "Test Role",
                })
                team_role_doc.insert()
                team_role = team_role_doc.name
                self._cleanup_manager.register("Team Role", team_role)

        # Add volunteer to team
        team.append(
            "team_members",
            {
                "volunteer": self._data["volunteer"].name,
                "volunteer_name": self._data["volunteer"].volunteer_name,
                "team_role": team_role,
                "from_date": kwargs.get("from_date", today()),
                "is_active": 1,
                "status": "Active",
            },
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
                # Chapter linkage is via Chapter Member child rows, not a Member field
                member_chapter = frappe.db.get_value(
                    "Chapter Member", {"member": volunteer.member, "enabled": 1}, "parent"
                )
                if member_chapter:
                    expense_data["chapter"] = member_chapter

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

    def _create_named_membership_type(self, name):
        """Create a membership type with a specific name for testing.

        Used when a persona/builder references a named type (e.g.
        "Annual Membership") that is not present on the test site.
        """
        if not DocumentExistenceValidator.check_document_exists("Membership Type", name):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": name,
                    "amount": 100,
                    "currency": "EUR",
                    "billing_period": "Annual",
                }
            )
            membership_type.insert()
            self._cleanup_manager.register("Membership Type", membership_type.name)
        return name

    def _create_default_membership_type(self):
        """Create a default membership type for testing"""
        name = f"Test Membership {random_string(8)}"

        if not DocumentExistenceValidator.check_document_exists("Membership Type", name):
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
