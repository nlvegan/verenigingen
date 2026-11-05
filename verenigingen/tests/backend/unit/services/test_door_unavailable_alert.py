"""#2127 ruling: a /word-lid door that can offer no plan shows "cannot be used right now" AND alerts staff.

The alert goes to the registered key's recipients (the admin pair), never Administrator; it is sent once a
day per door and reason, not once per visitor; and it must survive a Guest GET, which the framework rolls
back unless the request asks to commit. The in-process tests drive the page context; the WSGI test drives a
real GET as Guest and reads the result back on a fresh connection (dispatch README rule 21).

Probe shortcuts, stated: a door's template is made unusable with a db write (`status` Cancelled), standing
in for an admin cancelling a template that a door still lists.
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

DOOR = "Membership Application Door"
KEY = "door_unavailable"


class DoorAlertCase(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        ensure_notification_registry_rows()  # a key with no row counts as disabled; the patch does this on a site
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"door.alert.{frappe.generate_hash(length=8).lower()}@example.org",
                "first_name": "Door",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()
        self.track_doc("User", user.name)
        self.staff = user.name

    def tearDown(self):
        frappe.form_dict.pop("door", None)
        super().tearDown()

    def _render_door(self, door):
        from verenigingen.www import word_lid

        frappe.form_dict["door"] = door.name
        return word_lid.get_context(frappe._dict())

    def _broken_door(self, **fields):
        template = self._plan_template("Monthly")
        door = self._door(plans=[{"dues_template": template, "is_default": 1}], **fields)
        frappe.db.set_value("Membership Dues Schedule", template, "status", "Cancelled")
        return door, template

    def _alerts(self, door, user=None):
        return frappe.get_all(
            "Notification Log",
            {"document_type": DOOR, "document_name": door.name, "for_user": user or self.staff},
            ["name", "subject", "email_content"],
        )

    def _door_alert_events(self, door):
        return frappe.get_all(
            "Staff Alert Event",
            {"notification_key": KEY, "reference_name": door.name},
            ["name", "outcome", "requires_action"],
        )


class TestDoorUnavailableAlert(DoorAlertCase):
    def test_a_misconfigured_door_raises_exactly_one_alert_across_several_renders(self):
        door, _template = self._broken_door()
        for _ in range(4):
            context = self._render_door(door)
            self.assertEqual(context.plans, [], "control: the page really offers nothing")
        self.assertEqual(len(self._alerts(door)), 1)
        [event] = self._door_alert_events(door)
        self.assertEqual(event.requires_action, 1)

    def test_a_correctly_configured_door_raises_no_alert(self):
        template = self._plan_template("Monthly")
        door = self._door(plans=[{"dues_template": template, "is_default": 1}])
        for _ in range(3):
            self.assertEqual(len(self._render_door(door).plans), 1)
        self.assertEqual(self._alerts(door), [])
        self.assertEqual(self._door_alert_events(door), [])

    def test_a_housemate_door_offers_no_plans_by_design_and_raises_none(self):
        door = self._door(form_shape="Housemate", plans=[])
        self._render_door(door)
        self.assertEqual(self._alerts(door), [])

    def test_the_alert_names_the_door_the_type_and_the_reason(self):
        door, template = self._broken_door(title="Studentendeur")
        self._render_door(door)
        [alert] = self._alerts(door)
        text = alert.subject + alert.email_content
        self.assertIn("Studentendeur", text)
        self.assertIn(door.slug, alert.email_content)
        self.assertIn(self.membership_type.name, alert.email_content)
        self.assertIn(f"template {template} is not an active template", alert.email_content)

    def test_a_different_reason_for_the_same_door_alerts_again(self):
        door, _template = self._broken_door()
        self._render_door(door)
        # Now the type's own default template is below the type minimum: approval refuses the type.
        frappe.db.set_value("Membership Type", self.membership_type.name, "minimum_amount", 25)
        self._render_door(door)
        self._render_door(door)
        texts = [a.email_content for a in self._alerts(door)]
        self.assertEqual(len(texts), 2)
        self.assertTrue(any("approval would refuse membership type" in t for t in texts))
        self.assertTrue(any("is not an active template" in t for t in texts))

    def test_two_doors_each_alert_once(self):
        first, _ = self._broken_door()
        second, _ = self._broken_door()
        for door in (first, second, first, second):
            self._render_door(door)
        self.assertEqual((len(self._alerts(first)), len(self._alerts(second))), (1, 1))

    def test_administrator_is_not_a_recipient_and_the_key_holders_are(self):
        door, _template = self._broken_door()
        self._render_door(door)
        self.assertEqual(len(self._alerts(door)), 1, "control: a holder of the admin role is told")
        self.assertEqual(self._alerts(door, user="Administrator"), [])
        everyone = frappe.get_all(
            "Notification Log", {"document_type": DOOR, "document_name": door.name}, pluck="for_user"
        )
        self.assertNotIn("Administrator", everyone)

    def test_the_key_is_registered_requires_action_and_role_based(self):
        from verenigingen.notification_registry import NOTIFICATION_KEYS, REQUIRES_ACTION_KEYS

        self.assertIn(KEY, NOTIFICATION_KEYS)
        self.assertIn(KEY, REQUIRES_ACTION_KEYS)
        self.assertEqual(NOTIFICATION_KEYS[KEY]["recipient_policy"], "Role-Based")
        config = frappe.get_single("Verenigingen Email Configuration")
        [row] = [nt for nt in config.notification_types if nt.notification_key == KEY]
        self.assertEqual(sorted(r.strip() for r in row.recipient_roles.split(",")), sorted(["System Manager", "Verenigingen Administrator"]))


class TestDoorUnavailableAlertOverWsgi(VereningingenUnitTestCase):
    """A real GET as Guest: the framework rolls a GET back unless the request asks to commit. Builds and
    removes its own committed rows in a subprocess, so the test holds no transaction of its own (a held row
    lock on the email configuration would time the subprocess out)."""

    def test_the_alert_survives_a_guest_get_and_is_read_back_on_a_fresh_connection(self):
        site = frappe.local.site
        script = textwrap.dedent(
            f"""
            import json, uuid
            import frappe

            SITE = {site!r}
            slug = "wsgi-" + uuid.uuid4().hex[:10]
            email = "wsgi.staff." + uuid.uuid4().hex[:8] + "@example.org"
            made = {{}}
            out = {{}}
            frappe.init(site=SITE)
            frappe.connect()
            try:
                from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
                ensure_notification_registry_rows()
                user = frappe.get_doc({{"doctype": "User", "email": email, "first_name": "Wsgi",
                    "send_welcome_email": 0, "enabled": 1,
                    "roles": [{{"role": "Verenigingen Administrator"}}]}}).insert()
                made["user"] = user.name
                mtype = frappe.get_all("Membership Type", {{"dues_schedule_template": ["is", "set"]}}, pluck="name", limit=1)[0]
                source = frappe.db.get_value("Membership Type", mtype, "dues_schedule_template")
                template = frappe.copy_doc(frappe.get_doc("Membership Dues Schedule", source))
                template.schedule_name = "Wsgi " + uuid.uuid4().hex[:6]
                template.insert()
                made["template"] = template.name
                frappe.db.set_value("Membership Dues Schedule", template.name, "status", "Cancelled")
                door = frappe.get_doc({{"doctype": "Membership Application Door", "title": "Wsgi deur",
                    "slug": slug, "membership_type": mtype, "form_shape": "Regular", "enabled": 1,
                    "plans": [{{"dues_template": template.name, "is_default": 1}}]}})
                door.flags.ignore_validate = True  # the template is cancelled on purpose
                door.insert()
                made["door"] = door.name
                frappe.db.commit()
                frappe.destroy()

                import frappe.app
                from werkzeug.test import Client
                client = Client(frappe.app.application, use_cookies=False)
                headers = {{"X-Frappe-Site-Name": SITE}}
                out["statuses"] = [client.get("/word-lid/" + slug, headers=headers).status_code for _ in range(3)]
                body = client.get("/word-lid/" + slug, headers=headers).get_data(as_text=True)
                out["page_says_unavailable"] = "This form cannot be used right now" in body

                frappe.init(site=SITE)
                frappe.connect()  # a FRESH connection: nothing of the requests' transactions is shared
                logs = frappe.get_all("Notification Log",
                    {{"document_type": "Membership Application Door", "document_name": slug}},
                    ["for_user", "subject", "email_content"])
                out["to_user"] = [l.for_user for l in logs if l.for_user == email]
                out["to_administrator"] = [l.for_user for l in logs if l.for_user == "Administrator"]
                out["content"] = next((l.email_content for l in logs if l.for_user == email), "")
                out["events"] = frappe.get_all("Staff Alert Event",
                    {{"notification_key": "door_unavailable", "reference_name": slug}}, pluck="outcome")
                print("RESULT" + json.dumps(out))
            finally:
                if not frappe.local.site:
                    frappe.init(site=SITE)
                if not getattr(frappe.local, "db", None):
                    frappe.connect()
                frappe.db.delete("Notification Log", {{"document_name": slug}})
                frappe.db.delete("Staff Alert Event", {{"reference_name": slug}})
                frappe.db.delete("Email Queue Recipient", {{"recipient": email}})
                for doctype, key in (("Membership Application Door", "door"), ("Membership Dues Schedule", "template"), ("User", "user")):
                    if made.get(key):
                        frappe.delete_doc(doctype, made[key], force=True)
                frappe.db.commit()
                frappe.destroy()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=240,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        out = json.loads(next(l for l in result.stdout.splitlines() if l.startswith("RESULT"))[len("RESULT") :])
        self.assertEqual(out["statuses"], [200, 200, 200])
        self.assertTrue(out["page_says_unavailable"], "control: the GET really rendered the unusable door")
        self.assertEqual(len(out["to_user"]), 1, out)
        self.assertEqual(out["to_administrator"], [])
        self.assertIn("is not an active template", out["content"])
        self.assertEqual(len(out["events"]), 1, out)
