#!/usr/bin/env python3
"""
Sample file to test the improved validation system
This file contains various patterns that were causing false positives
"""

import json
from datetime import datetime

import frappe


def test_false_positive_patterns():
    """Patterns that should NOT be flagged but were in the old system"""

    # 1. Valid DocType field access
    member = frappe.get_doc("Member", "test-member")
    first_name = member.first_name  # Should be valid

    # 2. Child table iteration (was causing false positives)
    for membership in member.chapter_memberships:
        chapter = membership.chapter  # Should be valid child table field

    # 3. SQL result access (was causing false positives)
    results = frappe.db.sql(
        """
        SELECT name as member_name, COUNT(*) as total
        FROM tabMember GROUP BY name
    """,
        as_dict=True,
    )

    for row in results:
        name = row.member_name  # Should be valid - SQL alias
        count = row.total  # Should be valid - SQL alias

    # 4. Built-in object access (should be ignored)
    data = json.loads('{"key": "value"}')
    value = data.key  # Should be ignored - built-in object

    # 5. Property method access pattern
    manager = MemberManager()
    count = manager.active_count  # Should be valid if active_count is @property


class MemberManager:
    @property
    def active_count(self):
        return 42


def test_genuine_errors():
    """These SHOULD be flagged as genuine errors"""
    member = frappe.get_doc("Member", "test")

    # These are genuine errors that should be caught
    invalid = member.definitely_nonexistent_field  # Should be flagged
    typo = member.first_nam  # Should be flagged (typo)
