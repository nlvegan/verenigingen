"""process_member_post_creation is not client-reachable (#2232).

It carried a bare @frappe.whitelist() (no security tier, no Member permission check), so any
logged-in user could POST /api/method/...process_member_post_creation for ANY member name and
make the app mail that member a welcome message. Its only legitimate caller is the enqueue in
MemberPerformanceOptimizer.create_member_optimized; background jobs are not whitelist-gated,
so the whitelist was never needed.

The attacker below is a plain desk user with no Verenigingen role. The dispatch goes through
frappe.handler.execute_cmd with a real werkzeug POST, the same entry point the web server uses.
"""

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)

CMD = "verenigingen.utils.member_performance_optimizer.process_member_post_creation"


class TestPostCreationNotClientReachable2232(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = 1
        config.save()
        configure_notification_key("member_activated", 1, 0)
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)
        self.victim = self.create_test_member()
        self.attacker = self.create_test_user("attacker-2232@example.com", roles=[])

    def _queued_for_victim(self):
        return set(
            frappe.get_all(
                "Email Queue",
                filters={"reference_doctype": "Member", "reference_name": self.victim.name},
                pluck="name",
            )
        )

    def _post_as(self, user):
        args = {"member_name": self.victim.name}
        env = EnvironBuilder(path=f"/api/method/{CMD}", data=args, method="POST").get_environ()
        original = frappe.session.user
        frappe.set_user(user)
        frappe.local.request = Request(env)
        frappe.local.form_dict = frappe._dict(args)
        frappe.local.response = frappe._dict()
        try:
            frappe.handler.execute_cmd(CMD)
        finally:
            frappe.set_user(original)

    def test_plain_user_cannot_trigger_welcome_mail_for_another_member(self):
        before = self._queued_for_victim()
        with self.assertRaises(frappe.PermissionError):
            self._post_as(self.attacker.name)
        self.assertEqual(self._queued_for_victim(), before, "no mail may be queued for the victim")

    def test_the_function_is_not_whitelisted(self):
        from verenigingen.utils import member_performance_optimizer as m

        self.assertNotIn(m.process_member_post_creation, frappe.whitelisted)

    def test_the_enqueue_target_still_exists_and_is_importable_by_path(self):
        """Control: dropping the whitelist must not break the background job's dotted path."""
        self.assertTrue(callable(frappe.get_attr(CMD)))
