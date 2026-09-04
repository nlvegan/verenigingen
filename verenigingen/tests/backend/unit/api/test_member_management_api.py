# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Member Management API functions
Tests the whitelisted API functions for member management operations
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.api import member_management
from verenigingen.tests.utils.assertions import AssertionHelpers
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestMemberManagementAPI(VereningingenUnitTestCase):
    """Test Member Management API functions"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.test_env = TestEnvironmentSetup.create_standard_test_environment()

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()
        self.assertions = AssertionHelpers()

    def tearDown(self):
        """Clean up after each test"""
        # super().tearDown() FIRST, THEN builder.cleanup(commit=True): the base
        # teardown's `_rollback_once_before_draining` (tests/utils/base.py) must
        # discard this test's other uncommitted rows before the commit below runs,
        # or the commit makes ALL of them durable too -- not just the builder's
        # registered deletes. Measured: calling cleanup(commit=True) BEFORE
        # super().tearDown() leaked untracked Chapter/Membership Dues Schedule/User
        # rows created earlier in the test, because the rollback that would have
        # discarded them never got the chance. This order matches how
        # `_cleanup_document_with_retry` already does it: rollback first, delete
        # and commit after (#489).
        super().tearDown()
        self.builder.cleanup(commit=True)

    def test_assign_member_to_chapter(self):
        """Test assigning member to a chapter"""
        # Create member without chapter
        test_data = self.builder.with_member().build()
        member = test_data["member"]
        chapter = self.test_env["chapters"][0]

        # Assign to chapter
        member_management.assign_member_to_chapter(member.name, chapter.name)

        # Verify assignment (chapter linkage is via Chapter Member child rows)
        member_chapter = frappe.db.get_value(
            "Chapter Member", {"member": member.name, "enabled": 1}, "parent"
        )
        self.assertEqual(member_chapter, chapter.name)

        # Verify chapter members updated (the child table field is `members`)
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_names = [cm.member for cm in chapter_doc.members]
        self.assertIn(member.name, member_names)

    # FLAGGED (ambiguous API): member_management.get_member_chapters does not
    # exist. A `get_member_chapters` lives in utils/member_utils.py (returns
    # List[str]) and in chapter_management_service.py (returns List[Dict]), but
    # neither matches this module path / expected shape. Skipped pending a
    # product decision on whether this member_management API was intended.
    @unittest.skip("Flagged: member_management.get_member_chapters not implemented (ambiguous API)")
    def test_get_member_chapters(self):
        """Test getting all chapters a member belongs to"""
        # Create member in multiple chapters
        test_data = self.builder.with_chapter(self.test_env["chapters"][0].name).with_member().build()

        member = test_data["member"]

        # Add to second chapter
        second_chapter = self.test_env["chapters"][1]
        member_management.assign_member_to_chapter(member.name, second_chapter.name)

        # Get all chapters
        chapters = member_management.get_member_chapters(member.name)

        self.assertEqual(len(chapters), 2)
        chapter_names = [c["chapter"] for c in chapters]
        self.assertIn(self.test_env["chapters"][0].name, chapter_names)
        self.assertIn(second_chapter.name, chapter_names)

    # FLAGGED (ambiguous API): member_management.update_member_status(name,
    # status, reason) does not exist. Status changes are handled by
    # api/suspension_api.py (suspend_member / unsuspend_member) with a different
    # signature. Skipped pending a product decision on whether this 3-arg
    # status-setter API was intended.
    @unittest.skip("Flagged: member_management.update_member_status not implemented (ambiguous API)")
    def test_update_member_status(self):
        """Test updating member status"""
        # Create active member
        test_data = self.builder.with_member(status="Active").build()
        member = test_data["member"]

        # Suspend member
        result = member_management.update_member_status(member.name, "Suspended", reason="Non-payment")

        # Verify status update
        member.reload()
        self.assertEqual(member.status, "Suspended")
        self.assertEqual(member.suspension_reason, "Non-payment")
        self.assertIsNotNone(member.suspension_date)

    @unittest.skip("Flagged: member_management.update_member_status not implemented (ambiguous API)")
    def test_reactivate_member(self):
        """Test reactivating a suspended member"""
        # Create suspended member
        test_data = self.builder.with_member(
            status="Suspended", suspension_date=add_days(today(), -30), suspension_reason="Payment failure"
        ).build()

        member = test_data["member"]

        # Reactivate
        result = member_management.update_member_status(member.name, "Active", reason="Payment received")

        # Verify reactivation
        member.reload()
        self.assertEqual(member.status, "Active")
        self.assertIsNotNone(member.suspension_lifted_date)
