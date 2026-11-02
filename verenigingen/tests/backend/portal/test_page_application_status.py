"""The status page of a membership application (#1765, and #1051 before it).

The page reads a Membership Application Submission and is gated by the guest return token minted for
its NAME when the application is confirmed. It is a guest surface, so a wrong token, an unknown name
and a token minted for another application must be refused the same way on every channel.

Probe shortcuts, stated: the rows are inserted and then moved to a status with a db write
(update_modified=False), standing in for the confirm / review flow; `review_notes` is written by hand,
or by the same helper the reject endpoint uses, to stand in for a reviewer. The real reject flow is
covered in test_application_record_approval (test_rejected_application_status_page_shows_only_the_reason).
The oracle comparison runs through the real WSGI app in a subprocess (rule 21 of dispatch/README.md):
frappe.app.application destroys frappe.local per request, which would pull the running test's
transaction out from under it.
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path, now_datetime
from frappe.website.serve import get_response_content

from verenigingen.api.membership_application_review import _rejection_review_notes
from verenigingen.services.member.application.application_record import build_status_url
from verenigingen.templates.pages.application_status import (
    APPLICATION_STATUS_TOKEN_PURPOSE,
    applicant_visible_reason,
    get_context,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

SUBMISSION = "Membership Application Submission"
STAFF_ONLY = "STAFF-ONLY internal note about the applicant"


def _status_token(name):
    return generate_guest_return_token(APPLICATION_STATUS_TOKEN_PURPOSE, name)


class StatusPageCase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        self._original_user = frappe.session.user
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    def _make_status_row(self, status="Pending Review", **fields):
        doc = frappe.get_doc(
            {
                "doctype": SUBMISSION,
                "email": f"status.{frappe.generate_hash(length=8).lower()}@example.org",
                "source": "Short Form",
                "payload": "{}",
            }
        )
        doc.insert()
        self.track_doc(SUBMISSION, doc.name)
        values = {
            "status": status,
            "application_id": f"APP-{frappe.generate_hash(length=6).upper()}",
            "confirmed_on": now_datetime(),
        }
        values.update(fields)
        frappe.db.set_value(SUBMISSION, doc.name, values, update_modified=False)
        return frappe.get_doc(SUBMISSION, doc.name)

    def _context_as_guest(self, name, token):
        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": name, "token": token})
            ctx = frappe._dict()
            get_context(ctx)
        return ctx

    def _page_as_guest(self, name, token):
        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": name, "token": token})
            return get_response_content("application_status")


class TestStatusPageReadsTheApplication(StatusPageCase):
    def test_status_page_reads_application_by_token(self):
        row = self._make_status_row("Pending Review")

        ctx = self._context_as_guest(row.name, _status_token(row.name))

        self.assertEqual(ctx.application.status, "Pending Review")
        self.assertEqual(ctx.application.application_id, row.application_id)
        self.assertTrue(ctx.application.applied_on)
        self.assertEqual(ctx.application.reason, "")

    def test_the_link_the_confirmation_hands_out_opens_the_page(self):
        """The minted link and the page agree on the purpose, the parameter names and the identifier."""
        row = self._make_status_row("Pending Review")
        query = build_status_url(row.name).split("?", 1)[1]
        params = dict(pair.split("=", 1) for pair in query.split("&"))

        ctx = self._context_as_guest(params["id"], params["token"])

        self.assertEqual(ctx.application.application_id, row.application_id)

    def test_the_page_shows_a_message_for_every_status(self):
        shown = {}
        for status in ("Unconfirmed", "Pending Review", "Approved", "Rejected", "Superseded", "Expired"):
            row = self._make_status_row(status)
            page = self._page_as_guest(row.name, _status_token(row.name))
            self.assertIn(row.application_id, page, status)
            shown[status] = page
        self.assertEqual(len(set(shown.values())), len(shown), "two statuses render the same page")

    def test_status_page_refuses_bad_token_identically(self):
        """A wrong token, an unknown name and a token for another application give the same refusal,
        the same page, no message and no Error Log row (in-process; the WSGI twin is below)."""
        row, other = self._make_status_row(), self._make_status_row()
        cases = {
            "no token": (row.name, ""),
            "wrong token": (row.name, "0" * 64),
            "non-ascii token": (row.name, "héllo"),
            "another application's token": (row.name, _status_token(other.name)),
            "unknown name": (f"no-such-{frappe.generate_hash(length=8)}", _status_token("some-other-name")),
            "a name that is not a string": (["x"], _status_token(row.name)),
        }
        errors_before = frappe.db.count("Error Log")
        pages = {}
        for label, (name, token) in cases.items():
            frappe.local.message_log = []
            ctx = self._context_as_guest(name, token)
            self.assertIsNone(ctx.application, label)
            self.assertEqual(frappe.local.message_log, [], label)
            pages[label] = self._page_as_guest(name, token)
        self.assertEqual(frappe.db.count("Error Log"), errors_before)
        self.assertEqual(len(set(pages.values())), 1, "the refusals differ")
        self.assertNotIn(row.application_id, "".join(pages.values()))
        # Control: the right token on the same row is NOT that page.
        self.assertIn(row.application_id, self._page_as_guest(row.name, _status_token(row.name)))

    def test_a_valid_token_for_a_purged_application_looks_like_any_other_refusal(self):
        row = self._make_status_row()
        token = _status_token(row.name)
        refused = self._page_as_guest(row.name, "0" * 64)
        frappe.delete_doc(SUBMISSION, row.name, force=True)

        self.assertEqual(self._page_as_guest(row.name, token), refused)


class TestStatusPageDisclosure(StatusPageCase):
    def test_review_notes_are_shown_only_when_rejected(self):
        notes = _rejection_review_notes(
            {
                "rejection_category": "Other",
                "reason": "Wij zoeken geen leden buiten Nederland",
                "internal_notes": STAFF_ONLY,
                "email_template": None,
            }
        )
        for status in ("Unconfirmed", "Pending Review", "Approved", "Superseded", "Expired"):
            row = self._make_status_row(status, review_notes=notes)  # hand-set: probe shortcut
            page = self._page_as_guest(row.name, _status_token(row.name))
            self.assertNotIn("buiten Nederland", page, status)
            # the context carries nothing either, so a template change cannot start showing it
            self.assertEqual(self._context_as_guest(row.name, _status_token(row.name)).application.reason, "", status)
        rejected = self._make_status_row("Rejected", review_notes=notes)

        page = self._page_as_guest(rejected.name, _status_token(rejected.name))

        self.assertIn("Wij zoeken geen leden buiten Nederland", page)

    def test_internal_notes_category_and_reviewer_are_never_shown(self):
        reviewer = self.create_test_user_with_roles(
            email=f"reviewer.{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Administrator"],
            first_name="Zeldzame",
            last_name="Beoordelaar",
        )
        notes = _rejection_review_notes(
            {
                "rejection_category": "Fraudulent-looking",
                "reason": "Niet in ons werkgebied",
                "internal_notes": STAFF_ONLY,
                "email_template": "Some Template",
            }
        )
        row = self._make_status_row(
            "Rejected",
            review_notes=notes,
            reviewed_by=reviewer.email,
            review_date=now_datetime(),
            rejection_category="Fraudulent-looking",
        )

        page = self._page_as_guest(row.name, _status_token(row.name))

        self.assertIn("Niet in ons werkgebied", page)
        for secret in (STAFF_ONLY, "Fraudulent-looking", "Some Template", reviewer.email, "Beoordelaar"):
            self.assertNotIn(secret, page)
        ctx = self._context_as_guest(row.name, _status_token(row.name))
        self.assertEqual(set(ctx.application), {"status", "application_id", "applied_on", "reason"})

    def test_the_reason_is_cut_at_the_labels_the_reject_helper_writes(self):
        """Tied to _rejection_review_notes, so a change to its format reddens here, not on the page."""

        def notes(reason, internal=None):
            return _rejection_review_notes(
                {"rejection_category": "Other", "reason": reason, "internal_notes": internal, "email_template": None}
            )

        self.assertEqual(applicant_visible_reason(notes("Reden")), "Reden")
        self.assertEqual(applicant_visible_reason(notes("Reden", STAFF_ONLY)), "Reden")
        self.assertEqual(applicant_visible_reason(notes("Regel een\nregel twee", STAFF_ONLY)), "Regel een\nregel twee")
        self.assertEqual(applicant_visible_reason("free text a reviewer typed"), "")
        self.assertEqual(applicant_visible_reason(None), "")

    def test_every_printed_value_is_escaped(self):
        """Jinja autoescape is off here: a value the template prints without `|e` lands as markup."""
        row = self._make_status_row(
            "Rejected",
            application_id='"><img src=x onerror=alert(1)>',
            review_notes="Rejection Category: x\nReason: <script>alert(2)</script>\nEmail Template Used: Default",
        )

        page = self._page_as_guest(row.name, _status_token(row.name))

        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<script>alert(2)", page)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)

    def test_a_logged_in_member_needs_the_token_too(self):
        """The old session-ownership fallback is gone: an application has no Member until it is approved."""
        row = self._make_status_row()
        member = self.create_test_member(email=f"appstatus-{frappe.generate_hash(length=8)}@example.com")
        self.track_doc("Member", member.name)
        user = self.create_test_user_with_roles(email=member.email, roles=["Verenigingen Member"])

        with self.as_user(user.email):
            frappe.local.form_dict = frappe._dict({"id": row.name})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNone(ctx.application)


class TestStatusPageOverWsgi(StatusPageCase):
    """The oracle comparison through the real request path, read back on fresh connections."""

    def test_refusals_are_identical_over_a_real_request(self):
        site = frappe.local.site
        script = textwrap.dedent(
            f"""
            import json, re, uuid
            import frappe
            from frappe.utils import now_datetime

            SITE = {site!r}
            SUBMISSION = {SUBMISSION!r}

            def make(status, **fields):
                doc = frappe.get_doc({{"doctype": SUBMISSION, "source": "Short Form", "payload": "{{}}",
                    "email": "wsgi." + uuid.uuid4().hex[:8] + "@example.org"}})
                doc.insert()
                frappe.db.set_value(SUBMISSION, doc.name, dict(status=status,
                    application_id="APP-" + uuid.uuid4().hex[:6].upper(),
                    confirmed_on=now_datetime(), **fields), update_modified=False)
                return doc.name, frappe.db.get_value(SUBMISSION, doc.name, "application_id")

            frappe.init(site=SITE)
            frappe.connect()
            try:
                pending, pending_id = make("Pending Review")
                other, _ = make("Pending Review")
                rejected, rejected_id = make("Rejected",
                    review_notes="Rejection Category: x\\nReason: zichtbare reden\\nInternal Notes: {STAFF_ONLY}\\nEmail Template Used: Default")
                from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token as gen
                purpose = {APPLICATION_STATUS_TOKEN_PURPOSE!r}
                tok = lambda n: gen(purpose, n)
                unknown = "no-such-" + uuid.uuid4().hex[:10]
                tokens = dict(pending=tok(pending), other=tok(other), rejected=tok(rejected), unknown=tok(unknown))
                errors_before = frappe.db.count("Error Log")
                frappe.db.commit()
                frappe.destroy()

                import frappe.app
                from werkzeug.test import Client
                client = Client(frappe.app.application, use_cookies=False)
                headers = {{"X-Frappe-Site-Name": SITE}}

                def get(name, token):
                    r = client.get("/application_status", query_string={{"id": name, "token": token}}, headers=headers)
                    body = r.get_data(as_text=True)
                    body = re.sub(r'csrf_token\\s*[=:]\\s*"[^"]*"', "csrf_token", body)
                    return {{"status": r.status_code, "body": body,
                             "type": r.headers.get("Content-Type"),
                             "cookies": sorted(c.split("=")[0] for c in r.headers.get_all("Set-Cookie"))}}

                out = dict(
                    wrong_token=get(pending, "0" * 64),
                    foreign_token=get(pending, tokens["other"]),
                    unknown_name=get(unknown, tokens["unknown"]),
                    no_token=get(pending, ""),
                    pending_ok=get(pending, tokens["pending"]),
                    rejected_ok=get(rejected, tokens["rejected"]),
                    ids=dict(pending=pending_id, rejected=rejected_id),
                )

                frappe.init(site=SITE)
                frappe.connect()
                out["error_log_delta"] = frappe.db.count("Error Log") - errors_before
                print("RESULT" + json.dumps(out))
            finally:
                if not frappe.local.site:
                    frappe.init(site=SITE)
                if not getattr(frappe.local, "db", None):
                    frappe.connect()
                for name in [n for n in (locals().get("pending"), locals().get("other"), locals().get("rejected")) if n]:
                    frappe.db.delete(SUBMISSION, {{"name": name}})
                frappe.db.commit()
                frappe.destroy()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        out = json.loads(next(l for l in result.stdout.splitlines() if l.startswith("RESULT"))[len("RESULT") :])

        refusals = [out[k] for k in ("wrong_token", "foreign_token", "unknown_name", "no_token")]
        for refusal in refusals:
            self.assertEqual(refusal, refusals[0])
        self.assertEqual(refusals[0]["status"], 200)
        self.assertIn("No application found", refusals[0]["body"])
        self.assertEqual(out["error_log_delta"], 0)
        # Controls: the right token on the same rows is not that page, and shows the application.
        self.assertIn(out["ids"]["pending"], out["pending_ok"]["body"])
        self.assertNotIn(out["ids"]["pending"], refusals[0]["body"])
        self.assertIn("zichtbare reden", out["rejected_ok"]["body"])
        self.assertNotIn(STAFF_ONLY, out["rejected_ok"]["body"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"application_id": out["ids"]["pending"]}), 0)
