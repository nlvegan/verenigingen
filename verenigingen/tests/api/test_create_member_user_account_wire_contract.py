# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Wire-level contract for create_member_user_account's response shape (#1452).

member.js's create_user_account_dialog callback reads the response FLAT
(`r.message.message`, `r.message.error`). The whitelisted endpoint
(`verenigingen.api.member.general_api.create_member_user_account`, re-exported
as `verenigingen.verenigingen.doctype.member.member.create_member_user_account`
via member_compat.py -- the exact dotted path member.js calls) is decorated
with `@critical_api`, which serializes the returned OperationResult via
`to_dict(scrub_sensitive=True)` -- the NESTED schema. So:

  - success: {"success": True, "data": "<username>", "meta": {"message": ...,
    "action": ...}} -- the success text lives under "meta", not a top-level
    "message", and "data" is a bare username STRING, not an object.
  - failure (already_exists): {"success": False, "error": {"message": ...},
    "meta": {"user": ..., "action": "already_exists"}} -- there is no
    top-level "error" string and no top-level "message" at all.

This asserts the real dispatched shape (calling the whitelisted function
directly runs the same @critical_api decorator that converts the
OperationResult, per api_security_framework.py's to_dict(scrub_sensitive=True)
call) so the JS fix's assumption is backed by a real dispatch, not by reading
the decorator source and trusting it.
"""

import frappe

from verenigingen.api.member.general_api import create_member_user_account
from verenigingen.tests.utils.base import VereningingenTestCase


class TestCreateMemberUserAccountWireContract(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # @critical_api requires an authenticated privileged user (auth is not
        # mocked by the base test case).
        frappe.set_user("Administrator")

    def test_success_envelope_nests_username_under_data_and_message_under_meta(self):
        # create_test_member() (EnhancedTestDataFactory.create_member) generates
        # a unique default email and last_name suffix when none is given -- no
        # need for a bespoke uniquifying helper here.
        member = self.create_test_member(first_name="Wirecontract", last_name="Ok")

        response = create_member_user_account(member.name, send_welcome_email=False)

        self.assertTrue(response["success"])
        self.assertNotIn("message", response, "success text leaked to the envelope's top level")
        self.assertNotIn("error", response)
        self.assertIn("data", response)
        self.assertIsInstance(response["data"], str, "data should be the bare username string")
        self.assertIn("@", response["data"])
        self.assertIn("meta", response)
        self.assertTrue(response["meta"].get("message"), "success message must live under meta.message")
        self.assertIn(response["meta"].get("action"), ["created_new", "linked_existing"])

    def test_failure_envelope_nests_the_message_under_error_not_a_bare_string(self):
        member = self.create_test_member(first_name="Wirecontract", last_name="Dupe")

        first = create_member_user_account(member.name, send_welcome_email=False)
        self.assertTrue(first["success"], f"precondition failed: first call did not succeed: {first}")

        second = create_member_user_account(member.name, send_welcome_email=False)

        self.assertFalse(second["success"])
        self.assertNotIn("message", second, "failure text leaked to the envelope's top level")
        self.assertIn("error", second)
        self.assertIsInstance(
            second["error"],
            dict,
            "error must be a structured object ({message, code, ...}), not a bare string -- "
            "a caller reading `r.message.error` as a string would render '[object Object]'",
        )
        self.assertTrue(second["error"].get("message"))

    def test_failure_missing_member(self):
        response = create_member_user_account("MEM-DOES-NOT-EXIST-XYZ", send_welcome_email=False)

        self.assertFalse(response["success"])
        self.assertIn("error", response)
        self.assertIsInstance(response["error"], dict)
        self.assertTrue(response["error"].get("message"))
