"""#1853: self-service chapter paths identify the caller's Member by Member.user ONLY.

Maintainer ruling (2026-11-01): no Member.email fallback. A logged-in user whose email merely
matches a Member's email (Member.user unset) is refused, with a clear message; a properly linked
member can still join. Callers are plain "Verenigingen Member" users, not Administrator.
Fixture note: the unlinked case is built by clearing Member.user with db_set (the state of a
legacy record whose email matches a User); that is the state under test, not a stand-in for a flow.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSelfServiceChapterRequiresUserLink(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._form_dict = frappe.form_dict
        self._request = getattr(frappe.local, "request", None)
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 1853 Chapter {frappe.generate_hash()[:6]}", region="Test Region 1853"
        )
        self.linked = self._user_and_member_1853(linked=True)
        self.unlinked = self._user_and_member_1853(linked=False)

    def tearDown(self):
        frappe.form_dict = self._form_dict
        frappe.local.request = self._request
        super().tearDown()

    def _user_and_member_1853(self, linked):
        email = f"jc1853-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name="Jc", last_name="Link" if linked else "Email", email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email if linked else None)
        return frappe._dict(member=member, user=email)

    def _requests_for(self, member):
        return frappe.get_all("Chapter Join Request", filters={"member": member.name}, pluck="name")

    def test_linked_member_can_join(self):
        from verenigingen.api.chapter_join import join_chapter

        with self.as_user(self.linked.user):
            result = join_chapter(self.chapter.name, "I want to help")
        self.assertTrue(result["success"], msg=result)
        request = frappe.get_doc("Chapter Join Request", result["data"]["request_id"])
        self.assertEqual(request.member, self.linked.member.name)
        self.assertEqual(request.docstatus, 1)

    def test_email_only_user_is_refused_with_clear_message(self):
        from verenigingen.api.chapter_join import join_chapter

        with self.as_user(self.unlinked.user):
            result = join_chapter(self.chapter.name, "I want to help")
        self.assertFalse(result["success"])
        self.assertIn("not linked to a member record", result["error"]["message"])
        self.assertEqual(self._requests_for(self.unlinked.member), [])

    def test_user_with_no_member_at_all_is_refused(self):
        from verenigingen.api.chapter_join import join_chapter

        email = f"jc1853-none-{frappe.generate_hash()[:8]}@example.com"
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        # The self_service_api gate refuses a user with no Member at all before the body runs.
        with self.as_user(email):
            with self.assertRaises(frappe.PermissionError) as ctx:
                join_chapter(self.chapter.name, "I want to help")
        self.assertIn("No member record found", str(ctx.exception))
        self.assertEqual(frappe.get_all("Chapter Join Request", filters={"owner": email}), [])

    def test_flag_no_longer_exempts_the_ownership_check(self):
        """The #1786 member_verified_by_caller flag is gone: setting it does not bypass the check."""
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.unlinked.member.name,
                "chapter": self.chapter.name,
                "introduction": "hi",
                "status": "Pending",
            }
        )
        request.flags.member_verified_by_caller = True
        with self.as_user(self.unlinked.user):
            with self.assertRaises(frappe.PermissionError):
                request.insert()

    def test_context_api_does_not_resolve_member_by_email(self):
        from verenigingen.api.chapter_join import get_chapter_join_context

        with self.as_user(self.unlinked.user):
            result = get_chapter_join_context(self.chapter.name)
        self.assertTrue(result["success"], msg=result)
        self.assertIsNone(result["data"]["member"])
        with self.as_user(self.linked.user):
            result = get_chapter_join_context(self.chapter.name)
        self.assertEqual(result["data"]["member"], self.linked.member.name)

    def _post_page(self, module, user, **form):
        import importlib

        page = importlib.import_module(module)
        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "hello",
                "website_url": "https://example.com",
                **form,
            }
        )
        frappe.local.request = frappe._dict(method="POST")
        ctx = frappe._dict()
        with self.as_user(user):
            page.get_context(ctx)
        return ctx

    def _assert_page_refuses_email_only_user(self, module):
        # The page handlers log the refusal to the Error Log by design.
        self.expectErrorLog("Error in chapter join request")
        ctx = self._post_page(module, self.unlinked.user)
        self.assertTrue(ctx.get("join_error"))
        self.assertFalse(ctx.get("join_success"))
        self.assertFalse(ctx.already_member)
        self.assertFalse(
            frappe.db.exists(
                "Chapter Member", {"member": self.unlinked.member.name, "parent": self.chapter.name}
            )
        )

    def test_chapter_join_page_does_not_join_an_email_only_user(self):
        self._assert_page_refuses_email_only_user("verenigingen.templates.pages.chapter_join")

    def test_nested_join_chapter_page_does_not_join_an_email_only_user(self):
        self._assert_page_refuses_email_only_user("verenigingen.templates.pages.verenigingen.join_chapter")

    def test_portal_page_still_joins_a_linked_member(self):
        ctx = self._post_page("verenigingen.templates.pages.chapter_join", self.linked.user)
        self.assertTrue(ctx.get("join_success"), msg=ctx.get("join_error"))
        self.assertTrue(
            frappe.db.exists(
                "Chapter Member", {"member": self.linked.member.name, "parent": self.chapter.name}
            )
        )
