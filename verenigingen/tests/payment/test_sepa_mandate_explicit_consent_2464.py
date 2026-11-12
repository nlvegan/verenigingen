"""Explicit member consent to the SEPA mandate text (#2464).

Driven through the real whitelisted endpoint ``setup_sepa_direct_debit`` as a real
plain member (Member.user linked). Stand-ins, stated: the portal User is linked via
PortalSelfServiceTestMixin; the request (for the IP) is a real werkzeug Request bound
the way tests/security/test_client_ip_sources.py binds one; the "legacy mandate" is a
current-schema mandate whose consent columns are then set NULL through the column
(that is what a row created before this change looks like).
"""

from unittest.mock import patch

import frappe
from frappe.auth import HTTPRequest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api.member import sepa_api
from verenigingen.services.payment import sepa_mandate_consent as consent_module
from verenigingen.services.payment.sepa_mandate_consent import (
    DEFAULT_MANDATE_CONSENT_TEXT,
    get_mandate_consent_text,
    hash_consent_text,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.validation.iban_validator import generate_test_iban

PROXY = "127.0.0.1"
REAL_CLIENT = "203.0.113.77"
SPOOF = "198.51.100.9"
CONSENT_FIELDS = ["consent_source", "consent_timestamp", "consent_text", "consent_ip"]


class TestSepaMandateExplicitConsent(PortalSelfServiceTestMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._orig_request = getattr(frappe.local, "request", None)
        self._orig_request_ip = getattr(frappe.local, "request_ip", None)
        self.addCleanup(self._restore_request_2464)
        self.member = self.create_test_member(birth_date="1990-01-01")
        self.user = self._link_member_to_user(self.member)

    def _restore_request_2464(self):
        frappe.local.request = self._orig_request
        frappe.local.request_ip = self._orig_request_ip

    def _text_is(self, text):
        """Make the mandate text `text` for the endpoint under test.

        Stand-in, stated: the Settings READ is replaced here because the endpoint commits,
        which would persist a Settings write past this test and a commit to restore it is
        a bare-commit ratchet finding. The Settings read itself (and the empty fallback)
        is covered without the endpoint in test_empty_settings_text_falls_back_to_default.
        """
        patcher = patch.object(consent_module, "get_mandate_consent_text", return_value=text)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install_spoofed_xff_request_2464(self):
        environ = EnvironBuilder(
            method="POST", path="/x", headers={"X-Forwarded-For": f"{SPOOF}, {REAL_CLIENT}"}, data=b"{}"
        ).get_environ()
        environ["REMOTE_ADDR"] = PROXY
        frappe.local.request = Request(environ)
        HTTPRequest.__new__(HTTPRequest).set_request_ip()

    def _sign_via_endpoint_2464(self, **kwargs):
        with self._as_user(self.user.name):
            return sepa_api.setup_sepa_direct_debit(
                iban=kwargs.pop("iban", generate_test_iban("TEST")), account_holder_name="Test Holder", **kwargs
            )

    def _consenting_args(self):
        # Looked up on the module so a `_text_is` patch is what the "page" shows.
        return {
            "consent": 1,
            "consent_text_hash": hash_consent_text(consent_module.get_mandate_consent_text()),
        }

    def _member_mandate_rows_2464(self):
        return frappe.get_all("SEPA Mandate", filters={"member": self.member.name}, fields=["name", *CONSENT_FIELDS])

    def test_consent_creates_mandate_with_timestamp_snapshot_and_trusted_ip(self):
        self._text_is("Custom mandate text\nline two <b>x</b>")
        self._install_spoofed_xff_request_2464()
        result = self._sign_via_endpoint_2464(**self._consenting_args())
        self.assertTrue(result.get("success"), msg=result)
        (row,) = self._member_mandate_rows_2464()
        self.assertEqual(row.consent_source, "Member consent")
        self.assertEqual(row.consent_text, "Custom mandate text\nline two <b>x</b>")
        self.assertTrue(row.consent_timestamp)
        self.assertEqual(row.consent_ip, REAL_CLIENT)

    def test_empty_settings_text_falls_back_to_default(self):
        # No endpoint call, so nothing commits and the harness rollback undoes the write.
        frappe.db.set_single_value("Verenigingen Settings", "sepa_mandate_consent_text", "   ")
        self.assertEqual(get_mandate_consent_text(), DEFAULT_MANDATE_CONSENT_TEXT)
        frappe.db.set_single_value("Verenigingen Settings", "sepa_mandate_consent_text", "Configured wording")
        self.assertEqual(get_mandate_consent_text(), "Configured wording")

    def test_admin_configured_markup_is_rendered_escaped_on_the_dashboard(self):
        """The real template line that prints the text, rendered with a hostile Settings value.

        Stand-in, stated: the whole page cannot be rendered outside a request (it extends the
        web base and needs a full context), so the one template line holding the text is cut out
        of the real file and rendered through frappe.render_template.
        """
        import os

        import verenigingen.templates.pages as pages

        with open(os.path.join(os.path.dirname(pages.__file__), "payment_dashboard.html")) as f:
            line = next(ln for ln in f if 'id="sepa-mandate-consent-text"' in ln)
        hostile = "<script>alert(1)</script> & <img src=x onerror=alert(2)>"
        out = frappe.render_template(
            line, {"mandate_consent_text": hostile, "mandate_consent_text_hash": '"><script>h</script>'}
        )
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; ", out)

    def test_snapshot_is_the_text_the_page_would_show(self):
        self.assertTrue(self._sign_via_endpoint_2464(**self._consenting_args()).get("success"))
        (row,) = self._member_mandate_rows_2464()
        self.assertEqual(row.consent_text, get_mandate_consent_text())

    def test_missing_or_false_consent_is_refused_identically_and_creates_nothing(self):
        iban_before = frappe.db.get_value("Member", self.member.name, "iban")
        hashed = hash_consent_text(get_mandate_consent_text())
        attempts = [
            {},
            {"consent_text_hash": hashed},
            {"consent": 0, "consent_text_hash": hashed},
            {"consent": "0", "consent_text_hash": hashed},
            {"consent": "false", "consent_text_hash": hashed},
            {"consent": "", "consent_text_hash": hashed},
            {"consent": False, "consent_text_hash": hashed},
        ]
        results = [self._sign_via_endpoint_2464(**a) for a in attempts]
        for r in results:
            self.assertFalse(r.get("success"), msg=r)
            self.assertEqual(r, results[0])
        self.assertEqual(self._member_mandate_rows_2464(), [])
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "iban"), iban_before)

    def test_text_changed_since_render_is_refused(self):
        stale = hash_consent_text(get_mandate_consent_text())
        self._text_is(f"Edited after render {frappe.generate_hash(length=8)}")
        result = self._sign_via_endpoint_2464(consent=1, consent_text_hash=stale)
        self.assertFalse(result.get("success"), msg=result)
        self.assertEqual(self._member_mandate_rows_2464(), [])

    def test_editing_settings_later_does_not_change_an_existing_snapshot(self):
        self._text_is("Original wording")
        self.assertTrue(self._sign_via_endpoint_2464(**self._consenting_args()).get("success"))
        self._text_is("Rewritten wording")
        (row,) = self._member_mandate_rows_2464()
        self.assertEqual(row.consent_text, "Original wording")
        # A later ordinary save of the mandate (any lifecycle step) must not re-read Settings.
        mandate = frappe.get_doc("SEPA Mandate", row.name)
        mandate.notes = "touched after the Settings edit"
        mandate.save()
        self.assertEqual(frappe.db.get_value("SEPA Mandate", row.name, "consent_text"), "Original wording")

    def test_member_cannot_insert_a_mandate_directly_without_the_consent_flow(self):
        with self._as_user(self.user.name):
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(
                    {
                        "doctype": "SEPA Mandate",
                        "member": self.member.name,
                        "account_holder_name": "X",
                        "iban": generate_test_iban("TEST"),
                        "sign_date": frappe.utils.today(),
                        "status": "Active",
                        "is_active": 1,
                        "used_for_memberships": 1,
                        "mandate_type": "RCUR",
                        "consent_source": "Member consent",
                        "consent_text": "forged",
                    }
                ).insert()
        self.assertEqual(self._member_mandate_rows_2464(), [])

    def test_donation_hook_current_refusal_for_a_non_staff_caller_documents_status_quo(self):
        """Documents the CURRENT refusal of SEPAGateway._create_sepa_mandate for a non-staff caller.

        NOT guard coverage: secure_document_operation refuses this caller before the consent
        guard is reached, so this stays green with the guard removed. It becomes coverage of
        enforce_consent_provenance only once #2423 is fixed. Real gateway method, real Donor,
        real (non-staff) session user; a refusal must create nothing.
        """
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        donor = self.create_test_donor(donor_name="No Consent Donor")
        donation = self.create_test_donation(
            donor=donor.name, amount=15.0, mode_of_payment="SEPA Direct Debit", paid=0
        )
        iban = generate_test_iban("TEST")
        with self._as_user(self.user.name):
            created = pg.SEPAGateway()._create_sepa_mandate(
                donation, iban, {"donor_iban": iban, "donor_name": "No Consent Donor"}
            )
        self.assertIsNone(created)
        self.assertFalse(frappe.db.exists("SEPA Mandate", {"account_holder_name": "No Consent Donor"}))

    def _staff_mandate(self, **extra):
        doc = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "account_holder_name": "Staff Entered",
                "iban": generate_test_iban("TEST"),
                "sign_date": frappe.utils.today(),
                "status": "Active",
                "is_active": 1,
                "used_for_memberships": 1,
                "mandate_type": "RCUR",
                **extra,
            }
        )
        doc.insert()
        return doc

    def test_staff_created_mandate_has_marker_and_no_consent_record(self):
        doc = self._staff_mandate(consent_text="staff typed this", consent_timestamp="2020-01-01 00:00:00")
        row = frappe.db.get_value("SEPA Mandate", doc.name, CONSENT_FIELDS, as_dict=True)
        self.assertEqual(row.consent_source, "Staff entered")
        self.assertFalse(row.consent_text)
        self.assertFalse(row.consent_timestamp)
        self.assertFalse(row.consent_ip)

    def test_legacy_active_mandate_without_consent_fields_stays_active(self):
        doc = self._staff_mandate()
        frappe.db.set_value("SEPA Mandate", doc.name, {f: None for f in CONSENT_FIELDS}, update_modified=False)
        legacy = frappe.get_doc("SEPA Mandate", doc.name)
        legacy.notes = "re-saved"
        legacy.save()
        legacy.reload()
        self.assertEqual((legacy.status, legacy.is_active), ("Active", 1))
        self.assertFalse(legacy.consent_source)

    # --- the consent record is evidence: immutable after insert, for everyone (F1) ---

    def _member_signed_mandate(self):
        self._text_is("Original wording")
        self.assertTrue(self._sign_via_endpoint_2464(**self._consenting_args()).get("success"))
        (row,) = self._member_mandate_rows_2464()
        return row

    def _assert_consent_row_unchanged(self, before):
        after = frappe.db.get_value("SEPA Mandate", before.name, CONSENT_FIELDS, as_dict=True)
        for f in CONSENT_FIELDS:
            self.assertEqual(after[f], before[f], msg=f)

    def test_member_cannot_edit_consent_fields_via_client_set_value(self):
        from frappe.client import set_value

        before = self._member_signed_mandate()
        with self._as_user(self.user.name):
            with self.assertRaises(frappe.PermissionError):
                set_value("SEPA Mandate", before.name, "consent_text", "FORGED")
            with self.assertRaises(frappe.PermissionError):
                set_value(
                    "SEPA Mandate",
                    before.name,
                    {"consent_source": "Member consent", "consent_ip": "1.2.3.4"},
                )
        self._assert_consent_row_unchanged(before)

    def test_member_cannot_edit_consent_fields_via_whole_doc_save(self):
        """frappe.client.save is what a REST PUT of the whole document runs."""
        from frappe.client import save

        before = self._member_signed_mandate()
        for field, value in (
            ("consent_text", "FORGED"),
            ("consent_ip", "1.2.3.4"),
            ("consent_source", "Staff entered"),
            ("consent_timestamp", "2001-01-01 00:00:00"),
        ):
            doc = frappe.get_doc("SEPA Mandate", before.name).as_dict()
            doc[field] = value
            with self._as_user(self.user.name):
                with self.assertRaises(frappe.PermissionError, msg=field):
                    save(frappe.as_json(doc))
        self._assert_consent_row_unchanged(before)

    def test_staff_cannot_edit_consent_fields_after_insert_either(self):
        from frappe.client import set_value

        before = self._member_signed_mandate()
        with self.assertRaises(frappe.PermissionError):
            set_value("SEPA Mandate", before.name, "consent_text", "FORGED")
        with self.assertRaises(frappe.PermissionError):
            set_value("SEPA Mandate", before.name, "consent_ip", "1.2.3.4")
        self._assert_consent_row_unchanged(before)

    def test_staff_marker_row_cannot_be_upgraded_to_member_consent(self):
        doc = self._staff_mandate()
        doc.consent_source = "Member consent"
        doc.consent_text = "fabricated"
        with self.assertRaises(frappe.PermissionError):
            doc.save()

    def test_ordinary_lifecycle_saves_still_work_after_consent(self):
        """Control: the guard must not refuse writers that leave the consent fields alone."""
        before = self._member_signed_mandate()
        mandate = frappe.get_doc("SEPA Mandate", before.name)
        mandate.notes = "touched"
        mandate.save()
        mandate.status = "Cancelled"
        mandate.save()
        mandate.reload()
        self.assertEqual(mandate.status, "Cancelled")
        self._assert_consent_row_unchanged(before)
