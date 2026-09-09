# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the payment success / return page controller
(``verenigingen/templates/pages/payment_success.py``).

This is the page users land on when returning from an external payment
provider (Mollie, Pay.nl/ING Checkout, Ponto). The most important behaviour
under test is ``validate_payment_document_access`` - the IDOR guard that
prevents arbitrary documents from being read via the public status page.

Everything runs against real ORM documents created via the factory. The only
external boundaries stubbed are the Mollie payment-status gateway (no live
creds on CI) and the Pay.nl status API, both of which are stubbed at the
import seam, never the page's own business logic.
"""

import time
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import payment_success
from verenigingen.templates.pages.payment_success import PONTO_RETURN_TOKEN_PURPOSE
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token


class TestPagePaymentSuccess(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _make_donation(self, **kwargs):
        donation = self.create_test_donation(**kwargs)
        self.track_doc("Donation", donation.name)
        return donation

    # ------------------------------------------------------------------
    # validate_payment_document_access - the IDOR guard
    # ------------------------------------------------------------------

    def test_validate_rejects_doctype_not_in_whitelist(self):
        """A doctype outside ALLOWED_PAYMENT_DOCTYPES is rejected before any DB hit."""
        is_valid, result = payment_success.validate_payment_document_access("User", "Administrator", "tr_x")
        self.assertFalse(is_valid)
        # result is an error message string, not a doc.
        self.assertIsInstance(result, str)

    def test_validate_rejects_missing_document(self):
        """An allowed doctype with a non-existent docname returns 'not found'."""
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", "Donation-DOES-NOT-EXIST-XYZ", None
        )
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_rejects_when_neither_payment_id_nor_token_given(self):
        """A real, allowed document with NEITHER payment_id NOR token is refused (#1055).

        This used to pass (see git history) simply by omitting payment_id --
        exactly what MollieSettings.get_redirect_url() and mollie_checkout.js's
        own return-URL construction did by default, disclosing amount/paid to
        any guest supplying only a guessable doctype/docname pair.
        """
        donation = self._make_donation()
        is_valid, result = payment_success.validate_payment_document_access("Donation", donation.name, None)
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_accepts_a_valid_return_token_with_no_payment_id(self):
        """A valid return token (minted by get_redirect_url) is accepted with no payment_id."""
        donation = self._make_donation()
        token = generate_guest_return_token("payment_success", f"Donation:{donation.name}")
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, None, token
        )
        self.assertTrue(is_valid)
        self.assertEqual(result.name, donation.name)

    def test_validate_rejects_a_wrong_return_token(self):
        """A wrong token with no payment_id is refused, same as no token at all."""
        donation = self._make_donation()
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, None, "0" * 64
        )
        self.assertFalse(is_valid)

    def test_validate_payment_id_mismatch_is_rejected(self):
        """A wrong payment_id for an existing document is rejected (IDOR / reference forgery)."""
        donation = self._make_donation(payment_id="tr_correct_id")
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_WRONG_id"
        )
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_payment_id_match_passes(self):
        """A matching payment_id resolves to the real document."""
        donation = self._make_donation(payment_id="tr_match_me")
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_match_me"
        )
        self.assertTrue(is_valid)
        self.assertEqual(result.name, donation.name)

    def test_validate_payment_id_required_but_doc_has_none(self):
        """If a payment_id is supplied but the doc carries none, access is denied."""
        donation = self._make_donation()  # no payment_id
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_some_id"
        )
        self.assertFalse(is_valid)

    # ------------------------------------------------------------------
    # get_context - Mollie-style doctype/docname/payment_id flow
    # ------------------------------------------------------------------

    def test_get_context_no_params_shows_invalid_reference(self):
        """With no recognised params, the page reports an invalid reference message."""
        frappe.local.form_dict = frappe._dict()
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "unknown")
        self.assertIn("Invalid payment reference", context.payment_message)

    def test_get_context_disallowed_doctype_is_error(self):
        """A disallowed doctype passed via form_dict surfaces an error status, not the doc."""
        frappe.local.form_dict = frappe._dict({"doctype": "User", "docname": "Administrator"})
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "error")
        # No document info leaked.
        self.assertEqual(context.document_info, {})

    def test_get_context_paid_document_reports_completed(self):
        """An already-paid document with a valid return token (no payment_id) reports completed."""
        donation = self._make_donation(paid=1)
        token = generate_guest_return_token("payment_success", f"Donation:{donation.name}")
        frappe.local.form_dict = frappe._dict(
            {"doctype": "Donation", "docname": donation.name, "token": token}
        )
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["docname"], donation.name)
        self.assertTrue(len(context.next_steps) > 0)

    def test_get_context_paid_document_with_no_token_discloses_nothing(self):
        """A guest with only a real, guessable doctype/docname pair -- NO payment_id, NO
        token -- gets refused exactly like an unknown reference (#1055 finding 2), not
        the document's amount/paid status.
        """
        donation = self._make_donation(paid=1, amount=456.78)
        frappe.local.form_dict = frappe._dict({"doctype": "Donation", "docname": donation.name})
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "error")
        self.assertEqual(context.document_info, {})

    def test_get_context_payment_id_non_mollie_reports_unknown(self):
        """A validated payment_id on a non-Mollie document yields the 'unknown' fallback.

        Donations carry no ``payment_method`` field, so check_payment_status takes
        its non-Mollie branch and reports that automatic status checks are not
        possible for this method - the real, reachable behaviour for the allowed
        doctypes on this site.
        """
        donation = self._make_donation(paid=0, payment_id="tr_ctx_check")
        frappe.local.form_dict = frappe._dict(
            {
                "doctype": "Donation",
                "docname": donation.name,
                "payment_id": "tr_ctx_check",
            }
        )
        context = frappe._dict()
        payment_success.get_context(context)

        self.assertEqual(context.payment_status, "unknown")
        self.assertEqual(context.document_info["docname"], donation.name)

    def test_check_payment_status_non_mollie_method(self):
        """check_payment_status returns 'unknown' for a document with no Mollie method."""
        donation = self._make_donation(payment_id="tr_x")
        result = payment_success.check_payment_status(donation, "tr_x")
        self.assertEqual(result["status"], "unknown")

    # ------------------------------------------------------------------
    # Pay.nl / ING Checkout return branch
    # ------------------------------------------------------------------

    def test_ing_checkout_completed_status(self):
        """Status code 100 from Pay.nl maps to 'completed'."""
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": True, "status_code": 100},
        ):
            payment_success.handle_ing_checkout_return(context, "EX-1234")
        self.assertEqual(context.payment_status, "completed")

    def test_ing_checkout_cancelled_status(self):
        """Status code -90 from Pay.nl maps to 'cancelled'."""
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": True, "status_code": -90},
        ):
            payment_success.handle_ing_checkout_return(context, "EX-1234")
        self.assertEqual(context.payment_status, "cancelled")

    def test_ing_checkout_api_failure_is_error(self):
        """A non-success result from the Pay.nl API surfaces as an error status."""
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": False, "message": "boom"},
        ):
            payment_success.handle_ing_checkout_return(context, "EX-1234")
        self.assertEqual(context.payment_status, "error")
        self.assertEqual(context.payment_message, "boom")

    # ------------------------------------------------------------------
    # Ponto Payment Link return branch
    # ------------------------------------------------------------------

    def test_ponto_link_not_found_is_error(self):
        """A non-existent Ponto Payment Link returns an error status."""
        context = frappe._dict()
        payment_success.handle_ponto_payment_link_return(context, "PONTO-LINK-DOES-NOT-EXIST")
        self.assertEqual(context.payment_status, "error")

    _PONTO_IBAN = "NL39RABO0300065264"

    def _make_ponto_link(self, **kwargs):
        data = {
            "doctype": "Ponto Payment Link",
            "amount": kwargs.pop("amount", 25.0),
            "currency": "EUR",
            "description": kwargs.pop("description", "Membership payment"),
            "creditor_name": kwargs.pop("creditor_name", "Test Org"),
            "creditor_iban": self._PONTO_IBAN,
            "payment_type": "One-Time",
            "status": kwargs.pop("status", "Pending Authorization"),
        }
        data.update(kwargs)
        link = frappe.get_doc(data)
        link.insert()
        self.track_doc("Ponto Payment Link", link.name)
        return link

    def test_ponto_link_with_no_token_discloses_nothing(self):
        """A real Ponto Payment Link id with NO token is refused, not disclosed (#1055
        finding 1) -- this branch used to bypass the file's own ownership check
        (validate_payment_document_access) entirely.
        """
        link = self._make_ponto_link(amount=1234.56, creditor_name="Real Creditor")
        context = frappe._dict()
        payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "error")
        self.assertEqual(context.document_info, {})

    def test_ponto_link_with_valid_token_discloses_status(self):
        """The token minted at the one construction site (betaalverzoek_callback.py)
        is accepted and the real status is disclosed."""
        link = self._make_ponto_link(amount=1234.56)
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Executed")
        token = generate_guest_return_token(PONTO_RETURN_TOKEN_PURPOSE, link.name)
        context = frappe._dict()
        payment_success.handle_ponto_payment_link_return(context, link.name, token)
        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["docname"], link.name)

    # ------------------------------------------------------------------
    # get_next_steps - pure helper, all branches
    # ------------------------------------------------------------------

    def test_next_steps_completed_donation_includes_receipt(self):
        steps = payment_success.get_next_steps("completed", "Donation", "X")
        titles = [s["title"] for s in steps]
        self.assertIn("Receipt", titles)

    def test_next_steps_failed_offers_retry(self):
        steps = payment_success.get_next_steps("failed", "Donation", "X")
        actions = [s.get("action") for s in steps]
        self.assertIn("/donate", actions)

    def test_next_steps_pending_no_action_links(self):
        steps = payment_success.get_next_steps("pending", "Donation", "X")
        self.assertTrue(all(s.get("action") is None for s in steps))

    # ------------------------------------------------------------------
    # refresh_payment_status API endpoint
    # ------------------------------------------------------------------

    def test_refresh_status_invalid_reference_returns_failure(self):
        """The public refresh endpoint never leaks doc existence on a bad reference."""
        result = payment_success.refresh_payment_status("User", "Administrator", "tr_x")
        self.assertFalse(result["success"])

    def test_refresh_status_valid_document(self):
        """A valid, payment_id-matched document succeeds via the public endpoint.

        With no Mollie payment_method the status resolves to 'unknown', but the
        endpoint still reports success and never leaks beyond the validated doc.
        """
        donation = self._make_donation(payment_id="tr_refresh", paid=0)
        result = payment_success.refresh_payment_status("Donation", donation.name, "tr_refresh")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["is_paid"], 0)

    def test_refresh_status_payment_id_mismatch_rejected(self):
        """A wrong payment_id is rejected even for a real allowed document."""
        donation = self._make_donation(payment_id="tr_real")
        result = payment_success.refresh_payment_status("Donation", donation.name, "tr_forged")
        self.assertFalse(result["success"])

    def test_refresh_status_empty_payment_id_no_longer_bypasses_ownership(self):
        """An empty-string payment_id (the page's own default when the URL carries no
        payment_id) is refused, not treated as "no check requested" (#1055 finding 2).
        """
        donation = self._make_donation(paid=1, amount=456.78)
        result = payment_success.refresh_payment_status("Donation", donation.name, "")
        self.assertFalse(result["success"])

    def test_refresh_status_accepts_a_valid_return_token(self):
        """A valid return token (forwarded from the rendered page's form_dict) works
        with no payment_id."""
        donation = self._make_donation(paid=0)
        token = generate_guest_return_token("payment_success", f"Donation:{donation.name}")
        result = payment_success.refresh_payment_status("Donation", donation.name, "", token)
        self.assertTrue(result["success"])

    # ------------------------------------------------------------------
    # Existence-timing oracle (#1105)
    #
    # validate_payment_document_access refuses with a deliberately uniform
    # message (#1055), but used to check existence FIRST and only prove
    # ownership after a full frappe.get_doc(). So the *cost* of a refusal
    # revealed what the *message* was written to hide, over doctypes whose
    # autoname is a sequential naming_series (#1018). Measured before the
    # fix: 10.4x median wall-clock for Donation, 28.4x for Sales Invoice.
    #
    # These assert the invariant by the work a refusal does rather than by
    # wall-clock alone, because a tight latency assertion is inherently flaky
    # while "what did this path touch" is exact.
    #
    # Equal COUNTS are deliberately not the whole assertion. An accidental tie
    # is easy: mutating the fixed code to load the document before refusing
    # gives SELECT+INSERT(Error Log) for a missing docname against
    # SELECT+child-SELECT for an existing one -- 2 == 2, and an INSERT costs
    # far more than a SELECT. So each test pins the exact number of reads the
    # invariant permits, and rejects any write on a path a guest can trigger
    # at will.
    #
    # SCOPE, and why there are three layers rather than one. A review of this
    # file's first version demonstrated the limit of counting SQL: re-adding
    # the removed mismatch audit log, still conditioned on the document
    # existing, but routed through frappe.cache() instead of frappe.log_error,
    # reintroduced a measured 1.50x existence-dependent gap with every
    # SQL-based assertion still green. Counting one channel proves nothing
    # about the others, so:
    #
    #   1. SQL capture (_count_queries)     -- exact, but SQL only.
    #   2. Cache-call capture (_count_cache_calls) -- closes the channel that
    #      review actually defeated this file with.
    #   3. Coarse timing parity (_assert_refusal_latency_parity) -- channel
    #      agnostic, since it measures the observable itself, but only
    #      sensitive at the magnitude of the original defect (10.4x-28.4x).
    #
    # Layer 3's threshold is deliberately loose and CANNOT distinguish the
    # ~1.2x residual this fix accepts from a ~1.5x re-added side effect. That
    # is a real gap: a future side channel through a fourth mechanism, at
    # small magnitude, would pass all three. Do not read a green run here as
    # proof of constant-time behaviour -- it is proof of no SQL divergence, no
    # cache divergence, and no order-of-magnitude latency divergence.
    # ------------------------------------------------------------------

    def _count_queries(self, fn):
        """Return the SQL issued by fn(), via frappe's own instrumentation seam."""
        queries = []
        orig_sql = frappe.db.__class__.sql

        def _counting_sql(*args, **kwargs):
            result = orig_sql(*args, **kwargs)
            queries.append(str(args[0].last_query))
            return result

        try:
            frappe.db.__class__.sql = _counting_sql
            fn()
        finally:
            frappe.db.__class__.sql = orig_sql
        return queries

    def _count_cache_calls(self, fn):
        """Return the names of every frappe.cache() method fn() invokes.

        frappe.cache() is a function returning the Redis wrapper, so replacing
        it with one that hands back a recording proxy captures any call made
        through it without needing to know which methods a side channel picks.
        """
        calls = []
        real_cache = frappe.cache

        class _RecordingCache:
            def __init__(self, wrapped):
                self._wrapped = wrapped

            def __getattr__(self, name):
                attr = getattr(self._wrapped, name)
                if not callable(attr):
                    return attr

                def _recording(*args, **kwargs):
                    calls.append(name)
                    return attr(*args, **kwargs)

                return _recording

        try:
            frappe.cache = lambda: _RecordingCache(real_cache())
            fn()
        finally:
            frappe.cache = real_cache
        return calls

    def _assert_refusal_latency_parity(self, label, call_existing, call_missing, max_ratio=3.0):
        """A refusal must not take an order of magnitude longer for a docname
        that exists, through ANY channel.

        Compares minimums, not medians: noise can only ADD time, so the
        smallest observed run is the robust estimate of true cost and this
        does not turn flaky on a loaded runner. The threshold is loose on
        purpose -- see the SCOPE note above for what this cannot catch.
        """
        for _ in range(20):
            call_existing()
            call_missing()

        def fastest(fn, n=200):
            best = None
            for _ in range(n):
                start = time.perf_counter()
                fn()
                elapsed = time.perf_counter() - start
                best = elapsed if best is None else min(best, elapsed)
            return best

        missing = fastest(call_missing)
        existing = fastest(call_existing)
        ratio = existing / missing if missing else float("inf")
        self.assertLess(
            ratio,
            max_ratio,
            f"{label}: refusing an existing docname was {ratio:.2f}x the cost of refusing a "
            f"non-existent one ({existing * 1000:.4f}ms vs {missing * 1000:.4f}ms). A refusal "
            f"whose cost tracks existence is an oracle behind a uniform message (#1105).",
        )

    def _assert_refusal_reads_the_same_either_way(self, label, call_existing, call_missing, permitted):
        """A refusal must issue exactly `permitted` queries, all reads, whether
        or not the docname exists.

        Warms caches first: frappe resolves doctype meta and table columns
        lazily through Redis, so a cold cache inside the measured block
        counts as a difference that has nothing to do with the code under
        test.
        """
        for _ in range(3):
            call_existing()
            call_missing()

        for which, queries in (
            ("existing docname", self._count_queries(call_existing)),
            ("nonexistent docname", self._count_queries(call_missing)),
        ):
            self.assertEqual(
                len(queries),
                permitted,
                f"{label}: refusing a {which} issued {len(queries)} queries, "
                f"not the {permitted} the invariant permits. A refusal whose cost "
                f"depends on the document is an existence oracle behind a uniform "
                f"error message (#1105).\n  " + "\n  ".join(queries),
            )
            writes = [q for q in queries if not q.lstrip().upper().startswith("SELECT")]
            self.assertEqual(
                writes,
                [],
                f"{label}: refusing a {which} performed a WRITE. A guest can trigger "
                f"this path at will, so it must not grow tabError Log (MyISAM, "
                f"non-transactional) nor cost an INSERT (#1105).\n  " + "\n  ".join(writes),
            )

        # Layer 2: the same comparison for the cache, which layer 1 cannot see.
        self.assertEqual(
            self._count_cache_calls(call_existing),
            self._count_cache_calls(call_missing),
            f"{label}: the refusal made different frappe.cache() calls depending on "
            f"whether the document exists. Counting SQL alone does not see this -- it is "
            f"how a review defeated an earlier version of these tests (#1105).",
        )

        # Layer 3: the observable itself, for any channel neither above covers.
        self._assert_refusal_latency_parity(label, call_existing, call_missing)

    def test_validate_refusal_without_credentials_reads_nothing(self):
        """No payment_id and a wrong token must refuse without reading the document.

        Nothing supplied could prove ownership, so no read is needed to decide --
        and a refusal that reads nothing cannot cost more for a docname that
        happens to exist. This is the shape #1105 measured at 10.4x/28.4x.
        """
        donation = self._make_donation()
        bad_token = "0" * 64
        missing = "Assoc-Dnt-2026-99999-nonexistent"

        # Control: both calls must actually refuse, and refuse identically.
        # Otherwise this compares a success path against a failure path.
        ok_existing, msg_existing = payment_success.validate_payment_document_access(
            "Donation", donation.name, None, bad_token
        )
        ok_missing, msg_missing = payment_success.validate_payment_document_access(
            "Donation", missing, None, bad_token
        )
        self.assertFalse(ok_existing)
        self.assertFalse(ok_missing)
        self.assertEqual(msg_existing, msg_missing)

        self._assert_refusal_reads_the_same_either_way(
            "validate_payment_document_access (no credentials)",
            lambda: payment_success.validate_payment_document_access(
                "Donation", donation.name, None, bad_token
            ),
            lambda: payment_success.validate_payment_document_access("Donation", missing, None, bad_token),
            permitted=0,
        )

    def test_validate_refusal_with_wrong_payment_id_reads_one_row(self):
        """A garbage payment_id forces the one branch that must read, and it must
        read exactly one row -- the same query whether or not that row exists.

        Supplying a garbage payment_id is how a caller reaches the reading
        branch at all, so the invariant has to hold here too, not just on the
        no-credentials path above.
        """
        donation = self._make_donation(payment_id="tr_real")
        bad_token = "0" * 64
        missing = "Assoc-Dnt-2026-99999-nonexistent"

        ok_existing, _msg = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_garbage", bad_token
        )
        self.assertFalse(ok_existing)

        self._assert_refusal_reads_the_same_either_way(
            "validate_payment_document_access (wrong payment_id)",
            lambda: payment_success.validate_payment_document_access(
                "Donation", donation.name, "tr_garbage", bad_token
            ),
            lambda: payment_success.validate_payment_document_access(
                "Donation", missing, "tr_garbage", bad_token
            ),
            permitted=1,
        )

    def test_ponto_return_refusal_cost_does_not_reveal_existence(self):
        """A wrong token must refuse at the same read cost whether or not the
        payment link exists.

        This one is a regression guard, not a fix: measured on the unmodified
        code, handle_ponto_payment_link_return is already symmetric at the
        database level (one exists() either way), and the extra work an
        existing link costs is a single HMAC -- ~0.003ms against a ~0.35ms
        query, under 1%. It is kept so a future reordering that moves a read
        ahead of the token check cannot land unnoticed (#1105).
        """
        link = self._make_ponto_link()
        bad_token = "0" * 64
        missing = "PONTO-LINK-9999-nonexistent"

        def call(name):
            context = frappe._dict()
            payment_success.handle_ponto_payment_link_return(context, name, bad_token)
            # Control: both must refuse and disclose nothing.
            self.assertEqual(context.payment_status, "error")
            self.assertEqual(context.document_info, {})

        self._assert_refusal_reads_the_same_either_way(
            "handle_ponto_payment_link_return",
            lambda: call(link.name),
            lambda: call(missing),
            permitted=1,
        )
