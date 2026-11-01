"""#1922: a standalone insert of a Chapter Board Member row must still provision the seat.

#1672 moved the board role grant from the row's own ``after_insert`` to the Chapter save:
``BoardManager`` queues the volunteer in validate and ``Chapter.on_update`` flushes the role
profile sync. ``frappe.api.v1.create_doc`` (``POST /api/resource/<doctype>``) and
``frappe.api.v2.create_doc`` (``POST /api/v2/document/<doctype>``) do
``frappe.new_doc(doctype, **data).insert()`` with no ``istable`` handling, so a row POSTed
by Administrator never passes through a Chapter save and the seated user got no role.

A row added through a Chapter save never runs the child's ``after_insert`` (Frappe skips
child controllers there), so ``after_insert`` firing means the insert was standalone.

The REST cases make REAL HTTP requests (werkzeug ``Client(frappe.app.application)``) in a
subprocess, as Administrator, authenticated by an API key. The subprocess is a separate DB
connection, so the fixtures and the key are committed (drained/removed in cleanup).
Probe shortcut: the API key is written to Administrator's User row to stand in for a
configured integration.
"""

import json
import os
import subprocess
import sys
import textwrap
from unittest import mock

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"


class TestBoardRowStandaloneInsert1922(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Row1922 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.chapter_role = self._chapter_role_1922()

    def _chapter_role_1922(self):
        name = f"Secretary {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person(self, label):
        email = f"row1922.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Row", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email)

    def _row(self, person):
        return {
            "parent": self.chapter.name,
            "parenttype": "Chapter",
            "parentfield": "board_members",
            "volunteer": person.volunteer,
            "chapter_role": self.chapter_role,
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "email": person.email,
        }

    def _roles(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _create_administrator_api_token(self):
        key, secret = frappe.generate_hash(length=15), frappe.generate_hash(length=15)
        admin = frappe.get_doc("User", "Administrator")
        admin.api_key, admin.api_secret = key, secret
        admin.save()
        frappe.db.commit()

        def _cleanup_api_token():
            frappe.db.set_value("User", "Administrator", "api_key", None, update_modified=False)
            frappe.db.sql("delete from `__Auth` where doctype='User' and name='Administrator' and fieldname='api_secret'")
            frappe.db.commit()

        self.addCleanup(_cleanup_api_token)
        return f"{key}:{secret}"

    def _create_rows_over_http(self, person_v1, person_v2):
        """Return {route: (status, body)} for the two real REST routes."""
        token = self._create_administrator_api_token()
        frappe.db.commit()
        site = frappe.local.site
        script = textwrap.dedent(
            f"""
            import json
            import frappe
            frappe.init(site={site!r})
            frappe.connect()
            frappe.clear_cache()
            frappe.destroy()
            import frappe.app
            from werkzeug.test import Client

            client = Client(frappe.app.application)
            headers = {{"X-Frappe-Site-Name": {site!r}, "Authorization": "token " + {token!r}}}
            out = {{}}
            for route, row in (
                ("/api/resource/Chapter Board Member", {self._row(person_v1)!r}),
                ("/api/v2/document/Chapter Board Member", {self._row(person_v2)!r}),
            ):
                r = client.post(route, json=row, headers=headers)
                out[route] = [r.status_code, r.get_data(as_text=True)[:600]]
            print(json.dumps(out))
            """
        )
        sites_dir = os.path.join(frappe.utils.get_bench_path(), "sites")
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=sites_dir, capture_output=True, text=True, timeout=120
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        frappe.db.commit()  # drop this connection's stale snapshot before reading the rows
        return json.loads(result.stdout.strip().splitlines()[-1])

    # ------------------------------------------------------------------ the bug

    def test_administrator_rest_post_of_a_board_row_provisions_the_seat_on_both_routes(self):
        v1, v2 = self._person("Viaone"), self._person("Viatwo")
        for p in (v1, v2):
            self.assertNotIn(BOARD_ROLE, self._roles(p.user), "control: no role before the POST")

        out = self._create_rows_over_http(v1, v2)

        for route, (status, body) in out.items():
            self.assertEqual(status, 200, f"{route}: {body}")
        for p in (v1, v2):
            self.assertEqual(
                frappe.db.count("Chapter Board Member", {"parent": self.chapter.name, "volunteer": p.volunteer}),
                1,
                "the POSTed row exists",
            )
            self.assertIn(BOARD_ROLE, self._roles(p.user))

    def test_frappe_client_insert_still_provisions_the_seat(self):
        """The already-safe route (appends to the parent and saves it): must keep working."""
        person = self._person("Client")
        frappe.client.insert(doc=json.dumps({"doctype": "Chapter Board Member", **self._row(person)}))
        self.assertIn(BOARD_ROLE, self._roles(person.user))

    # --------------------------------------------- the normal path is unchanged

    def test_chapter_save_syncs_once_and_the_row_hook_does_not_run(self):
        """No double work: a row added through the Chapter save does not run the row's own
        after_insert, so the profile sync runs exactly once for the seated user."""
        from verenigingen.services.member.account.user_role_profile_calculator import (
            sync_user_role_profile,
        )
        from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
            ChapterBoardMember,
        )

        person = self._person("Normal")
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append("board_members", {k: v for k, v in self._row(person).items() if not k.startswith("parent")})

        # Mock justified: wraps= spies on the real calls to count them; behaviour unchanged.
        with mock.patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            wraps=sync_user_role_profile,
        ) as sync, mock.patch.object(
            ChapterBoardMember,
            "_provision_standalone_seat",
            autospec=True,
        ) as standalone:
            chapter.save()

        seat_syncs = [c for c in sync.call_args_list if c.args and c.args[0] == person.user]
        self.assertEqual(len(seat_syncs), 1)
        standalone.assert_not_called()
        self.assertIn(BOARD_ROLE, self._roles(person.user))
