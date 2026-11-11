"""
#1817: Ponto ``payment_page`` (guest GET) must not serve a link by its sequential name.

Driven through the REAL WSGI app as Guest (``werkzeug.test.Client(frappe.app.application)``),
in a SUBPROCESS that owns and deletes every row it commits (same approach and reasons as
test_ponto_callback_wsgi). The page only reads, so the rollback-on-GET trap (README rule 21)
does not hide anything here; the WSGI route is used because the guest path (rate limiter,
``public_api``, error serialisation, ``_server_messages``) is what an attacker sees.

Every refusal is compared with the UNKNOWN-name answer on every channel an anonymous caller
can read: HTTP status, body (``exc_type`` and ``_server_messages`` with the per-request
``__frappe_exc_id`` removed), response headers other than rate-limit counters, and the Error
Log row count. Query count is not measured over WSGI; the refusal for a missing/wrong token
happens before any database read by construction (see the endpoint docstring).

Usage:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_payment_page_wsgi
"""

import json
import os
import re
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SCRIPT = textwrap.dedent(
    """
    import itertools, json, re, uuid
    import frappe

    SITE = {site!r}
    frappe.init(site=SITE)
    frappe.connect()

    from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
    from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token as gen
    from verenigingen.verenigingen_payments.ponto.api import betaalverzoek_callback as cb

    created = []
    out = {{}}
    TABLES = ("Ponto Payment Link", "Version", "Comment", "Deleted Document")
    out["leak_before"] = {{t: frappe.db.count(t) for t in TABLES}}

    def make_link(status, description):
        d = frappe.new_doc("Ponto Payment Link")
        d.payment_type = "One-Time"
        d.amount = 25
        d.currency = "EUR"
        d.description = description
        d.creditor_name = "Org"
        d.creditor_iban = TestIBAN.ABN_AMRO_1
        d.status = status
        d.ponto_request_id = "wsgi-1817"
        d.redirect_link = "https://example.test/sign/wsgi-1817"
        d.insert()
        created.append(d.name)
        return d.name

    try:
        frappe.set_user("Administrator")
        pending = make_link("Pending Authorization", "WSGI-1817-PENDING-DESC")
        other = make_link("Pending Authorization", "WSGI-1817-OTHER")
        executed = make_link("Executed", "WSGI-1817-EXECUTED")
        cancelled = make_link("Cancelled", "WSGI-1817-CANCELLED")
        deleted = make_link("Pending Authorization", "WSGI-1817-DELETED")
        deleted_token = gen(cb.PAYMENT_PAGE_TOKEN_PURPOSE, deleted)
        frappe.db.delete("Ponto Payment Link", {{"name": deleted}})  # raw: delete_doc leaves audit rows
        created.remove(deleted)
        frappe.db.commit()

        # minted BEFORE frappe.destroy(): the signing key lives in frappe.local.conf
        tokens = {{n: gen(cb.PAYMENT_PAGE_TOKEN_PURPOSE, n) for n in (pending, other, executed, cancelled)}}
        tok = tokens.__getitem__
        out["names"] = {{"pending": pending, "other": other, "executed": executed}}
        out["tokens"] = tokens
        # the proofs the SAME link legitimately carries elsewhere: none may unlock this page
        foreign = {{
            "cancel": gen(cb.CANCEL_TOKEN_PURPOSE, pending),
            "return_proof": gen(cb.RETURN_PROOF_PURPOSE, pending),
            "success": gen(cb.PONTO_RETURN_TOKEN_PURPOSE, pending),
            "ponto_pay": gen("ponto_pay", pending),
        }}
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client

        client = Client(frappe.app.application, use_cookies=False)  # a cookie jar makes later requests differ
        headers = {{"X-Frappe-Site-Name": SITE}}
        PAGE = "/api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_page"
        seq = itertools.count(1)
        base = uuid.uuid4().int

        def error_logs():
            frappe.init(site=SITE)
            frappe.connect()
            try:
                return frappe.db.count("Error Log")
            finally:
                frappe.destroy()

        def get(query):
            n = base + next(seq)
            addr = f"10.{{(n >> 16) % 250 + 1}}.{{(n >> 8) % 250 + 1}}.{{n % 250 + 1}}"
            before = error_logs()
            r = client.get(PAGE + query, headers=headers, environ_base={{"REMOTE_ADDR": addr}})
            body = r.get_data(as_text=True)
            data = json.loads(body)
            for key in ("_server_messages", "exception"):
                if isinstance(data.get(key), str):
                    data[key] = re.sub(r'__frappe_exc_id[^,}}]*', "", data[key])
            data.pop("exc", None)
            hdrs = {{k: v for k, v in r.headers.items() if not k.lower().startswith(("x-ratelimit", "date", "content-length"))}}
            data.pop("headers", None)
            return {{
                "status": r.status_code,
                "body": data,
                "headers": hdrs,
                "error_log_delta": error_logs() - before,
                "raw": body,
            }}

        out["unknown"] = get("?link=PONTO-LINK-99999999")
        out["unknown_with_token"] = get(f"?link=PONTO-LINK-99999999&token={{tok(pending)}}")
        out["no_args"] = get("")
        out["by_name_pending"] = get(f"?link={{pending}}")
        out["by_name_executed"] = get(f"?link={{executed}}")
        out["by_name_cancelled"] = get(f"?link={{cancelled}}")
        out["wrong_token"] = get(f"?link={{pending}}&token=deadbeef")
        out["empty_token"] = get(f"?link={{pending}}&token=")
        out["non_ascii_token"] = get(f"?link={{pending}}&token=h%C3%A9llo")
        out["other_links_token"] = get(f"?link={{pending}}&token={{tok(other)}}")
        out["deleted_with_token"] = get(f"?link={{deleted}}&token={{deleted_token}}")
        for key, value in foreign.items():
            out["foreign_" + key] = get(f"?link={{pending}}&token={{value}}")
        out["ok_pending"] = get(f"?link={{pending}}&token={{tok(pending)}}")
        out["ok_executed"] = get(f"?link={{executed}}&token={{tok(executed)}}")
        out["ok_cancelled"] = get(f"?link={{cancelled}}&token={{tok(cancelled)}}")
    finally:
        frappe.destroy()
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        for name in created:
            frappe.db.delete("Ponto Payment Link", {{"name": name}})
            frappe.db.delete("Comment", {{"reference_doctype": "Ponto Payment Link", "reference_name": name}})
            frappe.db.delete("Version", {{"ref_doctype": "Ponto Payment Link", "docname": name}})
        frappe.db.commit()
        out["leak_after"] = {{t: frappe.db.count(t) for t in TABLES}}
    print("RESULT" + json.dumps(out))
    """
)

REFUSALS = (
    "unknown_with_token",
    "no_args",
    "by_name_pending",
    "by_name_executed",
    "by_name_cancelled",
    "wrong_token",
    "empty_token",
    "non_ascii_token",
    "other_links_token",
    "deleted_with_token",
    "foreign_cancel",
    "foreign_return_proof",
    "foreign_success",
    "foreign_ponto_pay",
)


class TestPontoPaymentPageOverRealWsgi(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sites_dir = os.path.join(get_bench_path(), "sites")
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT.format(site=frappe.local.site)],
            cwd=sites_dir,
            capture_output=True,
            text=True,
            timeout=240,
        )
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT")]
        assert lines, result.stdout[-3000:] + "\n" + result.stderr[-3000:]
        cls.out = json.loads(lines[-1][len("RESULT") :])

    def test_subprocess_cleaned_up_its_committed_rows(self):
        self.assertEqual(self.out["leak_after"], self.out["leak_before"])

    def test_the_unknown_answer_is_a_404_not_found(self):
        """The reference every refusal is compared with must itself be the refusal."""
        unknown = self.out["unknown"]
        self.assertEqual(unknown["status"], 404)
        self.assertEqual(unknown["body"]["exc_type"], "DoesNotExistError")
        self.assertIn("Payment link not found", unknown["body"]["_server_messages"])

    def test_a_guest_who_only_knows_the_name_is_refused_like_an_unknown_name(self):
        """The #1817 attack: walk PONTO-LINK-{####}. A pending, an executed and a cancelled
        row (real rows, so a status-dependent answer would show) all answer as the unknown name."""
        self.assertNotIn("WSGI-1817-PENDING-DESC", self.out["by_name_pending"]["raw"])
        self.assertNotIn("example.test/sign", self.out["by_name_pending"]["raw"])

    def test_every_refusal_is_identical_to_the_unknown_answer_on_every_channel(self):
        reference = self.out["unknown"]
        for key in REFUSALS:
            for channel in ("status", "body", "headers", "error_log_delta"):
                with self.subTest(refusal=key, channel=channel):
                    self.assertEqual(self.out[key][channel], reference[channel])

    def test_a_refusal_writes_no_error_log_row(self):
        for key in ("unknown",) + REFUSALS:
            with self.subTest(refusal=key):
                self.assertEqual(self.out[key]["error_log_delta"], 0)

    def test_the_real_token_serves_the_pending_link(self):
        """Positive control: the refusals above are about the token, not a broken endpoint."""
        ok = self.out["ok_pending"]
        self.assertEqual(ok["status"], 200)
        message = ok["body"]["message"]
        self.assertEqual(message["status"], "pending")
        self.assertEqual(message["payment_link"], self.out["names"]["pending"])
        self.assertEqual(message["description"], "WSGI-1817-PENDING-DESC")
        self.assertEqual(message["redirect_link"], "https://example.test/sign/wsgi-1817")

    def test_a_token_holder_still_sees_the_legitimate_status_message(self):
        self.assertEqual(self.out["ok_executed"]["body"]["message"]["status"], "already_paid")
        self.assertEqual(self.out["ok_cancelled"]["body"]["message"]["status"], "cancelled")

    def test_a_token_opens_only_its_own_link(self):
        tokens = self.out["tokens"]
        names = self.out["names"]
        self.assertNotEqual(tokens[names["pending"]], tokens[names["other"]])
        self.assertEqual(self.out["other_links_token"]["status"], 404)

    def test_tokens_do_not_follow_the_sequential_name(self):
        """The token is not derivable from the name: consecutive links share no structure and
        the token contains no part of the name's counter."""
        tokens = self.out["tokens"]
        names = self.out["names"]
        for key in ("pending", "other"):
            digits = re.search(r"(\d+)$", names[key]).group(1)
            self.assertNotIn(digits, tokens[names[key]])
            self.assertGreaterEqual(len(tokens[names[key]]), 32)
