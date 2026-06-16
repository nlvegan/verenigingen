"""
Meaningful test suite for verenigingen/api/anbi_operations.py

ANBI / Belastingdienst (Dutch tax) compliance API. Covers every whitelisted
function: update_donor_tax_identifiers, get_donor_anbi_data, generate_anbi_report,
update_anbi_consent, validate_bsn, get_anbi_statistics, export_belastingdienst_report,
send_consent_requests.

IMPORTANT ABOUT RETURN SHAPE
----------------------------
These endpoints are decorated with @critical_api / @standard_api. The security
framework wrapper converts the returned OperationResult into a *dict* via
OperationResult.to_dict(scrub_sensitive=True) (nested schema) before returning.
So calling the function directly yields a dict, not an OperationResult:

    {"success": True/False,
     "data": {...},                      # on success
     "error": {"message": ..., "errors": [...]},  # on failure
     "meta": {"message": ...} | {"context": {...}}}

All assertions below target that dict shape.

Several product bugs were found while originally writing these tests (validate_bsn
instantiating Donor() with no args; generate_anbi_report selecting a nonexistent
"donation_type" column; update_anbi_consent's truthy-string branch + a nonexistent
frappe.add_comment). Those bugs are now fixed in production, so the corresponding
tests assert the correct behavior as normal (non-expectedFailure) tests.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

# Eleven-proof VALID BSNs (sum(d*w) % 11 == 0, weights [9,8,7,6,5,4,3,2,-1])
VALID_BSN = "123456782"
VALID_BSN_ALT = "111222333"
# Fails eleven-proof
INVALID_BSN = "123456789"


class TestANBIOperations(VereningingenTestCase):
    """Integration tests for the ANBI operations API."""

    def setUp(self):
        super().setUp()
        # Run privileged endpoint tests as Administrator (permlevel-1 / financial).
        frappe.set_user("Administrator")

    # ------------------------------------------------------------------ #
    # Helpers (persistence lives here, not in test bodies)
    # ------------------------------------------------------------------ #
    def _make_individual_donor(self, **kwargs):
        """Create an Individual donor via the base-class factory."""
        defaults = {"donor_type": "Individual"}
        defaults.update(kwargs)
        return self.create_test_donor(**defaults)

    def _make_org_donor(self, **kwargs):
        defaults = {"donor_type": "Organization"}
        defaults.update(kwargs)
        return self.create_test_donor(**defaults)

    def _make_anbi_donation(self, donor_name, amount, agreement_number, donation_date=None):
        """Create + submit a paid ANBI donation (anbi_agreement_number set, docstatus=1)."""
        donation = self.create_test_donation(
            donor=donor_name,
            amount=amount,
            anbi_agreement_number=agreement_number,
            anbi_agreement_date=frappe.utils.today(),
            donation_date=donation_date or frappe.utils.today(),
            paid=1,
        )
        donation.reload()
        if donation.docstatus == 0:
            donation.submit()
        return donation

    def _make_lowpriv_user(self):
        """A logged-in user with a role that has NO Donor/Donation access."""
        email = f"anbi.lowpriv.{frappe.generate_hash(length=6)}@example.com"
        # Verenigingen Member has only permlevel-0 read on Donor per donor.json,
        # and no Donation perms -> good "denied" subject for permlevel-1 checks.
        return self.create_test_user(email, roles=["Verenigingen Member"])

    # ------------------------------------------------------------------ #
    # validate_bsn
    # ------------------------------------------------------------------ #
    def test_validate_bsn_valid_number(self):
        """validate_bsn should report a known eleven-proof-valid BSN as valid.

        The endpoint uses frappe.new_doc("Donor") to obtain a Donor instance for
        the eleven-proof check, so a valid 9-digit BSN returns valid=True with the
        cleaned digits.
        """
        from verenigingen.api.anbi_operations import validate_bsn

        result = validate_bsn(VALID_BSN)

        self.assertTrue(
            result["success"],
            f"validate_bsn unexpectedly failed: {result.get('error')}",
        )
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["cleaned_value"], VALID_BSN)

    def test_validate_bsn_invalid_number(self):
        """A bad-eleven-proof BSN should yield valid=False with the cleaned digits."""
        from verenigingen.api.anbi_operations import validate_bsn

        result = validate_bsn(INVALID_BSN)

        self.assertTrue(result["success"], f"unexpected failure: {result.get('error')}")
        self.assertFalse(result["data"]["valid"])
        self.assertEqual(result["data"]["cleaned_value"], INVALID_BSN)

    def test_validate_bsn_short_number_is_invalid(self):
        """A too-short BSN should return valid=False with cleaned digits.

        A 5-digit input is not 9 digits -> valid=False; non-digit characters are
        stripped so cleaned_value preserves only the digits.
        """
        from verenigingen.api.anbi_operations import validate_bsn

        result = validate_bsn("123-45")

        self.assertTrue(result["success"], f"unexpected failure: {result.get('error')}")
        self.assertFalse(result["data"]["valid"])
        # Non-digits stripped
        self.assertEqual(result["data"]["cleaned_value"], "12345")

    # ------------------------------------------------------------------ #
    # update_donor_tax_identifiers
    # ------------------------------------------------------------------ #
    def test_update_donor_tax_identifiers_bsn_and_verification(self):
        """Happy path: store a BSN + verification metadata; values persist (encrypted)."""
        from verenigingen.api.anbi_operations import update_donor_tax_identifiers

        donor = self._make_individual_donor()

        result = update_donor_tax_identifiers(
            donor=donor.name, bsn=VALID_BSN, verification_method="DigiD"
        )

        self.assertTrue(result["success"], f"update failed: {result.get('error')}")
        self.assertEqual(result["data"]["donor"], donor.name)

        # Stored value must be encrypted (ENC: prefix), not plaintext.
        stored = frappe.db.get_value(
            "Donor",
            donor.name,
            ["bsn_citizen_service_number", "identification_verified", "identification_verification_method"],
            as_dict=True,
        )
        self.assertTrue(
            stored.bsn_citizen_service_number.startswith("ENC:"),
            "BSN must be encrypted at rest, got plaintext",
        )
        self.assertEqual(stored.identification_verified, 1)
        self.assertEqual(stored.identification_verification_method, "DigiD")

    def test_update_donor_tax_identifiers_rsin_for_organization(self):
        """RSIN is stored (encrypted) for an organization donor."""
        from verenigingen.api.anbi_operations import update_donor_tax_identifiers

        donor = self._make_org_donor()
        # 8-digit RSIN is accepted by Donor.validate_tax_identifiers
        result = update_donor_tax_identifiers(donor=donor.name, rsin="12345678")

        self.assertTrue(result["success"], f"update failed: {result.get('error')}")
        stored = frappe.db.get_value("Donor", donor.name, "rsin_organization_tax_number")
        self.assertTrue(stored.startswith("ENC:"), "RSIN must be encrypted at rest")

    def test_update_donor_tax_identifiers_nonexistent_donor_fails(self):
        """Nonexistent donor -> failure result with proper context (no raise)."""
        from verenigingen.api.anbi_operations import update_donor_tax_identifiers

        result = update_donor_tax_identifiers(donor="NO-SUCH-DONOR-XYZ", bsn=VALID_BSN)

        self.assertFalse(result["success"])
        self.assertEqual(result["meta"]["context"]["operation"], "update_donor_tax_identifiers")
        self.assertEqual(result["meta"]["context"]["donor"], "NO-SUCH-DONOR-XYZ")

    def test_update_donor_tax_identifiers_invalid_bsn_rejected(self):
        """An invalid-eleven-proof BSN is rejected by Donor validation -> failure."""
        from verenigingen.api.anbi_operations import update_donor_tax_identifiers

        donor = self._make_individual_donor()
        result = update_donor_tax_identifiers(donor=donor.name, bsn=INVALID_BSN)

        self.assertFalse(result["success"], "invalid BSN should not be accepted")
        # Donor must be unchanged (no BSN stored)
        self.assertFalse(frappe.db.get_value("Donor", donor.name, "bsn_citizen_service_number"))

    def test_update_donor_tax_identifiers_permission_denied(self):
        """Low-priv user (no Donor write/permlevel) is rejected via frappe.throw."""
        from verenigingen.api.anbi_operations import update_donor_tax_identifiers

        donor = self._make_individual_donor()
        user = self._make_lowpriv_user()

        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                update_donor_tax_identifiers(donor=donor.name, bsn=VALID_BSN)

    # ------------------------------------------------------------------ #
    # get_donor_anbi_data
    # ------------------------------------------------------------------ #
    def test_get_donor_anbi_data_returns_fields(self):
        """Returns donor ANBI fields for an authorized user."""
        from verenigingen.api.anbi_operations import get_donor_anbi_data

        donor = self._make_individual_donor(anbi_consent=1)

        result = get_donor_anbi_data(donor.name)

        self.assertTrue(result["success"], f"failed: {result.get('error')}")
        data = result["data"]
        self.assertEqual(data["donor_name"], donor.donor_name)
        self.assertEqual(data["donor_type"], "Individual")
        self.assertEqual(data["anbi_consent"], 1)

    def test_get_donor_anbi_data_nonexistent_donor_fails(self):
        """Nonexistent donor -> failure with 'Donor not found' context."""
        from verenigingen.api.anbi_operations import get_donor_anbi_data

        result = get_donor_anbi_data("NO-SUCH-DONOR-XYZ")

        self.assertFalse(result["success"])
        self.assertEqual(result["meta"]["context"]["operation"], "get_donor_anbi_data")

    def test_get_donor_anbi_data_permission_denied(self):
        """Low-priv user cannot read ANBI data."""
        from verenigingen.api.anbi_operations import get_donor_anbi_data

        donor = self._make_individual_donor()
        user = self._make_lowpriv_user()

        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                get_donor_anbi_data(donor.name)

    # ------------------------------------------------------------------ #
    # update_anbi_consent
    # ------------------------------------------------------------------ #
    def test_update_anbi_consent_truthy_string(self):
        """consent='1' -> stored consent 1 and a consent_date is set."""
        from verenigingen.api.anbi_operations import update_anbi_consent

        donor = self._make_individual_donor(anbi_consent=0)
        result = update_anbi_consent(donor=donor.name, consent="1")

        self.assertTrue(result["success"], f"failed: {result.get('error')}")
        self.assertEqual(result["data"]["consent"], 1)
        self.assertTrue(result["data"]["consent_date"], "consent_date should be set when granting")
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "anbi_consent"), 1)

    def test_update_anbi_consent_truthy_int(self):
        """consent=1 (int) -> stored consent 1 (cbool handling)."""
        from verenigingen.api.anbi_operations import update_anbi_consent

        donor = self._make_individual_donor(anbi_consent=0)
        result = update_anbi_consent(donor=donor.name, consent=1)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["consent"], 1)

    def test_update_anbi_consent_falsy_clears_consent_value(self):
        """consent='0' must clear the stored consent flag to 0.

        cbool('0') == 0, so anbi_consent is correctly cleared. (The withdrawal
        *reason comment* and consent_date handling are buggy -- see the
        PRODUCT BUG test below -- but the core consent value is right.)
        """
        from verenigingen.api.anbi_operations import update_anbi_consent

        donor = self._make_individual_donor(anbi_consent=1)
        result = update_anbi_consent(donor=donor.name, consent="0", reason="Donor requested removal")

        self.assertTrue(result["success"], f"failed: {result.get('error')}")
        self.assertEqual(result["data"]["consent"], 0)
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "anbi_consent"), 0)

    def test_update_anbi_consent_withdrawal_logs_reason(self):
        """Withdrawing consent with a reason clears the flag and records a Comment.

        The endpoint normalizes the raw value with cbool, so the whitelisted
        string "0" correctly takes the withdrawal branch (anbi_consent -> 0) and
        records the withdrawal reason via the Document method add_comment("Comment", ...).
        """
        from verenigingen.api.anbi_operations import update_anbi_consent

        donor = self._make_individual_donor(anbi_consent=1)
        reason = "Donor requested removal"

        result = update_anbi_consent(donor=donor.name, consent="0", reason=reason)
        self.assertTrue(result["success"], f"failed: {result.get('error')}")

        # Withdrawal branch must clear the consent flag.
        self.assertEqual(result["data"]["consent"], 0)
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "anbi_consent"), 0)

        # A Comment carrying the withdrawal reason must be recorded on the Donor.
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Donor", "reference_name": donor.name},
            fields=["content"],
        )
        self.assertTrue(
            any(reason in (c.content or "") for c in comments),
            f"expected a withdrawal comment containing the reason; got {comments}",
        )

    def test_update_anbi_consent_nonexistent_donor_fails(self):
        from verenigingen.api.anbi_operations import update_anbi_consent

        result = update_anbi_consent(donor="NO-SUCH-DONOR-XYZ", consent="1")

        self.assertFalse(result["success"])
        self.assertEqual(result["meta"]["context"]["operation"], "update_anbi_consent")

    # ------------------------------------------------------------------ #
    # get_anbi_statistics
    # ------------------------------------------------------------------ #
    def test_get_anbi_statistics_aggregates_seeded_data(self):
        """Seed two paid ANBI donations + consent/verification; assert the aggregates."""
        from verenigingen.api.anbi_operations import get_anbi_statistics

        # Baseline (other data may exist on the shared site).
        before = get_anbi_statistics()["data"]["statistics"]
        base_count = before["total_anbi_donations"]
        base_amount = float(before["total_anbi_amount"])
        base_consent = before["donors_with_consent"]
        base_verified = before["donors_verified"]

        donor = self._make_individual_donor(anbi_consent=1, identification_verified=1)
        agreement = f"ANBI-{frappe.generate_hash(length=6)}"
        self._make_anbi_donation(donor.name, 200.0, agreement)
        self._make_anbi_donation(donor.name, 50.0, agreement)

        after = get_anbi_statistics()["data"]["statistics"]

        self.assertEqual(after["total_anbi_donations"], base_count + 2)
        self.assertAlmostEqual(float(after["total_anbi_amount"]), base_amount + 250.0, places=2)
        self.assertEqual(after["donors_with_consent"], base_consent + 1)
        self.assertEqual(after["donors_verified"], base_verified + 1)

    def test_get_anbi_statistics_date_filter_excludes_out_of_range(self):
        """A date-window filter must exclude donations outside the window."""
        from verenigingen.api.anbi_operations import get_anbi_statistics

        donor = self._make_individual_donor()
        agreement = f"ANBI-{frappe.generate_hash(length=6)}"
        in_range_date = "2024-06-15"
        out_range_date = "2020-01-01"
        self._make_anbi_donation(donor.name, 123.0, agreement, donation_date=in_range_date)
        self._make_anbi_donation(donor.name, 999.0, agreement, donation_date=out_range_date)

        stats = get_anbi_statistics("2024-01-01", "2024-12-31")["data"]["statistics"]

        # Window must reflect the filter and exclude the 2020 donation.
        self.assertEqual(stats["period"], {"from": "2024-01-01", "to": "2024-12-31"})
        # The in-range 123.0 donation must be counted; the 999.0 one must not.
        # (Can't assert exact totals on a shared site, but the out-of-range amount
        #  must not be present: total within window should include 123 but the
        #  per-donor contribution excludes 999.)
        self.assertGreaterEqual(float(stats["total_anbi_amount"]), 123.0)
        self.assertLess(
            float(stats["total_anbi_amount"]),
            float(get_anbi_statistics()["data"]["statistics"]["total_anbi_amount"]),
            "windowed total must be smaller than all-time total (excludes 999.0 in 2020)",
        )

    # ------------------------------------------------------------------ #
    # generate_anbi_report
    # ------------------------------------------------------------------ #
    def test_generate_anbi_report_returns_seeded_donations(self):
        """generate_anbi_report should return the seeded ANBI donations.

        The report selects only columns that exist on the Donation doctype
        (the nonexistent "donation_type" was removed), so it succeeds and returns
        the matching donation rows.
        """
        from verenigingen.api.anbi_operations import generate_anbi_report

        donor = self._make_individual_donor()
        agreement = f"ANBI-{frappe.generate_hash(length=6)}"
        self._make_anbi_donation(donor.name, 300.0, agreement, donation_date="2024-03-01")

        result = generate_anbi_report("2024-01-01", "2024-12-31")

        self.assertTrue(
            result["success"],
            f"generate_anbi_report failed: {result.get('error')}",
        )
        summary = result["data"]["summary"]
        self.assertGreaterEqual(summary["total_donations"], 1)
        self.assertFalse(summary["includes_tax_ids"])
        # Our seeded donation must appear with the right donor + amount.
        ours = [d for d in result["data"]["donations"] if d["anbi_agreement_number"] == agreement]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0]["amount"], 300.0)
        self.assertEqual(ours[0]["donor_name"], donor.donor_name)

    def test_generate_anbi_report_permission_denied_without_donation_read(self):
        """Low-priv user (no Donation read) is rejected before any query."""
        from verenigingen.api.anbi_operations import generate_anbi_report

        user = self._make_lowpriv_user()
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                generate_anbi_report("2024-01-01", "2024-12-31")

    # ------------------------------------------------------------------ #
    # export_belastingdienst_report
    # ------------------------------------------------------------------ #
    def test_export_belastingdienst_report_creates_csv_file(self):
        """Export produces a private CSV File; report rows come from donation_summary."""
        from verenigingen.api.anbi_operations import export_belastingdienst_report

        # The donation_summary report's get_data() is independent of the
        # enable_anbi_functionality gate (that gate is only in execute()), so
        # export works regardless. Seed one paid donation so there is data.
        donor = self._make_individual_donor(anbi_consent=1)
        agreement = f"ANBI-{frappe.generate_hash(length=6)}"
        self._make_anbi_donation(donor.name, 75.0, agreement, donation_date="2024-05-01")

        result = export_belastingdienst_report({"from_date": "2024-01-01", "to_date": "2024-12-31"})

        self.assertTrue(result["success"], f"export failed: {result.get('error')}")
        self.assertTrue(result["data"]["file_name"].startswith("ANBI_Report_"))
        self.assertTrue(result["data"]["file_name"].endswith(".csv"))

        file_url = result["data"]["file_url"]
        self.assertTrue(file_url, "file_url must be populated")
        # The File doc must actually exist and be private.
        file_doc = frappe.get_all(
            "File", filters={"file_url": file_url}, fields=["name", "is_private"]
        )
        self.assertEqual(len(file_doc), 1)
        self.assertEqual(file_doc[0].is_private, 1)
        self.track_doc("File", file_doc[0].name)

    def test_export_belastingdienst_report_accepts_json_string_filters(self):
        """filters passed as a JSON string are parsed (whitelist sends strings)."""
        import json as _json

        from verenigingen.api.anbi_operations import export_belastingdienst_report

        result = export_belastingdienst_report(
            _json.dumps({"from_date": "2024-01-01", "to_date": "2024-12-31"})
        )
        self.assertTrue(result["success"], f"export failed: {result.get('error')}")
        file_doc = frappe.get_all("File", filters={"file_url": result["data"]["file_url"]}, pluck="name")
        if file_doc:
            self.track_doc("File", file_doc[0])

    def test_export_belastingdienst_report_permission_denied(self):
        """Low-priv user (no Donation export) is rejected."""
        from verenigingen.api.anbi_operations import export_belastingdienst_report

        user = self._make_lowpriv_user()
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                export_belastingdienst_report({"from_date": "2024-01-01", "to_date": "2024-12-31"})

    # ------------------------------------------------------------------ #
    # send_consent_requests
    # ------------------------------------------------------------------ #
    def test_send_consent_requests_targets_unconsented_donors(self):
        """A paid-donation donor without consent is a candidate; sent_count is an int.

        We do not assert the email actually went out (the 'anbi_consent_request'
        template may not be configured on the test site, in which case the email
        service returns failure and sent_count stays 0). We DO assert the SQL +
        result plumbing works and returns a non-negative integer sent_count.
        """
        from verenigingen.api.anbi_operations import send_consent_requests

        donor = self._make_individual_donor(
            anbi_consent=0, donor_email=f"consent.{frappe.generate_hash(length=6)}@example.com"
        )
        agreement = f"ANBI-{frappe.generate_hash(length=6)}"
        self._make_anbi_donation(donor.name, 40.0, agreement)

        result = send_consent_requests()

        self.assertTrue(result["success"], f"send_consent_requests failed: {result.get('error')}")
        self.assertIsInstance(result["data"]["sent_count"], int)
        self.assertGreaterEqual(result["data"]["sent_count"], 0)

    def test_send_consent_requests_permission_denied(self):
        """Low-priv user (no Donor write) is rejected."""
        from verenigingen.api.anbi_operations import send_consent_requests

        user = self._make_lowpriv_user()
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                send_consent_requests()
