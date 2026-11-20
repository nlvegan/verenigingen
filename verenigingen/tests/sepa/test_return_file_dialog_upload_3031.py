"""#3031: the Direct Debit Batch "Process Return File" dialog sent the Attach URL as the file content.

An Attach control's value is the uploaded File's URL, never its content, so the parser failed, logged,
and the endpoint answered 200 {processed: 0, total: 0} whatever was uploaded. These tests drive the real
WSGI app (`werkzeug.test.Client(frappe.app.application)`) as a user holding the "Verenigingen System
Administrator" role profile, with a session and CSRF token, exactly as the dialog does: a real File doc
is uploaded and its `file_url` is posted. The WSGI half runs as a SUBPROCESS (frappe.app.application
destroys/re-inits `frappe.local` per request; same approach as test_load_unpaid_invoices_limit_2843).
The subprocess commits a login user and its File rows and deletes them in a `finally`; row counts of the
touched tables are compared before/after.

Usage:
    bench --site test_site_10 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_return_file_dialog_upload_3031
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

# E2E ids carry no "E2E-" prefix, so accepting them touches no invoice: the count is all that is observable.
PAIN002 = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03"><CstmrPmtStsRpt><OrgnlPmtInfAndSts>'
    "<TxInfAndSts><OrgnlEndToEndId>NOPREFIX-1</OrgnlEndToEndId><TxSts>ACSP</TxSts></TxInfAndSts>"
    "<TxInfAndSts><OrgnlEndToEndId>NOPREFIX-2</OrgnlEndToEndId><TxSts>ACSP</TxSts></TxInfAndSts>"
    "</OrgnlPmtInfAndSts></CstmrPmtStsRpt></Document>"
)

SCRIPT = textwrap.dedent(
    """
    import json, re
    import frappe

    SITE = {site!r}
    import uuid
    # per-run user: the endpoint is rate limited per user (100/hour), so a fixed user starves reruns
    EMAIL = "rf3031-" + uuid.uuid4().hex[:8] + "@example.org"
    PW = "Return-3031-Wsgi-Xz!9"
    URL = "/api/method/verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation.process_sepa_return_file"
    TABLES = ("User", "Has Role", "Contact", "Notification Settings", "Version", "File")
    PAIN002 = {pain002!r}
    out = {{"responses": {{}}}}
    made_files = []

    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")
    started = frappe.utils.now_datetime()
    out["leak_before"] = {{t: frappe.db.count(t) for t in TABLES}}

    def make_file(name, content, owner):
        doc = frappe.get_doc({{"doctype": "File", "file_name": name, "content": content, "is_private": 1}})
        doc.owner = owner
        doc.insert(ignore_permissions=True)
        doc.db_set("owner", owner)
        made_files.append(doc.name)
        return doc.file_url

    try:
        if not frappe.db.exists("User", EMAIL):
            user = frappe.new_doc("User")
            user.email = EMAIL
            user.first_name = "Return3031"
            user.send_welcome_email = 0
            user.append("role_profiles", {{"role_profile": "Verenigingen System Administrator"}})
            user.insert(ignore_permissions=True)
        from frappe.utils.password import update_password
        update_password(EMAIL, PW)
        mine = make_file("return-3031-mine.xml", PAIN002, EMAIL)
        garbage = make_file("return-3031-garbage.xml", "not xml at all", EMAIL)
        wrong_root = make_file("return-3031-wrong-root.xml", "<html><body/></html>", EMAIL)
        # private, owned by someone else, attached to nothing: the caller must not read it. Distinct
        # content: File.insert de-duplicates identical content onto the FIRST row's file_url.
        forbidden = make_file("return-3031-forbidden.xml", PAIN002 + "<!-- distinct hash -->", "Administrator")
        remote = frappe.get_doc({{"doctype": "File", "file_name": "return-3031-remote.xml",
                                 "file_url": "http://example.org/return-3031-remote.xml", "is_private": 0}})
        remote.insert(ignore_permissions=True)
        made_files.append(remote.name)
        frappe.db.commit()
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client
        client = Client(frappe.app.application)
        headers = {{"X-Frappe-Site-Name": SITE}}
        addr = {{"REMOTE_ADDR": "10.30.3.1"}}
        login = client.post("/api/method/login", data={{"usr": EMAIL, "pwd": PW}}, headers=headers, environ_base=addr)
        out["login"] = login.status_code
        page = client.get("/desk", headers=headers, environ_base=addr).get_data(as_text=True)
        headers["X-Frappe-CSRF-Token"] = re.search(r'csrf_token["\\'\\s:=]+([0-9a-f]{{10,}})', page).group(1)

        def call(key, **data):
            data.setdefault("file_type", "pain.002")
            resp = client.post(URL, data=data, headers=headers, environ_base=addr)
            body = json.loads(resp.get_data(as_text=True))
            out["responses"][key] = {{
                "status": resp.status_code,
                "message": body.get("message"),
                "exception": body.get("exception"),
                "server_messages": body.get("_server_messages"),
                "keys": sorted(body.keys()),
            }}

        call("url_mine", file_url=mine)
        call("content_control", file_content=PAIN002)
        call("url_garbage", file_url=garbage)
        call("url_wrong_root", file_url=wrong_root)
        call("content_garbage", file_content="not xml")
        call("url_as_content", file_content=mine)
        call("url_unknown", file_url="/private/files/return-3031-nonexistent.xml")
        call("url_forbidden", file_url=forbidden)
        call("url_traversal", file_url="/private/files/../../../../../../etc/passwd")
        call("nothing")
        out["forbidden_url_is_real"] = forbidden
        call("url_remote", file_url="http://example.org/return-3031-remote.xml")

        # query count of the lookup itself, as the same user, unknown vs forbidden
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user(EMAIL)
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import _read_uploaded_return_file
        def queries(url):
            n = [0]
            real = frappe.db.sql
            def counting(*a, **k):
                n[0] += 1
                return real(*a, **k)
            frappe.db.sql = counting
            try:
                _read_uploaded_return_file(url)
            except Exception:
                pass  # only the count matters here; the refusals are asserted over WSGI
            finally:
                del frappe.db.sql
            return n[0]
        queries(forbidden)  # warm caches (meta, roles) so the counted runs compare like with like
        out["queries_unknown"] = queries("/private/files/return-3031-nonexistent.xml")
        out["queries_forbidden"] = queries(forbidden)
        out["queries_remote"] = queries("http://example.org/return-3031-remote.xml")
        frappe.set_user("Administrator")
    finally:
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        for name in made_files:
            if frappe.db.exists("File", name):
                frappe.delete_doc("File", name, force=True, ignore_permissions=True)
        if frappe.db.exists("User", EMAIL):
            frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
        for name in frappe.get_all("Contact", filters={{"email_id": EMAIL}}, pluck="name"):
            frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
        frappe.db.delete("Version", {{"docname": ["in", [EMAIL, "Return3031"]]}})
        gone = ["User", "Contact", "Notification Settings", "File"]
        frappe.db.delete("Comment", {{"comment_type": "Deleted", "reference_doctype": ["in", gone], "creation": [">=", started]}})
        frappe.db.delete("Deleted Document", {{"deleted_doctype": ["in", gone], "creation": [">=", started]}})
        frappe.db.commit()
        out["leak_after"] = {{t: frappe.db.count(t) for t in TABLES}}
    print("RESULT" + json.dumps(out, default=str))
    """
)


class TestReturnFileDialogUploadOverWsgi(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        script = SCRIPT.format(site=frappe.local.site, pain002=PAIN002)
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

    def _resp(self, key):
        resp = dict(self.out["responses"][key])
        # frappe stamps every raised exception with a random id; it is not content
        if resp.get("server_messages"):
            resp["server_messages"] = re.sub(r"__frappe_exc_id[^,}]*", "", resp["server_messages"])
        return resp

    def test_the_run_logged_in_and_cleaned_up_after_itself(self):
        self.assertEqual(self.out["login"], 200)
        self.assertEqual(self.out["leak_after"], self.out["leak_before"])

    def test_the_content_path_processes_the_returns(self):
        """Control: the real pain.002 content processes both transactions (so 0/0 below is not the fixture)."""
        resp = self._resp("content_control")
        self.assertEqual(resp["status"], 200, resp)
        self.assertEqual(resp["message"], {"processed": 2, "total": 2})

    def test_the_uploaded_files_url_processes_the_same_returns(self):
        """The dialog's real input: the File's URL. Before #3031 this answered {processed: 0, total: 0}."""
        resp = self._resp("url_mine")
        self.assertEqual(resp["status"], 200, resp)
        self.assertEqual(resp["message"], {"processed": 2, "total": 2})

    def test_an_unparseable_upload_is_an_error_not_zero_of_zero(self):
        for key in ("url_garbage", "url_wrong_root", "content_garbage"):
            resp = self._resp(key)
            self.assertEqual(resp["status"], 417, (key, resp))
            self.assertIn("not a valid pain.002", json.dumps(resp), (key, resp))
            self.assertNotIn("processed", json.dumps(resp["message"]), (key, resp))

    def test_the_url_sent_as_content_is_the_old_dialog_call_and_is_now_an_error(self):
        """The dialog's pre-fix call (`file_content` = the Attach URL) answered 200 {processed: 0, total: 0}."""
        resp = self._resp("url_as_content")
        self.assertEqual(resp["status"], 417, resp)
        self.assertIn("not a valid pain.002", json.dumps(resp))

    def test_unknown_and_forbidden_urls_are_refused_identically(self):
        """Existence oracle: a real private file the caller may not read looks exactly like a missing one."""
        self.assertTrue(self.out["forbidden_url_is_real"].startswith("/private/files/"))
        unknown, forbidden = self._resp("url_unknown"), self._resp("url_forbidden")
        self.assertEqual(unknown["status"], 403, unknown)
        self.assertIn("Return file not found or not accessible", json.dumps(unknown))
        self.assertEqual(unknown, forbidden)

    def test_unknown_and_forbidden_urls_cost_the_same_number_of_queries(self):
        """Query count is a channel too (review N1): the forbidden File must not cost more than a missing one."""
        self.assertGreater(self.out["queries_unknown"], 0)
        self.assertEqual(self.out["queries_unknown"], self.out["queries_forbidden"], self.out)

    def test_a_remote_url_file_is_refused_like_an_unknown_one(self):
        """A readable File row with an http file_url has no local content: refuse, do not 500 (review N3)."""
        self.assertEqual(self._resp("url_remote"), self._resp("url_unknown"))
        self.assertEqual(self.out["queries_remote"] > 0, True)

    def test_a_filesystem_path_is_never_opened(self):
        resp = self._resp("url_traversal")
        self.assertEqual(resp, self._resp("url_unknown"))
        self.assertNotIn("root:", json.dumps(resp))

    def test_no_file_at_all_is_refused(self):
        resp = self._resp("nothing")
        self.assertEqual(resp["status"], 417, resp)
        self.assertIn("No return file was provided", json.dumps(resp))
