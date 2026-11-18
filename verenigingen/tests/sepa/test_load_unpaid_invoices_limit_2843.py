"""#2843: the Load Unpaid Invoices dialog posts `limit` as a STRING and the endpoint refused all of them.

`load_unpaid_invoices` / `load_unpaid_invoices_secure` checked `isinstance(limit, int)`, but a form POST
(what `frappe.call` sends) delivers every value as text, so "100" was refused exactly like "abc". The
existing tests call the function in-process with an int and could not see it. These tests drive the real
WSGI app (`werkzeug.test.Client(frappe.app.application)`, README rule 21) as a user holding the
"Verenigingen System Administrator" role profile (System Manager alone is refused), with a session and
CSRF token, as the browser does. No API keys.

The WSGI half runs as a SUBPROCESS because `frappe.app.application` destroys/re-inits `frappe.local` per
request (same approach as test_ponto_callback_wsgi). The subprocess commits a login user and deletes it in
a `finally`; row counts of the touched tables are compared before/after. If the subprocess is KILLED the
user stays; re-running the module reuses and then deletes it.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_load_unpaid_invoices_limit_2843
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.error_handling import SEPAError
from verenigingen.verenigingen_payments.utils.sepa_input_validation import SEPAInputValidator

LIMIT_MESSAGE = "Invalid limit. Must be between 1 and 10000"

SCRIPT = textwrap.dedent(
    """
    import json, re
    import frappe

    SITE = {site!r}
    EMAIL = "limit-2843-wsgi@example.org"
    PW = "Limit-2843-Wsgi-Xz!9"
    BASE = "/api/method/verenigingen.verenigingen_payments.api.{module}.{fn}"
    TABLES = ("User", "Has Role", "Contact", "Notification Settings", "Version")
    out = {{"responses": {{}}}}

    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")
    started = frappe.utils.now_datetime()
    out["leak_before"] = {{t: frappe.db.count(t) for t in TABLES}}
    try:
        if not frappe.db.exists("User", EMAIL):
            user = frappe.new_doc("User")
            user.email = EMAIL
            user.first_name = "Limit2843"
            user.send_welcome_email = 0
            user.append("role_profiles", {{"role_profile": "Verenigingen System Administrator"}})
            user.insert(ignore_permissions=True)
        from frappe.utils.password import update_password
        update_password(EMAIL, PW)
        frappe.db.commit()
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client
        client = Client(frappe.app.application)
        headers = {{"X-Frappe-Site-Name": SITE}}
        addr = {{"REMOTE_ADDR": "10.28.4.3"}}
        login = client.post("/api/method/login", data={{"usr": EMAIL, "pwd": PW}}, headers=headers, environ_base=addr)
        out["login"] = login.status_code
        page = client.get("/desk", headers=headers, environ_base=addr).get_data(as_text=True)
        headers["X-Frappe-CSRF-Token"] = re.search(r'csrf_token["\\'\\s:=]+([0-9a-f]{{10,}})', page).group(1)

        for module, fn in {targets!r}:
            for limit in {limits!r}:
                data = {{"date_range": "all"}}
                if limit is not None:
                    data["limit"] = limit
                resp = client.post(BASE.format(module=module, fn=fn), data=data, headers=headers, environ_base=addr)
                body = json.loads(resp.get_data(as_text=True))
                out["responses"][module + "|" + repr(limit)] = {{
                    "status": resp.status_code,
                    "message": body.get("message"),
                    "exception": body.get("exception"),
                }}
    finally:
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        if frappe.db.exists("User", EMAIL):
            frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
        for name in frappe.get_all("Contact", filters={{"email_id": EMAIL}}, pluck="name"):
            frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
        # the deletes above leave Version / "Deleted" Comment / Deleted Document rows behind
        frappe.db.delete("Version", {{"docname": ["in", [EMAIL, "Limit2843"]]}})
        mine = ["User", "Contact", "Notification Settings"]
        frappe.db.delete("Comment", {{"comment_type": "Deleted", "reference_doctype": ["in", mine], "creation": [">=", started]}})
        frappe.db.delete("Deleted Document", {{"deleted_doctype": ["in", mine], "creation": [">=", started]}})
        frappe.db.commit()
        out["leak_after"] = {{t: frappe.db.count(t) for t in TABLES}}
    print("RESULT" + json.dumps(out, default=str))
    """
)

TARGETS = [("sepa_batch_ui", "load_unpaid_invoices"), ("sepa_batch_ui_secure", "load_unpaid_invoices_secure")]
LIMITS = ["100", "1", "10000", "0", "10001", "99999", "-5", "abc", "1.5", "", None]


class TestLoadUnpaidInvoicesLimitOverWsgi(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        script = SCRIPT.format(site=frappe.local.site, module="{module}", fn="{fn}", targets=TARGETS, limits=LIMITS)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=240,
        )
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT")]
        assert lines, result.stdout[-3000:] + "\n" + result.stderr[-3000:]
        cls.out = json.loads(lines[-1][len("RESULT") :])

    def _refused(self, module, limit):
        resp = self.out["responses"][f"{module}|{limit!r}"]
        # the plain endpoint is @handle_api_error (400 in the body); the _secure twin raises (417)
        self.assertIn(resp["status"], (400, 417), resp)
        return json.dumps(resp)

    def _loaded(self, module, limit):
        resp = self.out["responses"][f"{module}|{limit!r}"]
        self.assertEqual(resp["status"], 200, resp)
        self.assertIsInstance(resp["message"], list, resp)

    def test_the_run_logged_in_and_cleaned_up_after_itself(self):
        self.assertEqual(self.out["login"], 200)
        self.assertEqual(self.out["leak_after"], self.out["leak_before"])

    def test_a_digit_string_limit_loads_invoices(self):
        for module, _fn in TARGETS:
            for limit in ("100", "1", "10000"):
                with self.subTest(module=module, limit=limit):
                    self._loaded(module, limit)

    def test_no_limit_still_loads_invoices(self):
        for module, _fn in TARGETS:
            with self.subTest(module=module):
                self._loaded(module, None)

    def test_out_of_range_limits_are_refused_with_the_range_message(self):
        for module, _fn in TARGETS:
            for limit in ("0", "10001", "99999", "-5"):
                with self.subTest(module=module, limit=limit):
                    self.assertIn(LIMIT_MESSAGE, self._refused(module, limit))

    def test_non_numeric_limits_are_refused_not_coerced_to_a_number(self):
        for module, _fn in TARGETS:
            for limit in ("abc", "1.5", ""):
                with self.subTest(module=module, limit=limit):
                    self.assertIn(LIMIT_MESSAGE, self._refused(module, limit))


class TestParseBatchLimit(EnhancedTestCase):
    def test_digit_strings_and_ints_become_ints(self):
        for raw, expected in (("100", 100), (" 7 ", 7), ("\t7 ", 7), ("+5", 5), ("0000100", 100), (100, 100), ("10000", 10000), (1, 1)):
            with self.subTest(raw=raw):
                value = SEPAInputValidator.parse_batch_limit(raw)
                self.assertEqual(value, expected)
                self.assertIs(type(value), int)

    def test_none_means_no_limit(self):
        self.assertIsNone(SEPAInputValidator.parse_batch_limit(None))

    def test_out_of_range_and_non_numeric_values_are_refused(self):
        for raw in ("0", 0, "-1", -1, "10001", 10001, "abc", "1.5", "", " ", "1e3", 1.5, 100.0, True, False, [], "١٢", "9" * 5000, "\xa05", "1\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(SEPAError) as ctx:
                    SEPAInputValidator.parse_batch_limit(raw)
                self.assertIn(LIMIT_MESSAGE, str(ctx.exception))
