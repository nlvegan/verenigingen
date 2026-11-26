"""consent_ip / consent_text on SEPA Mandate are staff-only (#2480, maintainer ruling 2026-11-20).

Board and chapter scopes read a mandate through ``permissions.has_sepa_mandate_permission``
and the ``Verenigingen Member`` role's permlevel-0 DocPerm. They must not receive the
signing IP or the agreed text, on ANY channel. Staff roles (System Manager, Verenigingen
Staff, Verenigingen Administrator) still do. The member's own consent capture
(``setup_sepa_direct_debit``) must still store both values.

Stand-ins, stated: the mandate is created through the REAL member endpoint (real member
session, real consent hash); the request used for the IP is a real werkzeug Request bound as
tests/security/test_client_ip_sources.py binds one. The board seat is built by
``create_test_board_member`` (real Volunteer, Chapter Board Member row, role profile) and the
subject member is placed in that chapter. No probe shortcuts set a consent field directly.
"""

import json

import frappe
from frappe.auth import HTTPRequest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api.member import sepa_api
from verenigingen.services.payment import sepa_mandate_consent as consent_module
from verenigingen.services.payment.sepa_mandate_consent import hash_consent_text
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.tests.support.wsgi_http_session import CommittedLoginUsersMixin, api_path, run_wsgi_cases
from verenigingen.utils.validation.iban_validator import generate_test_iban

PROXY = "127.0.0.1"
SIGNING_IP = "203.0.113.80"
STAFF_ROLES = ("System Manager", "Verenigingen Staff", "Verenigingen Administrator")
SECRET_FIELDS = ("consent_ip", "consent_text")


class TestSepaMandateConsentPermlevel2480(PortalSelfServiceTestMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._orig_request = getattr(frappe.local, "request", None)
        self._orig_request_ip = getattr(frappe.local, "request_ip", None)
        self.addCleanup(self._restore_request_2480)
        self.chapter = self.create_test_chapter()
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        self.member = self.create_test_member(birth_date="1990-01-01")
        self.member_user = self._link_member_to_user(self.member)
        self.add_member_to_test_chapter(self.member.name, self.chapter.name)
        self.mandate_name = self._member_signs_via_endpoint_2480()

    def _restore_request_2480(self):
        frappe.local.request = self._orig_request
        frappe.local.request_ip = self._orig_request_ip

    def _member_signs_via_endpoint_2480(self):
        environ = EnvironBuilder(
            method="POST", path="/x", headers={"X-Forwarded-For": f"198.51.100.9, {SIGNING_IP}"}, data=b"{}"
        ).get_environ()
        environ["REMOTE_ADDR"] = PROXY
        frappe.local.request = Request(environ)
        HTTPRequest.__new__(HTTPRequest).set_request_ip()
        text_hash = hash_consent_text(consent_module.get_mandate_consent_text())
        with self._as_user(self.member_user.name):
            result = sepa_api.setup_sepa_direct_debit(
                iban=generate_test_iban("TEST"),
                account_holder_name="Test Holder",
                consent=1,
                consent_text_hash=text_hash,
            )
        self.assertTrue(result.get("success"), msg=result)
        return result["mandate_name"]

    def _staff_user_2480(self, role):
        slug = role.replace(" ", "").lower()
        return self.factory.create_user_with_roles(
            email=f"perm2480-{slug}-{self.uid}@example.com", roles=[role]
        ).name

    # ---- channels: each returns the consent values the caller was handed ----

    def _via_client_get_2480(self, user):
        from frappe.client import get

        with self._as_user(user):
            return get("SEPA Mandate", self.mandate_name)

    def _via_client_get_list_2480(self, user):
        from frappe.client import get_list

        with self._as_user(user):
            rows = get_list(
                "SEPA Mandate",
                filters={"name": self.mandate_name},
                fields=["name", "mandate_id", *SECRET_FIELDS],
            )
        return rows[0] if rows else {}

    def _via_getdoc_2480(self, user):
        from frappe.desk.form.load import getdoc

        with self._as_user(user):
            frappe.response.pop("docs", None)
            getdoc("SEPA Mandate", self.mandate_name)
            docs = frappe.response.get("docs") or []
            frappe.response.pop("docs", None)
            frappe.response.pop("docinfo", None)
        return docs[0] if docs else {}

    def _via_reportview_2480(self, user):
        from frappe.desk.reportview import get

        with self._as_user(user):
            frappe.local.form_dict = frappe._dict(
                doctype="SEPA Mandate",
                fields=json.dumps(["`tabSEPA Mandate`.`name`", *[f"`tabSEPA Mandate`.`{f}`" for f in SECRET_FIELDS]]),
                filters=json.dumps({"name": self.mandate_name}),
            )
            result = get()
        return result

    # ---- red/green: the board scope ----

    def test_capture_still_stores_both_values_through_the_real_flow(self):
        stored = frappe.db.get_value("SEPA Mandate", self.mandate_name, list(SECRET_FIELDS), as_dict=True)
        self.assertEqual(stored.consent_ip, SIGNING_IP)
        self.assertEqual(stored.consent_text, consent_module.get_mandate_consent_text())

    def test_board_user_does_not_receive_consent_values_on_any_channel(self):
        board = self.board.user
        # Control first: the board user CAN read this mandate, so an absent value below is the
        # permlevel, not a refused read.
        self.assertTrue(frappe.has_permission("SEPA Mandate", "read", doc=self.mandate_name, user=board))
        for label, getter in (
            ("frappe.client.get", self._via_client_get_2480),
            ("frappe.client.get_list", self._via_client_get_list_2480),
            ("desk.form.load.getdoc", self._via_getdoc_2480),
        ):
            payload = getter(board)
            self.assertTrue(payload.get("name") == self.mandate_name, msg=f"{label}: control read failed")
            for field in SECRET_FIELDS:
                self.assertFalse(payload.get(field), msg=f"{label} leaked {field} to a board user")

    def test_board_user_reportview_does_not_return_consent_values(self):
        board = self.board.user
        try:
            result = self._via_reportview_2480(board)
        except frappe.PermissionError:
            return  # refusing the whole request is also not a leak
        flat = json.dumps(result, default=str)
        self.assertNotIn(SIGNING_IP, flat)
        self.assertNotIn(consent_module.get_mandate_consent_text()[:30], flat)

    def test_the_signing_member_does_not_receive_them_either(self):
        """Ruling: staff roles only. The member's own session is not a staff role."""
        for field in SECRET_FIELDS:
            self.assertFalse(self._via_client_get_2480(self.member_user.name).get(field), msg=field)

    # ---- staff keep reading ----

    def test_each_staff_role_still_receives_both_values(self):
        for role in STAFF_ROLES:
            user = self._staff_user_2480(role)
            for label, getter in (
                ("frappe.client.get", self._via_client_get_2480),
                ("frappe.client.get_list", self._via_client_get_list_2480),
                ("desk.form.load.getdoc", self._via_getdoc_2480),
            ):
                payload = getter(user)
                self.assertEqual(payload.get("consent_ip"), SIGNING_IP, msg=f"{role} via {label}")
                self.assertEqual(
                    payload.get("consent_text"),
                    consent_module.get_mandate_consent_text(),
                    msg=f"{role} via {label}",
                )

    # ---- the declaration itself ----

    def test_both_fields_declare_permlevel_1_and_all_staff_roles_have_a_permlevel_1_read_row(self):
        meta = frappe.get_meta("SEPA Mandate")
        for field in SECRET_FIELDS:
            self.assertEqual(meta.get_field(field).permlevel, 1, msg=field)
        readers = {p.role for p in meta.permissions if p.permlevel == 1 and p.read}
        self.assertEqual(readers, set(STAFF_ROLES))
        self.assertFalse({p.role for p in meta.permissions if p.permlevel == 1 and p.write})


class TestSepaMandateConsentPermlevelOverRest2480(
    CommittedLoginUsersMixin, PortalSelfServiceTestMixin, EnhancedTestCase
):
    """The real WSGI app: a session cookie from POST /api/method/login, then frappe.client.get.

    Stand-ins, stated: ``Member.user`` is linked with ``db.set_value`` (the login user is the
    plain-member reader); the mandate itself is created through the real endpoint. Fixtures are
    committed because the WSGI child is another DB connection, and removed afterwards. The
    board scope is covered in-process by the class above (building a committed board seat is
    out of proportion); this class proves the staff/non-staff split on the HTTP channel.
    """

    def setUp(self):
        super().setUp()
        users = self._create_login_users(staff="Verenigingen Administrator", reader="Verenigingen Member")
        self.staff_email, self.reader_email = users["staff"], users["reader"]
        self.member = self.create_test_member(birth_date="1990-01-01")
        frappe.db.set_value("Member", self.member.name, {"user": self.reader_email, "email": self.reader_email})
        self._orig_request = getattr(frappe.local, "request", None)
        self._orig_request_ip = getattr(frappe.local, "request_ip", None)
        self.addCleanup(self._restore_request_rest_2480)
        environ = EnvironBuilder(
            method="POST", path="/x", headers={"X-Forwarded-For": f"198.51.100.9, {SIGNING_IP}"}, data=b"{}"
        ).get_environ()
        environ["REMOTE_ADDR"] = PROXY
        frappe.local.request = Request(environ)
        HTTPRequest.__new__(HTTPRequest).set_request_ip()
        text_hash = hash_consent_text(consent_module.get_mandate_consent_text())
        with self._as_user(self.reader_email):
            result = sepa_api.setup_sepa_direct_debit(
                iban=generate_test_iban("TEST"), account_holder_name="Rest Holder", consent=1,
                consent_text_hash=text_hash,
            )
        self.assertTrue(result.get("success"), msg=result)  # the endpoint commits, so the child sees it
        self.mandate_name = result["mandate_name"]
        self.addCleanup(self._cleanup_rest_fixture_2480)

    def _restore_request_rest_2480(self):
        frappe.local.request = self._orig_request
        frappe.local.request_ip = self._orig_request_ip

    def _cleanup_rest_fixture_2480(self):
        frappe.db.rollback()
        if frappe.db.exists("SEPA Mandate", self.mandate_name):
            frappe.delete_doc("SEPA Mandate", self.mandate_name, force=True, ignore_permissions=True)
        frappe.db.commit()  # the WSGI child is another DB connection

    def _rest_get_2480(self, email):
        case = {
            "name": "g",
            "endpoint": api_path("frappe.client.get"),
            "login": {"usr": email, "pwd": self.password},
            "csrf": False,
            "json": {"doctype": "SEPA Mandate", "name": self.mandate_name},
        }
        response = run_wsgi_cases(case)["g"]
        self.assertEqual(response["status"], 200, response["body"])
        return json.loads(response["body"])["message"], response["body"]

    def test_non_staff_reader_gets_the_mandate_without_the_consent_values_over_rest(self):
        doc, body = self._rest_get_2480(self.reader_email)
        self.assertEqual(doc["name"], self.mandate_name)  # control: the read itself succeeded
        self.assertNotIn(SIGNING_IP, body)
        for field in SECRET_FIELDS:
            self.assertFalse(doc.get(field), msg=field)

    def test_staff_reader_gets_the_consent_values_over_rest(self):
        doc, _body = self._rest_get_2480(self.staff_email)
        self.assertEqual(doc["consent_text"], consent_module.get_mandate_consent_text())
        self.assertEqual(doc["consent_ip"], SIGNING_IP)
