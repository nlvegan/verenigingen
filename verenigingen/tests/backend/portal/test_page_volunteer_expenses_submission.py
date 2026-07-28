"""
Submission-path tests for the volunteer expenses portal page
(verenigingen.templates.pages.volunteer.expenses).

The sibling module test_page_volunteer_expenses.py covers get_context and the
read-only data endpoints. This module covers the two branches a real browser
actually exercises and that no test reaches today:

- ``submit_expense`` accepting the payload as an HTML-escaped JSON *string*
  (expenses.py:172-178) -- the form-submission fallback -- and the guards that
  run on it: volunteer-parameter tampering and organization membership. A
  volunteer must not be able to file a claim in another volunteer's name, nor
  against a chapter/team they do not belong to.
- ``upload_expense_receipt`` (expenses.py:49-140), which is ~40 uncovered lines
  of file-object handling reached through frappe.form_dict.

Each denial is paired with the same request made legitimately, so a guard that
degenerates into "always fail" is caught. End-to-end claim CREATION is not
asserted here: it needs an auto-created Employee plus company/expense-account
configuration that this test site does not provide, and the submission stops at
that step for every caller.
"""

import base64
import io
import json

import frappe
from frappe.utils import today

from verenigingen.templates.pages.volunteer import expenses
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles


class TestVolunteerExpenseSubmissionGuards(EnhancedTestCase):
    """submit_expense must only ever file a claim for the calling volunteer."""

    def setUp(self):
        super().setUp()
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.member, self.user = self._make_member_with_user("Filer")
        self.volunteer = self.create_test_volunteer(member=self.member.name, volunteer_name="Expense Filer")

        # A second, unrelated volunteer whose identity the caller must not be
        # able to borrow.
        self.other_member, self.other_user = self._make_member_with_user("Other")
        self.other_volunteer = self.create_test_volunteer(
            member=self.other_member.name, volunteer_name="Other Volunteer"
        )

        # A chapter the caller is NOT a member of.
        self.foreign_chapter = self.create_test_chapter(
            chapter_name=f"Foreign Chapter {frappe.generate_hash()[:6]}"
        )
        # The caller's own chapter, used as the control.
        self.own_chapter = self.create_test_chapter(chapter_name=f"Own Chapter {frappe.generate_hash()[:6]}")
        self._add_member_to_chapter(self.own_chapter, self.member.name)

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _make_member_with_user(self, label):
        email = f"expsub-{label.lower()}-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name=label,
            last_name="Volunteer",
            email=email,
            birth_date="1990-01-01",
        )
        email = member.email
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": label,
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member.db_set("user", email)
        member.reload()
        # The expense endpoints require SecurityLevel.MEDIUM, which the security
        # framework grants through an assigned role PROFILE, not a bare role. A
        # real portal volunteer holds the "Verenigingen Volunteer" profile (the
        # profile that maps to MEDIUM for self-service operations); a user with
        # only the bare role is denied before the body runs.
        grant_matching_role_profiles(email, "Verenigingen Volunteer")
        return member, email

    def _add_member_to_chapter(self, chapter, member_name):
        chapter.append(
            "members",
            {
                "member": member_name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

    def _payload(self, **overrides):
        data = {
            "description": "Trainticket to the members' meeting",
            "amount": 12.5,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.own_chapter.name,
            "category": "Travel",
        }
        data.update(overrides)
        return data

    # -------------------------------------------------- volunteer impersonation

    def test_submit_expense_rejects_a_payload_naming_another_volunteer(self):
        """The volunteer field is caller-supplied, so it must be cross-checked.

        The portal template echoes the volunteer id back in the form payload; the
        service compares it against the volunteer resolved from the session and
        refuses a mismatch instead of trusting the client. The paired call with
        the caller's OWN id proves this is an identity comparison and not a
        blanket rejection of the volunteer field.
        """
        foreign = self._payload(volunteer=self.other_volunteer.name)
        own = self._payload(volunteer=self.volunteer.name)

        with self.as_user(self.user):
            with self.assertRaises(frappe.PermissionError) as raised:
                expenses.submit_expense(json.dumps(foreign))
            own_result = expenses.submit_expense(json.dumps(own))

        self.assertIn("tampering", str(raised.exception).lower())
        self.assertNotIn("tampering", json.dumps(own_result).lower())

    # ------------------------------------------------- organization membership

    def test_submit_expense_rejects_a_chapter_the_volunteer_does_not_belong_to(self):
        """A volunteer must not be able to charge an expense to a foreign chapter.

        Both calls send the identical payload and differ only in the chapter, so a
        guard that failed everything (or nothing) would not produce two different
        outcomes.
        """
        with self.as_user(self.user):
            foreign = expenses.submit_expense(json.dumps(self._payload(chapter=self.foreign_chapter.name)))
            own = expenses.submit_expense(json.dumps(self._payload(chapter=self.own_chapter.name)))

        self.assertFalse(foreign["success"])
        self.assertIn("Chapter membership required", foreign["message"])
        self.assertIn(self.foreign_chapter.name, foreign["message"])

        # The caller's own chapter gets past the membership guard: the submission
        # proceeds to employee/company setup, which is what fails instead.
        self.assertNotIn("Chapter membership required", own["message"])
        self.assertNotEqual(foreign["message"], own["message"])

    def test_submit_expense_html_escaped_payload_is_unescaped_before_parsing(self):
        """Form submissions arrive HTML-escaped; the endpoint must unescape first.

        Without the html.unescape() step the json.loads() would fail on the
        escaped quotes and the request would never reach the guards at all.
        """
        escaped = json.dumps(self._payload(chapter=self.foreign_chapter.name)).replace('"', "&quot;")

        with self.as_user(self.user):
            result = expenses.submit_expense(escaped)

        # Proof the payload was parsed: the chapter-specific guard fired.
        self.assertFalse(result["success"])
        self.assertIn(self.foreign_chapter.name, result["message"])

    def test_submit_expense_reports_missing_required_fields(self):

        with self.as_user(self.user):
            result = expenses.submit_expense(json.dumps({"organization_type": "Chapter"}))

        self.assertFalse(result["success"])
        self.assertTrue(any("description" in err for err in result["errors"]))
        self.assertTrue(any("amount" in err for err in result["errors"]))


class TestVolunteerExpenseReceiptUpload(EnhancedTestCase):
    """upload_expense_receipt has to cope with three shapes of "uploaded file".

    The browser posts multipart/form-data, so the production path is a werkzeug
    FileStorage on ``frappe.request.files``. The endpoint additionally scans
    ``frappe.form_dict`` under four field names for the legacy form post. These
    tests bind a REAL werkzeug request (not a stub) so the multipart branch is
    exercised end to end.
    """

    def setUp(self):
        super().setUp()
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1
        self._request_was_bound = hasattr(frappe.local, "request")

        self.member, self.user = self._make_member_with_user("Uploader")
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Receipt Uploader"
        )

    def tearDown(self):
        for key in ("receipt", "file", "_file", "uploaded_file"):
            frappe.local.form_dict.pop(key, None)
        if not self._request_was_bound:
            try:
                del frappe.local.request
            except AttributeError:
                pass
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _make_member_with_user(self, label):
        email = f"exprec-{label.lower()}-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name=label,
            last_name="Volunteer",
            email=email,
            birth_date="1990-01-01",
        )
        email = member.email
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": label,
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member.db_set("user", email)
        member.reload()
        grant_matching_role_profiles(email, "Verenigingen Volunteer")
        return member, email

    def _bind_request(self, files=None):
        """Bind a real werkzeug Request, the object Frappe puts on frappe.local
        during an HTTP call. Without it frappe.request is unbound and every
        branch of the endpoint collapses into the outer exception handler."""
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        builder = EnvironBuilder(
            method="POST",
            path="/api/method/verenigingen.templates.pages.volunteer.expenses.upload_expense_receipt",
            data=files or {},
        )
        frappe.local.request = Request(builder.get_environ())

    # ------------------------------------------------------- multipart (real) path

    def test_multipart_upload_is_returned_base64_encoded(self):
        content = b"%PDF-1.4 fake receipt bytes"
        self._bind_request({"receipt": (io.BytesIO(content), "receipt.pdf", "application/pdf")})

        with self.as_user(self.user):
            result = expenses.upload_expense_receipt()

        self.assertTrue(result["success"], result)
        self.assertEqual(result["file_name"], "receipt.pdf")
        self.assertEqual(result["content_type"], "application/pdf")
        # The bytes must survive the round trip unchanged.
        self.assertEqual(base64.b64decode(result["file_content"]), content)

    def test_no_file_in_the_request_is_reported_not_raised(self):
        self._bind_request()

        with self.as_user(self.user):
            result = expenses.upload_expense_receipt()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "No file uploaded")

    # -------------------------------------------------------- form_dict fallback

    def test_dict_shaped_upload_from_form_dict_is_accepted(self):
        content = b"jpeg-bytes"
        self._bind_request()

        with self.as_user(self.user):
            # frappe.set_user() resets frappe.local.form_dict, so the request
            # fields have to be planted AFTER switching user.
            frappe.local.form_dict["receipt"] = {
                "filename": "receipt.jpg",
                "content": content,
                "content_type": "image/jpeg",
            }
            result = expenses.upload_expense_receipt()

        self.assertTrue(result["success"], result)
        self.assertEqual(result["file_name"], "receipt.jpg")
        self.assertEqual(result["content_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(result["file_content"]), content)

    def test_dict_shaped_upload_without_content_type_defaults_to_octet_stream(self):
        self._bind_request()

        with self.as_user(self.user):
            frappe.local.form_dict["receipt"] = {"filename": "receipt.png", "content": b"png-bytes"}
            result = expenses.upload_expense_receipt()

        self.assertTrue(result["success"], result)
        self.assertEqual(result["content_type"], "application/octet-stream")

    def test_alternate_field_names_are_accepted(self):
        """The endpoint scans four field names because the legacy form and the
        current JS post the file under different keys."""
        self._bind_request()

        with self.as_user(self.user):
            frappe.local.form_dict["uploaded_file"] = {"filename": "alt.jpg", "content": b"jpeg"}
            result = expenses.upload_expense_receipt()

        self.assertTrue(result["success"], result)
        self.assertEqual(result["file_name"], "alt.jpg")

    # ------------------------------------------------------------ rejected inputs

    def test_empty_file_is_rejected(self):
        self._bind_request()

        with self.as_user(self.user):
            frappe.local.form_dict["receipt"] = {"filename": "empty.pdf", "content": b""}
            result = expenses.upload_expense_receipt()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Empty file uploaded")

    def test_unrecognised_file_object_is_rejected_rather_than_stored(self):
        """A bare string in the receipt field is neither a file object nor a
        {filename, content} dict and must not be treated as an upload."""
        self._bind_request()

        with self.as_user(self.user):
            frappe.local.form_dict["receipt"] = "/etc/passwd"
            result = expenses.upload_expense_receipt()

        self.assertFalse(result["success"])
        self.assertIn("Unsupported file object type", result["error"])
