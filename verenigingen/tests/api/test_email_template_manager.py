# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Meaningful test suite for verenigingen/api/email_template_manager.py

Covers the live email-template management API:
  - create_comprehensive_email_templates()  [@frappe.whitelist + @critical_api]
  - test_email_template(template_name, ...)  [@frappe.whitelist + @standard_api]
  - get_email_template(...)                  (non-whitelisted helper, rendering+fallback)

Decorated endpoints return a SERIALIZED DICT (OperationResult.to_dict(scrub_sensitive=True),
nested schema):
    success: {"success": True, "data": {...}, "meta": {...}, "timestamp": ...}
    failure: {"success": False, "error": {"message", "errors", "code", ...}}

Every Email Template the module manages is force-deleted in tearDown so we never
leave duplicate/garbage template docs on the test site.
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.api.email_template_manager import (
    create_comprehensive_email_templates,
    get_email_template,
    send_template_email,
    test_email_template,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.operation_result import OperationResult

# The exact set of Email Templates create_comprehensive_email_templates() manages.
# Kept in sync with the module's `templates` list so cleanup is exhaustive.
MANAGED_TEMPLATES = {
    "expense_approval_request": "💰 Expense Approval Required - {{ doc.name }}",
    "expense_approved": "✅ Expense Approved - {{ doc.name }}",
    "expense_rejected": "❌ Expense Rejected - {{ doc.name }}",
    "donation_confirmation": "Thank you for your donation - {{ donation_id }}",
    "donation_payment_confirmation": "Payment Received - Donation {{ donation_id }}",
    "anbi_tax_receipt": "Tax Deduction Receipt - {{ receipt_number }}",
    "termination_overdue_notification": "Overdue Termination Requests - {{ count }} items",
    "member_contact_request_received": "Contact Request Received - {{ doc.name }}",
}


class TestEmailTemplateManager(VereningingenTestCase):
    """Behaviour-level tests for the email template manager API."""

    def tearDown(self):
        # Force-delete every managed template (whether this test created it or not)
        # so the suite is self-cleaning and idempotent across runs.
        for name in MANAGED_TEMPLATES:
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True)
        frappe.db.commit()
        super().tearDown()

    def _delete_managed_templates(self):
        """Ensure a clean slate before a create call (helper, not a test body op)."""
        for name in MANAGED_TEMPLATES:
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True)
        frappe.db.commit()

    # ------------------------------------------------------------------
    # create_comprehensive_email_templates
    # ------------------------------------------------------------------
    def test_create_templates_actually_creates_named_docs(self):
        """Happy path: every named Email Template exists with the expected subject,
        use_html flag, and non-empty HTML response after a create call."""
        self._delete_managed_templates()

        result = create_comprehensive_email_templates()

        # Decorated @critical_api endpoint -> serialized nested dict
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], f"creation failed: {result.get('error')}")
        data = result["data"]
        # All 8 templates were freshly created, none pre-existed.
        self.assertEqual(data["created"], 8, f"expected 8 created, got {data}")
        self.assertEqual(data["updated"], 0)
        self.assertEqual(data["total"], 8)

        # Assert the ACTUAL effect: each named template now exists with the right content.
        for name, expected_subject in MANAGED_TEMPLATES.items():
            self.assertTrue(
                frappe.db.exists("Email Template", name),
                f"Email Template '{name}' should have been created",
            )
            doc = frappe.get_doc("Email Template", name)
            self.assertEqual(doc.subject, expected_subject, f"wrong subject for {name}")
            self.assertEqual(doc.use_html, 1, f"{name} should be flagged use_html")
            self.assertTrue(doc.response and doc.response.strip(), f"{name} response is empty")
            self.assertIn("<div", doc.response, f"{name} response should contain HTML markup")

    def test_specific_template_content_substance(self):
        """Spot-check distinctive content of specific templates so a swapped/blank
        body would be caught (not just 'a div exists')."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        anbi = frappe.get_doc("Email Template", "anbi_tax_receipt")
        self.assertIn("ANBI", anbi.response)
        self.assertIn("{{ receipt_number }}", anbi.subject)

        donation = frappe.get_doc("Email Template", "donation_confirmation")
        self.assertIn("{{ donor_name }}", donation.response)
        # The donation send context (send_donation_confirmation_email) provides a
        # FLAT key, not a `doc`, so the template must use {{ donation_amount }}.
        self.assertIn("{{ donation_amount }}", donation.response)

        approval = frappe.get_doc("Email Template", "expense_approval_request")
        self.assertIn("{{ approver_name }}", approval.response)
        self.assertIn("{{ approval_url }}", approval.response)

    def test_donation_templates_render_with_real_send_context(self):
        """REGRESSION: the donation confirmation/payment templates are sent with a
        FLAT-key context (donation_id/donation_amount/...) and NO `doc`, but the
        manager previously defined them with {{ doc.name }}/{{ doc.amount }}.
        Attribute access on an undefined `doc` raises UndefinedError at render, so
        the email was silently dropped (caught + logged by the sender). Render each
        managed template with the exact context its sender passes and assert it
        resolves to the real values with no `doc.*` left."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        donation_ctx = {
            "donation_id": "DON-RENDER-0001",
            "donation_amount": "25.00",
            "donation_date": "02-01-2026",
            "donation_status": "Paid",
            "earmarking": "General Fund",
            "donation_notes": "Keep it up",
            "donor_name": "Jane Donor",
            "organization_name": "Test Org",
            "organization_email": "info@example.com",
        }
        payment_ctx = {
            "donation_id": "DON-RENDER-0001",
            "donation_amount": "25.00",
            "payment_date": "03-01-2026",
            "payment_method": "Bank Transfer",
            "payment_reference": "REF-1",
            "earmarking": "General Fund",
            "donor_name": "Jane Donor",
            "organization_name": "Test Org",
            "organization_email": "info@example.com",
        }
        for name, ctx in (
            ("donation_confirmation", donation_ctx),
            ("donation_payment_confirmation", payment_ctx),
        ):
            tmpl = frappe.get_doc("Email Template", name)
            self.assertNotIn("doc.", tmpl.response, f"{name} must not reference an undefined doc.*")
            self.assertNotIn("doc.", tmpl.subject, f"{name} subject must not reference doc.*")
            # Render must not raise (a {{ doc.name }} would raise UndefinedError) and
            # must show the real flat-key values.
            rendered = frappe.render_template(tmpl.response, ctx)
            self.assertIn(ctx["donation_id"], rendered)
            self.assertIn("Jane Donor", rendered)

    def test_create_templates_is_idempotent(self):
        """Calling twice must NOT duplicate docs. Second call updates the existing 8
        (created=0, updated=8) and the doc count for each name stays exactly 1."""
        self._delete_managed_templates()

        first = create_comprehensive_email_templates()
        self.assertTrue(first["success"])
        self.assertEqual(first["data"]["created"], 8)
        self.assertEqual(first["data"]["updated"], 0)

        second = create_comprehensive_email_templates()
        self.assertTrue(second["success"])
        # Idempotent: nothing new created, all 8 updated-in-place.
        self.assertEqual(second["data"]["created"], 0, "second run must not create duplicates")
        self.assertEqual(second["data"]["updated"], 8)

        # Email Template autoname=Prompt -> name is the literal; there can only ever
        # be one row per name. Assert no duplicates accumulated.
        for name in MANAGED_TEMPLATES:
            count = frappe.db.count("Email Template", {"name": name})
            self.assertEqual(count, 1, f"expected exactly 1 '{name}', found {count}")

    def test_update_path_overwrites_modified_content(self):
        """If a managed template was hand-edited, a re-run restores the canonical
        subject/response via the update branch (proves update actually writes)."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        # Mutate an existing template, then re-run.
        doc = frappe.get_doc("Email Template", "expense_approved")
        doc.subject = "TAMPERED SUBJECT"
        doc.response = "<p>tampered</p>"
        doc.save()
        frappe.db.commit()

        result = create_comprehensive_email_templates()
        self.assertTrue(result["success"])
        # Everything already existed -> all updates, no creates.
        self.assertEqual(result["data"]["created"], 0)
        self.assertEqual(result["data"]["updated"], 8)

        restored = frappe.get_doc("Email Template", "expense_approved")
        self.assertEqual(restored.subject, MANAGED_TEMPLATES["expense_approved"])
        self.assertIn("✅ Expense Approved", restored.response)
        self.assertNotIn("tampered", restored.response)

    # ------------------------------------------------------------------
    # get_email_template (helper: render + fallback)
    # ------------------------------------------------------------------
    def test_get_email_template_renders_context(self):
        """Rendering an existing template substitutes context variables into both
        subject and message."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        rendered = get_email_template(
            "anbi_tax_receipt",
            context={
                "receipt_number": "RCPT-2026-007",
                "donor_name": "Jane Donor",
                "anbi_number": "ANBI-XYZ",
                "tax_year": "2026",
                "organization_name": "Test Org",
                "doc": frappe._dict({"amount": 250}),
            },
        )
        self.assertEqual(rendered["subject"], "Tax Deduction Receipt - RCPT-2026-007")
        self.assertIn("Jane Donor", rendered["message"])
        self.assertIn("ANBI-XYZ", rendered["message"])
        self.assertIn("250", rendered["message"])
        # Unsubstituted Jinja markers must not survive rendering.
        self.assertNotIn("{{ receipt_number }}", rendered["subject"])
        self.assertNotIn("{{ donor_name }}", rendered["message"])

    def test_get_email_template_missing_uses_fallback(self):
        """A non-existent template returns the supplied (rendered) fallback,
        not an exception."""
        rendered = get_email_template(
            "no_such_template_xyz",
            context={"name": "World"},
            fallback_subject="Hello {{ name }}",
            fallback_message="Body for {{ name }}",
        )
        self.assertEqual(rendered["subject"], "Hello World")
        self.assertEqual(rendered["message"], "Body for World")

    def test_get_email_template_missing_no_fallback_defaults(self):
        """Missing template with no fallback yields the documented default strings."""
        rendered = get_email_template("totally_absent_template")
        self.assertEqual(rendered["subject"], "Notification - totally_absent_template")
        self.assertEqual(rendered["message"], "This is an automated notification.")

    # ------------------------------------------------------------------
    # test_email_template (whitelisted @standard_api wrapper around get_email_template)
    # ------------------------------------------------------------------
    def test_test_email_template_endpoint_default_context(self):
        """The reporting endpoint renders a template with its built-in sample context
        and returns subject/message in the nested data payload."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        result = test_email_template("expense_approval_request")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], f"render failed: {result.get('error')}")
        data = result["data"]
        self.assertEqual(data["template_name"], "expense_approval_request")
        # Built-in sample context sets doc.name=TEST-001 and approver_name=Test Approver.
        self.assertIn("TEST-001", data["subject"])
        self.assertIn("Test Approver", data["message"])
        self.assertNotIn("{{ doc.name }}", data["subject"])

    def test_test_email_template_endpoint_custom_context(self):
        """A caller-supplied context is honoured by the endpoint."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        result = test_email_template(
            "donation_confirmation",
            test_context={
                "donor_name": "Custom Donor",
                "organization_name": "Custom Org",
                "earmarking": "General",
                "donation_date": "2026-06-16",
                "donation_id": "DON-999",
                "donation_amount": "42.00",
                "donation_status": "Paid",
                "donation_notes": "",
            },
        )
        self.assertTrue(result["success"], f"render failed: {result.get('error')}")
        data = result["data"]
        self.assertEqual(data["subject"], "Thank you for your donation - DON-999")
        self.assertIn("Custom Donor", data["message"])
        self.assertIn("42", data["message"])

    def test_test_email_template_missing_returns_fallback_success(self):
        """Rendering a missing template via the endpoint does NOT error: get_email_template
        swallows DoesNotExistError and returns a fallback, so the endpoint reports success
        with the default fallback subject. This documents the (intentional) fallback contract."""
        result = test_email_template("nonexistent_template_abc")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        # Default fallback subject from get_email_template.
        self.assertEqual(result["data"]["subject"], "Notification - nonexistent_template_abc")
        self.assertEqual(result["data"]["message"], "This is an automated notification.")

    # ------------------------------------------------------------------
    # Frappe-native rendering interplay (latent inconsistency guard)
    # ------------------------------------------------------------------
    def test_use_html_set_and_response_html_populated_for_native_render(self):
        """With use_html=1, the module must ALSO populate `response_html` so Frappe's
        STANDARD email-template rendering produces a real (non-empty) body.

        Frappe's EmailTemplate.response_ property returns `response_html` when
        use_html=1 (see frappe/.../email_template.py). If `response_html` were left
        empty, native sends/renders (get_formatted_email / response_) would yield an
        EMPTY body. The fix sets response_html == response in both the create and
        update paths, so native rendering and the module's own get_email_template()
        helper now agree.
        """
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        doc = frappe.get_doc("Email Template", "donation_confirmation")
        # Both fields carry the same HTML; response_html is NOT empty.
        self.assertTrue(doc.response and doc.response.strip(), "content should be in response")
        self.assertTrue(
            doc.response_html and doc.response_html.strip(),
            "response_html must be populated so Frappe-native rendering is non-empty",
        )
        # Frappe's Code field (response_html) normalizes HTML on save (whitespace
        # collapse, auto-closed tags), so it won't be byte-identical to the TextEditor
        # `response`. What matters is that response_html carries the same real markup.
        self.assertIn("<div", doc.response_html, "response_html must carry the HTML body")
        self.assertIn("{{ donor_name }}", doc.response_html, "response_html must carry the template content")

        # response_ (the property Frappe uses) returns response_html when use_html=1,
        # so it must be the real HTML body, not empty.
        self.assertEqual(doc.use_html, 1)
        self.assertTrue(doc.response_ and doc.response_.strip(), "response_ must be non-empty")
        self.assertIn("<div", doc.response_)

        # Frappe's native renderer (get_formatted_email -> response_) now yields a
        # NON-empty body containing the substituted content.
        native = doc.get_formatted_email({"donor_name": "X", "donation_id": "D1", "donation_amount": "1"})
        self.assertTrue(
            native["message"].strip(),
            "Frappe-native render must produce a non-empty body now that response_html is set",
        )
        self.assertIn("X", native["message"], "native render must substitute donor_name")
        self.assertIn("€1", native["message"], "native render must substitute donation_amount")

        # The module's own helper renders the same real content (both paths agree).
        module_rendered = get_email_template(
            "donation_confirmation",
            context={
                "donor_name": "X",
                "organization_name": "Org",
                "earmarking": "G",
                "donation_date": "2026-01-01",
                "donation_id": "D1",
                "donation_amount": "1",
                "donation_status": "Paid",
                "donation_notes": "",
            },
        )
        self.assertIn("X", module_rendered["message"])
        self.assertTrue(module_rendered["message"].strip())

    # ------------------------------------------------------------------
    # get_email_template — generic render-error fallback (not DoesNotExist)
    # ------------------------------------------------------------------
    def test_get_email_template_render_error_returns_fallback(self):
        """A template that EXISTS but whose body raises during Jinja rendering
        (e.g. malformed/forbidden expression) must NOT propagate: get_email_template
        catches the generic Exception and returns the supplied fallback strings.

        This is distinct from the DoesNotExistError path — the template is real,
        but rendering it blows up.
        """
        broken_name = f"broken_render_template_{frappe.generate_hash(length=6)}"
        # Syntactically-VALID Jinja that raises at RENDER time (division by zero).
        # Email Template validates syntax on save, so we cannot persist a malformed
        # template; this passes validation but blows up when get_email_template
        # renders it, hitting the generic Exception fallback branch.
        broken = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": broken_name,
                "subject": "Broken {{ 1 / 0 }}",
                "response": "<p>Broken {{ 1 / 0 }}</p>",
                "use_html": 1,
                "response_html": "<p>Broken {{ 1 / 0 }}</p>",
                "enabled": 1,
            }
        )
        broken.insert()
        frappe.db.commit()
        self.addCleanup(lambda: frappe.delete_doc("Email Template", broken_name, force=True))

        self.expectErrorLog("Email Template Rendering Error")
        rendered = get_email_template(
            broken_name,
            context={"name": "Ignored"},
            fallback_subject="Fallback Subject",
            fallback_message="Fallback Message",
        )
        # The render error was swallowed; the explicit fallbacks are returned.
        self.assertEqual(rendered["subject"], "Fallback Subject")
        self.assertEqual(rendered["message"], "Fallback Message")

    def test_get_email_template_render_error_default_fallback(self):
        """Render error with no explicit fallback yields the documented default
        subject/message (the `or` defaults in the except branch)."""
        broken_name = f"broken_render_default_{frappe.generate_hash(length=6)}"
        # Valid syntax, raises at render time (see sibling test).
        broken = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": broken_name,
                "subject": "OK subject",
                "response": "<p>{{ 1 / 0 }}</p>",
                "use_html": 1,
                "response_html": "<p>{{ 1 / 0 }}</p>",
                "enabled": 1,
            }
        )
        broken.insert()
        frappe.db.commit()
        self.addCleanup(lambda: frappe.delete_doc("Email Template", broken_name, force=True))

        self.expectErrorLog("Email Template Rendering Error")
        rendered = get_email_template(broken_name)
        self.assertEqual(rendered["subject"], f"Notification - {broken_name}")
        self.assertEqual(rendered["message"], "This is an automated notification.")

    # ------------------------------------------------------------------
    # send_template_email — renders a template and dispatches via EmailService
    # ------------------------------------------------------------------
    # send_template_email's own RETURN value just mirrors the service's success
    # flag, which is site-dependent (mail config). The site-independent, regression-
    # catching contract is WHAT it hands to the EmailService: the RENDERED (not raw)
    # subject/message, the recipients, and the notification_key. We observe the
    # EmailService dispatch boundary (the external send) by patching the service
    # factory the function imports at call time and capturing send_simple_email's
    # arguments — no business logic is mocked; the template render + plumbing all run.

    def _spy_email_service(self):
        """Patch the EmailService factory send_template_email imports and return a
        MagicMock whose .send_simple_email records its call and returns success.
        Yields (patcher, spy_send) — caller starts/stops the patcher."""
        spy_service = MagicMock()
        spy_service.send_simple_email.return_value = OperationResult.ok({"sent": True})
        patcher = patch(
            "verenigingen.services.communication.email_service.get_email_service",
            return_value=spy_service,
        )
        return patcher, spy_service.send_simple_email

    def test_send_template_email_passes_rendered_content_to_service(self):
        """Happy path: the RENDERED subject/message (context substituted) and the
        recipients + notification_key are handed to EmailService.send_simple_email.
        A regression that dropped the body or sent the raw template would fail."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        recipient = f"send-target-{frappe.generate_hash(length=6)}@example.com"
        patcher, spy_send = self._spy_email_service()
        patcher.start()
        try:
            result = send_template_email(
                "donation_confirmation",
                recipients=[recipient],
                context={
                    "donor_name": "Sent Donor",
                    "organization_name": "Send Org",
                    "earmarking": "General",
                    "donation_date": "2026-06-16",
                    "donation_id": "DON-SEND",
                    "donation_amount": "77.00",
                    "donation_status": "Paid",
                    "donation_notes": "",
                },
                notification_key="member_status_change",
            )
        finally:
            patcher.stop()

        self.assertTrue(result, "service reported success -> function returns True")
        spy_send.assert_called_once()
        kwargs = spy_send.call_args.kwargs
        self.assertEqual(kwargs["recipients"], [recipient])
        self.assertEqual(kwargs["notification_key"], "member_status_change")
        # Subject was rendered: '{{ donation_id }}' -> 'DON-SEND'.
        self.assertEqual(kwargs["subject"], "Thank you for your donation - DON-SEND")
        # Body carries the substituted context, not the raw Jinja markers.
        self.assertIn("Sent Donor", kwargs["message"])
        self.assertIn("77", kwargs["message"])
        self.assertNotIn("{{ donor_name }}", kwargs["message"])

    def test_send_template_email_without_notification_key_passes_none(self):
        """Omitting notification_key (the warning branch) still dispatches, and the
        service receives notification_key=None (not a defaulted test key)."""
        self._delete_managed_templates()
        create_comprehensive_email_templates()

        recipient = f"nokey-target-{frappe.generate_hash(length=6)}@example.com"
        patcher, spy_send = self._spy_email_service()
        patcher.start()
        try:
            result = send_template_email(
                "expense_approved",
                recipients=[recipient],
                context={
                    "volunteer_name": "No Key Vol",
                    "approved_by_name": "Boss",
                    "company": "Org",
                    "formatted_amount": "€10.00",
                    "approved_on": "2026-06-16",
                    "doc": frappe._dict({"name": "EXP-NOKEY", "description": "d"}),
                },
                # notification_key intentionally omitted -> warning branch.
            )
        finally:
            patcher.stop()

        self.assertTrue(result)
        kwargs = spy_send.call_args.kwargs
        self.assertIsNone(kwargs["notification_key"])
        # The expense_approved template rendered with the volunteer's name.
        self.assertIn("No Key Vol", kwargs["message"])

    def test_send_template_email_missing_template_passes_fallback_content(self):
        """A non-existent template does not raise: get_email_template returns the
        default fallback subject/message, and THOSE exact fallback strings are what
        reach the EmailService."""
        recipient = f"missing-tmpl-{frappe.generate_hash(length=6)}@example.com"
        patcher, spy_send = self._spy_email_service()
        patcher.start()
        try:
            result = send_template_email(
                "no_such_template_for_send_xyz",
                recipients=[recipient],
                context={},
                notification_key="member_status_change",
            )
        finally:
            patcher.stop()

        self.assertTrue(result)
        kwargs = spy_send.call_args.kwargs
        # The documented default fallback strings from get_email_template.
        self.assertEqual(kwargs["subject"], "Notification - no_such_template_for_send_xyz")
        self.assertEqual(kwargs["message"], "This is an automated notification.")
