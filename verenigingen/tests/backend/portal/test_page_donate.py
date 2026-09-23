"""
Coverage-extension tests for the public donation page
(verenigingen.templates.pages.donate).

The guest/authenticated submit + payment-method save paths are covered by
test_guest_donation_flow.py. This module covers the OTHER surface: get_context
assembly (anonymous, logged-in donor pre-fill, donation_id return paths),
map_donation_status mapping, get_donation_status, mark_donation_paid permission
guard + happy path, and retry_payment validation guards.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageDonate(EnhancedTestCase):
    """Real-data tests for donate.py context + status helpers."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        self._original_user = frappe.session.user

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    def _make_donation(self, *, paid=0, mode="Bank Transfer", amount=20.0, status="One-time"):
        donor = self.create_test_donor(donor_email=f"donate-{frappe.generate_hash()[:8]}@example.com")
        doc = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": today(),
                "amount": amount,
                "mode_of_payment": mode,
                "status": status,
                "donation_purpose_type": "General",
                "paid": paid,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    # ----- map_donation_status (pure) ----------------------------------

    def test_map_donation_status(self):
        from verenigingen.services.donation.public_donation_service import (
            get_public_donation_service,
        )

        svc = get_public_donation_service()
        self.assertEqual(svc.map_donation_status("One-time donation"), "One-time")
        self.assertEqual(svc.map_donation_status("Monthly recurring"), "Recurring")
        self.assertEqual(svc.map_donation_status("Promised donation"), "Promised")
        self.assertEqual(svc.map_donation_status("Recurring"), "Recurring")
        # Unknown values fall back to One-time.
        self.assertEqual(svc.map_donation_status("garbage value"), "One-time")

    # ----- get_context --------------------------------------------------

    def test_context_anonymous_basic(self):
        from verenigingen.templates.pages.donate import get_context

        frappe.form_dict = frappe._dict()
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.no_cache, 1)
        self.assertIn("company_name", ctx.settings)
        self.assertIsInstance(ctx.payment_methods, list)
        self.assertIsInstance(ctx.chapters, list)
        self.assertIsInstance(ctx.donor_types, list)
        # Anonymous: no user_info populated.
        self.assertEqual(ctx.user_info, {})

    def test_context_logged_in_prefills_existing_donor(self):
        from verenigingen.templates.pages.donate import get_context

        email = f"donateuser-{frappe.generate_hash()[:8]}@example.com"
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Donate",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        # Existing donor matching the user email -> prefilled context.
        self.create_test_donor(donor_name="Donate User", donor_email=email)

        frappe.form_dict = frappe._dict()
        with self.as_user(email):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.user_info["email"], email)
        self.assertIn("existing_donor", ctx)
        self.assertEqual(ctx.existing_donor["donor_email"], email)

    def test_context_with_paid_donation_id_shows_success(self):
        from verenigingen.services.donation.public_donation_service import (
            generate_donation_return_token,
        )
        from verenigingen.templates.pages.donate import get_context

        donation = self._make_donation(paid=1, mode="Bank Transfer")
        token = generate_donation_return_token(donation.name)
        frappe.form_dict = frappe._dict({"donation_id": donation.name, "token": token})
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.payment_status, "success")
        self.assertEqual(ctx.donation_result.name, donation.name)

    def test_context_with_unpaid_no_payment_id_pending(self):
        from verenigingen.services.donation.public_donation_service import (
            generate_donation_return_token,
        )
        from verenigingen.templates.pages.donate import get_context

        donation = self._make_donation(paid=0, mode="Bank Transfer")
        token = generate_donation_return_token(donation.name)
        frappe.form_dict = frappe._dict({"donation_id": donation.name, "token": token})
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.payment_status, "pending")

    def test_context_with_unknown_donation_id_error(self):
        from verenigingen.templates.pages.donate import get_context

        frappe.form_dict = frappe._dict({"donation_id": "Nonexistent-Donation-XYZ"})
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.payment_status, "error")

    # ----- get_context donation_id ownership (#1018) --------------------
    #
    # donate.py's return-from-payment path renders a Donation's amount, date
    # and purpose straight from `frappe.get_doc("Donation", donation_id)`,
    # with no check that the requesting browser is the one that actually
    # made this donation. Donation.autoname is naming_series: (sequential),
    # so a stranger's donation_id is enumerable. The fix requires a `token`
    # query param -- an HMAC over the donation name, generated only when we
    # build the Mollie return_url -- and treats a missing/wrong token
    # identically to an unknown donation_id (same payment_status, no
    # donation_result key at all), so refusal carries no oracle.

    def test_context_with_strangers_donation_id_and_no_token_discloses_nothing(self):
        """A guest who only knows another donor's donation_id must get nothing."""
        from verenigingen.templates.pages.donate import get_context

        donation = self._make_donation(paid=1, mode="Bank Transfer", amount=987.65)
        frappe.form_dict = frappe._dict({"donation_id": donation.name})
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.payment_status, "error")
        self.assertNotIn("donation_result", ctx)

    def test_context_with_strangers_donation_id_and_wrong_token_discloses_nothing(self):
        """A forged/guessed token must be refused exactly like no token at all."""
        from verenigingen.templates.pages.donate import get_context

        donation = self._make_donation(paid=1, mode="Bank Transfer", amount=987.65)
        frappe.form_dict = frappe._dict({"donation_id": donation.name, "token": "0" * 64})
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.payment_status, "error")
        self.assertNotIn("donation_result", ctx)

    # ----- non-ASCII token (#1108) --------------------------------------
    #
    # hmac.compare_digest raises TypeError on a non-ASCII str, and this
    # helper's own "fails closed" docstring only covered the missing/empty
    # case. donate.py's try/except around frappe.get_doc catches only
    # frappe.DoesNotExistError, so the TypeError escaped get_context as an
    # unhandled 500 instead of the ordinary refusal. Same defect #1103's
    # 4339c1b13 fixed in the sibling guest_return_tokens helper.

    def test_context_with_non_ascii_token_discloses_nothing_not_raises(self):
        """A non-ASCII token must be REFUSED, exactly like any other bad token --
        not raise a TypeError out of get_context."""
        from verenigingen.templates.pages.donate import get_context

        donation = self._make_donation(paid=1, mode="Bank Transfer", amount=987.65)
        frappe.form_dict = frappe._dict({"donation_id": donation.name, "token": "héllo"})
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        # Same refusal shape as the wrong-but-ASCII-token control above: same
        # payment_status, no donation_result key at all.
        self.assertEqual(ctx.payment_status, "error")
        self.assertNotIn("donation_result", ctx)

    def test_verify_donation_return_token_refuses_non_ascii_at_the_helper(self):
        """The helper itself fails closed, so every caller is covered by
        construction, not just the one wrapped in a try/except."""
        from verenigingen.services.donation.public_donation_service import (
            verify_donation_return_token,
        )

        donation = self._make_donation(paid=1, mode="Bank Transfer")
        self.assertFalse(verify_donation_return_token(donation.name, "héllo"))

    def test_verify_donation_return_token_refuses_empty_token(self):
        from verenigingen.services.donation.public_donation_service import (
            verify_donation_return_token,
        )

        donation = self._make_donation(paid=1, mode="Bank Transfer")
        self.assertFalse(verify_donation_return_token(donation.name, ""))

    def test_verify_donation_return_token_refuses_none_token(self):
        from verenigingen.services.donation.public_donation_service import (
            verify_donation_return_token,
        )

        donation = self._make_donation(paid=1, mode="Bank Transfer")
        self.assertFalse(verify_donation_return_token(donation.name, None))

    def test_verify_donation_return_token_refuses_wrong_ascii_token(self):
        """Control: an ordinary wrong-but-ASCII token is refused, not an error."""
        from verenigingen.services.donation.public_donation_service import (
            verify_donation_return_token,
        )

        donation = self._make_donation(paid=1, mode="Bank Transfer")
        self.assertFalse(verify_donation_return_token(donation.name, "0" * 64))

    def test_verify_donation_return_token_accepts_correct_token(self):
        """Control: the happy path -- a correctly generated token -- still works."""
        from verenigingen.services.donation.public_donation_service import (
            generate_donation_return_token,
            verify_donation_return_token,
        )

        donation = self._make_donation(paid=1, mode="Bank Transfer")
        token = generate_donation_return_token(donation.name)
        self.assertTrue(verify_donation_return_token(donation.name, token))

    # ----- get_donation_status -----------------------------------------

    def test_get_donation_status_paid(self):
        from verenigingen.templates.pages.donate import get_donation_status

        donation = self._make_donation(paid=1, amount=42.0)
        result = get_donation_status(donation.name)
        self.assertEqual(result["status"], "Paid")
        self.assertEqual(result["amount"], 42.0)
        self.assertEqual(str(result["date"]), today())

    def test_get_donation_status_pending(self):
        from verenigingen.templates.pages.donate import get_donation_status

        donation = self._make_donation(paid=0)
        result = get_donation_status(donation.name)
        self.assertEqual(result["status"], "Pending")

    def test_get_donation_status_missing_id(self):
        from verenigingen.templates.pages.donate import get_donation_status

        self.assertEqual(get_donation_status(None), {"error": "Donation ID required"})

    def test_get_donation_status_is_not_guest_reachable(self):
        """Control: unlike retry_payment/get_context, this endpoint has no
        allow_guest=True, so frappe's own dispatch gate already refuses a
        Guest session before the function body runs (#1092's boundary, not
        the escalation it reports). Checked at the whitelist-registry layer
        per CLAUDE.md ("whitelisting gates DISPATCH, not calls") -- frappe's
        is_whitelisted() raises PermissionError rather than returning a bool."""
        from verenigingen.templates.pages.donate import get_donation_status

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                frappe.is_whitelisted(get_donation_status)

    def test_get_donation_status_denies_unauthorized_authenticated_user(self):
        """#1092: get_donation_status_data called frappe.get_doc directly, which
        performs no permission check, so any authenticated user who cleared
        the endpoint's HIGH security-level gate could read ANY donation's
        amount/status/purpose -- roles that are not in Donation's own DocPerm
        read list (System Manager, Verenigingen Administrator, Verenigingen
        Webhook User; see tests/security/test_permission_registry_consistency
        .py's DONATION_READ_ROLES). "Verenigingen Chapter Board Member" is one
        of the roles #965 measured as clearing HIGH (via its Role Profile,
        api_security_framework.py's Rule 4) while sitting outside
        DONATION_READ_ROLES -- exactly the escalation this issue reports --
        and this user is not linked to this donation's donor either, so it
        must be refused."""
        from verenigingen.templates.pages.donate import get_donation_status

        donation = self._make_donation(paid=1, amount=42.0)

        with self.as_role("Verenigingen Chapter Board Member"):
            result = get_donation_status(donation.name)

        self.assertEqual(result, {"error": "Insufficient permissions"})

    def test_get_donation_status_allows_permitted_user(self):
        """Positive control: a user who DOES hold Donation read access (per
        DONATION_READ_ROLES) still gets real data back -- the fix must not
        also break the legitimate admin/webhook path."""
        from verenigingen.templates.pages.donate import get_donation_status

        donation = self._make_donation(paid=1, amount=42.0)
        admin = self.ensure_test_admin_user()

        with self.as_user(admin.email):
            result = get_donation_status(donation.name)

        self.assertEqual(result["status"], "Paid")
        self.assertEqual(result["amount"], 42.0)

    def _call_get_donation_status(self, donation_id):
        """Normalise get_donation_status's result whether it returns a dict or
        raises -- #1284's bug is that these two cases look different depending
        on whether the caller-supplied id exists, which is exactly what this
        helper must not silently paper over."""
        from verenigingen.templates.pages.donate import get_donation_status

        try:
            return {"result": get_donation_status(donation_id)}
        except Exception as e:
            return {"exception": type(e).__name__}

    def test_get_donation_status_unauthorized_user_cannot_distinguish_unknown_from_forbidden(self):
        """#1284: get_donation_status_data called frappe.get_doc(donation_id) BEFORE
        the #1092 permission guard, so an unknown id raised frappe.DoesNotExistError
        while an existing-but-forbidden id returned {"error": "Insufficient
        permissions"} -- two distinguishable outcomes an unauthorized caller could
        use as an existence oracle over Donation names. A caller without Donation
        read permission must get the IDENTICAL response for both."""
        donation = self._make_donation(paid=1, amount=42.0)

        with self.as_role("Verenigingen Chapter Board Member"):
            forbidden = self._call_get_donation_status(donation.name)
            unknown = self._call_get_donation_status("NONEXISTENT-DONATION-XYZ-123")

        self.assertEqual(forbidden, unknown)
        self.assertEqual(forbidden, {"result": {"error": "Insufficient permissions"}})

    def test_get_donation_status_permitted_user_gets_clear_not_found(self):
        """Positive control for #1284's fix: a caller who DOES hold Donation read
        access must still get a distinct, clear "not found" for a genuinely
        missing id -- the fix must not turn every unknown id into a blanket
        "Insufficient permissions" for legitimate readers too."""
        from verenigingen.templates.pages.donate import get_donation_status

        admin = self.ensure_test_admin_user()

        with self.as_user(admin.email):
            result = get_donation_status("NONEXISTENT-DONATION-XYZ-123")

        self.assertNotEqual(result, {"error": "Insufficient permissions"})
        self.assertIn("error", result)
        self.assertIn("not found", result["error"].lower())

    def test_get_donation_status_share_recipient_cannot_distinguish_unknown_from_unrelated(self):
        """Round-2 review of #1284's fix: frappe.has_permission("Donation", "read")
        with no `doc` falls through to false_if_not_shared() (frappe/permissions.py),
        whose no-doc branch returns True if the caller has ANY Donation shared with
        them for read -- not specifically the requested donation_id. Donation grants
        share:1 to System Manager / Verenigingen Administrator (donation.json), so an
        admin can share exactly one donation with an otherwise-unprivileged board
        user, and that user's doctype-level check then passes for every donation_id,
        reopening the existence oracle the first round of the fix closed: an
        unrelated EXISTING id reaches frappe.db.exists (True) then fails the
        doc-level check ("Insufficient permissions"), while an UNKNOWN id fails
        db.exists first ("Donation not found") -- distinguishable again.

        A share recipient must get the SAME refusal for "unrelated existing" and
        "unknown" as anyone else without genuine role-level access, while still
        being able to read the donation actually shared with them (positive
        control)."""
        shared_donation = self._make_donation(paid=1, amount=42.0)
        unrelated_donation = self._make_donation(paid=1, amount=99.0)

        email = "scratch.donation-share-recipient-1284@test.invalid"

        # as_role() creates/configures the scratch user as a side effect of the
        # call itself (before the `with` even starts) and returns the as_user()
        # context manager -- so the user exists here, before it is entered, and
        # a share can be granted to it first.
        board_member_session = self.as_role("Verenigingen Chapter Board Member", email=email)

        with self.as_user("Administrator"):
            frappe.share.add("Donation", shared_donation.name, user=email, read=1)

        with board_member_session:
            from verenigingen.templates.pages.donate import get_donation_status

            shared_result = get_donation_status(shared_donation.name)
            unrelated_result = self._call_get_donation_status(unrelated_donation.name)
            unknown_result = self._call_get_donation_status("NONEXISTENT-DONATION-XYZ-999")

        # Positive control: the share itself must still work.
        self.assertEqual(shared_result["status"], "Paid")
        self.assertEqual(shared_result["amount"], 42.0)

        # The oracle: an unrelated existing id and an unknown id must be identical.
        self.assertEqual(unrelated_result, unknown_result)

    # ----- mark_donation_paid ------------------------------------------

    def test_mark_donation_paid_happy_path(self):
        from verenigingen.templates.pages.donate import mark_donation_paid

        donation = self._make_donation(paid=0)
        admin = self.ensure_test_admin_user()
        with self.as_user(admin.email):
            result = mark_donation_paid(donation.name, payment_reference="REF-123")

        self.assertTrue(result.get("success"))
        donation.reload()
        self.assertEqual(donation.paid, 1)
        self.assertEqual(donation.payment_id, "REF-123")

    # ----- retry_payment guards ----------------------------------------

    def test_retry_payment_missing_id(self):
        from verenigingen.templates.pages.donate import retry_payment

        with self.assertRaises(frappe.ValidationError):
            retry_payment(None)

    def test_retry_payment_already_paid(self):
        from verenigingen.templates.pages.donate import retry_payment

        donation = self._make_donation(paid=1, mode="Mollie")
        donor_email = frappe.db.get_value("Donor", donation.donor, "donor_email")
        # The endpoint wraps the "already paid" throw into a generic error.
        with self.assertRaises(frappe.ValidationError):
            retry_payment(donation.name, donor_email=donor_email)

    def test_retry_payment_non_mollie(self):
        from verenigingen.templates.pages.donate import retry_payment

        donation = self._make_donation(paid=0, mode="Bank Transfer")
        donor_email = frappe.db.get_value("Donor", donation.donor, "donor_email")
        with self.assertRaises(frappe.ValidationError):
            retry_payment(donation.name, donor_email=donor_email)

    # ----- retry_payment ownership (#969) -------------------------------
    #
    # retry_payment is deliberately guest-reachable: a donor whose Mollie
    # payment failed has no session to authenticate with. With no session,
    # donor_email is the only ownership signal the endpoint can check --
    # see PublicDonationService._verify_donor_email_matches.
    #
    # All three tests below stub the Mollie boundary so that, absent the
    # ownership check, the call would SUCCEED and return a real-looking
    # payment URL. This proves a refusal is the ownership check firing, not
    # an unrelated failure (e.g. missing Mollie credentials) that would
    # happen to raise the same exception type for the wrong reason.

    class _FakeCompletePaymentService:
        def __init__(self, client=None):
            pass

        def create_donation_payment(self, donation_doc, form_data):
            return {
                "status": "redirect_required",
                "payment_url": "https://pay.mollie.test/checkout/retry",
                "checkout_url": "https://pay.mollie.test/checkout/retry",
            }

    _CPS_PATH = (
        "verenigingen.verenigingen_payments.mollie.services."
        "complete_payment_service.CompletePaymentService"
    )

    def test_retry_payment_refuses_stranger_with_no_donor_email(self):
        """A guest supplying only the (enumerable) donation_id is refused."""
        from unittest.mock import patch

        from verenigingen.templates.pages.donate import retry_payment

        donation = self._make_donation(paid=0, mode="Mollie")
        with self.as_user("Guest"):
            with patch(self._CPS_PATH, self._FakeCompletePaymentService):
                with self.assertRaises(frappe.ValidationError):
                    retry_payment(donation.name)

    def test_retry_payment_refuses_stranger_with_wrong_donor_email(self):
        """A guest supplying an unrelated email is refused, same as no email at all."""
        from unittest.mock import patch

        from verenigingen.templates.pages.donate import retry_payment

        donation = self._make_donation(paid=0, mode="Mollie")
        with self.as_user("Guest"):
            with patch(self._CPS_PATH, self._FakeCompletePaymentService):
                with self.assertRaises(frappe.ValidationError):
                    retry_payment(donation.name, donor_email="stranger@example.com")

    def test_retry_payment_allows_guest_with_correct_donor_email(self):
        """The real donor -- identified only by their own email, no session -- may retry."""
        from unittest.mock import patch

        from verenigingen.templates.pages.donate import retry_payment

        donation = self._make_donation(paid=0, mode="Mollie")
        donor_email = frappe.db.get_value("Donor", donation.donor, "donor_email")

        with self.as_user("Guest"):
            with patch(self._CPS_PATH, self._FakeCompletePaymentService):
                frappe.local.response = frappe._dict()
                retry_payment(donation.name, donor_email=donor_email)

        self.assertEqual(
            frappe.local.response.get("location"), "https://pay.mollie.test/checkout/retry"
        )
