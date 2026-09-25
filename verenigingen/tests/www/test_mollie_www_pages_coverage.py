"""
Coverage tests for the Mollie www portal pages:
- verenigingen/www/mollie_subscription_audit.py
- verenigingen/www/mollie_member_reconciliation.py

Both pages are financial-admin gated. get_context() enforces a battery of
has_permission() checks; the @critical_api whitelisted endpoints additionally
gate on Verenigingen-Staff/Administrator roles (mollie_subscription_audit) or
Member write permission (mollie_member_reconciliation).

The reconciliation/audit data endpoints require a live Mollie API key which the
test site does not have, so those endpoints return a serialized failure
OperationResult (which logs). We assert the failure shape + that the log is the
expected, intentional one (expectErrorLog). The member-field-update endpoint
needs no Mollie connectivity and is driven against real Member records, asserting
the field changes actually persist.

Permission paths use REAL users + roles via set_user(); no business-logic mocking.
External Mollie connectivity is NOT mocked -- we test the real "no key" branch.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.www import mollie_member_reconciliation as mmr, mollie_subscription_audit as msa


class TestMollieWwwPagesCoverage(VereningingenTestCase):
    """Real-data tests for the Mollie audit + reconciliation portal pages."""

    def setUp(self):
        super().setUp()
        # Financial-admin user. System Manager grants the Member / Mollie Settings
        # / Payment Entry / Verenigingen Payments Settings read+write the page
        # gates require, and is also one of MollieWebhookService.ALLOWED_ROLES.
        self.admin_email = f"mollie-admin-{frappe.generate_hash()[:8]}@example.com"
        self.admin_user = self._make_user(
            self.admin_email,
            roles=["Verenigingen Administrator", "System Manager"],
        )

        # A plain member user without financial-admin permissions.
        self.plain_email = f"mollie-plain-{frappe.generate_hash()[:8]}@example.com"
        self.plain_user = self._make_user(self.plain_email, roles=["Verenigingen Member"])

    def _make_user(self, email, roles):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "send_welcome_email": 0,
                    "roles": [{"role": r} for r in roles],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)

        # Post the Rule-5 cap, HIGH/CRITICAL access needs an assigned role PROFILE.
        # Assign the profile matching each role so the admin user clears the page
        # endpoints' gate; Member maps to LOW and stays correctly denied.
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        grant_matching_role_profiles(email, roles)
        return email

    def _grant_chapter_user_permission(self, email, chapter_name):
        """Scope a user to one Chapter via a real User Permission row.

        This is a CONSTRUCTED test scenario, not a state production ever
        creates or leaves in place (#1366). Member does have a custom
        `has_permission` hook (`verenigingen.permissions.has_member_permission`,
        registered in verenigingen/hooks/permissions.py), but Frappe controller
        hooks can only DENY, never grant (frappe/permissions.py:481-498), so its
        Roles.ADMIN_ROLES bypass cannot override a User Permission denial --
        which is why inserting this row still measurably denies
        frappe.has_permission() below for a Verenigingen-Staff-bearing caller.
        The row itself, though, is something this app actively prevents:
        chapter scoping is enforced by permission_query_conditions, not User
        Permission rows (patches v2_1/cleanup_admin_chapter_user_permissions.py
        and v2_2/remove_all_chapter_user_permissions.py removed them app-wide,
        and `cleanup_chapter_user_permissions_for_admins`, a User.on_update
        hook, deletes any Chapter User Permission row on every subsequent User
        save). So the reachable population for the oracle this test proves is
        closed is near-zero today; see #1366. Kept as a code-level regression
        test (and as a hedge against DocPerm or the hook ever changing), not as
        evidence of a live exploit path.
        """
        user_permission = frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": email,
                "allow": "Chapter",
                "for_value": chapter_name,
            }
        )
        user_permission.insert(ignore_permissions=True)
        self.track_doc("User Permission", user_permission.name)

    # ===== mollie_subscription_audit.get_context =====

    def test_audit_get_context_sets_page_flags_for_admin(self):
        # Administrator is a real user that satisfies every has_permission gate
        # (Member / Mollie Settings / Payment Entry read) -- exercises the pass path.
        with self.set_user("Administrator"):
            with self.assertNoErrorLog():
                context = frappe._dict()
                msa.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)

    def test_audit_get_context_denies_plain_user(self):
        """A member without Payment Entry/Mollie Settings read is blocked."""
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.get_context(frappe._dict())

    # ===== mollie_subscription_audit endpoints: role gating =====

    def test_audit_get_default_webhook_url_denied_for_plain_user(self):
        """The @critical_api decorator denies a non-admin before the body runs."""
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.get_default_webhook_url()

    def test_audit_get_active_subscriptions_denied_for_plain_user(self):
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.get_active_subscriptions_with_webhooks()

    def test_audit_bulk_update_denied_for_plain_user(self):
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.bulk_update_subscription_webhooks("[]", "https://x/webhook")

    def test_audit_bulk_update_invalid_json_for_admin(self):
        """Admin passes the role gate but malformed JSON fails cleanly."""
        with self.set_user(self.admin_email):
            result = msa.bulk_update_subscription_webhooks("{not json", "https://x/webhook")
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        # Must be the JSON-format failure, not a permission denial.
        self.assertNotIn("permission_denied", str(result))

    def test_audit_run_audit_no_mollie_key_returns_failure(self):
        """Without a live Mollie key the audit fails gracefully and logs once."""
        with self.set_user(self.admin_email):
            self.expectErrorLog("Subscription Audit Error")
            with self.assertErrorLog("Subscription Audit Error"):
                result = msa.run_audit()
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    def test_audit_run_audit_writes_exactly_one_error_log_row(self):
        """#1130: one failed Mollie call must not fan out into several Error Log rows.

        Before the fix, the single 400 from GET /v2/subscriptions produced FOUR
        rows: http_client's "HTTP Request Failed", error_handler's "Mollie
        api_connection: HTTPError", subscription_audit.py's argument-swapped
        "Subscription Audit", and this endpoint's own "Subscription Audit Error".
        Only the last of those should remain -- it is this endpoint's canonical
        failure log, asserted separately above.
        """
        with self.set_user(self.admin_email):
            self.expectErrorLog("Subscription Audit Error")
            marker = frappe.utils.now_datetime()
            before = {
                r.name
                for r in frappe.get_all("Error Log", filters={"creation": [">=", marker]}, fields=["name"])
            }
            result = msa.run_audit()
            rows = frappe.get_all(
                "Error Log",
                filters={"creation": [">=", marker]},
                fields=["name", "method"],
                order_by="creation asc",
            )
            rows = [r for r in rows if r.name not in before]

        self.assertFalse(result.get("success"))
        titles = [r.method for r in rows]
        self.assertEqual(
            titles,
            ["Subscription Audit Error"],
            f"expected exactly one Error Log row for a failed audit, got: {titles}",
        )

    def test_audit_get_default_webhook_url_admin_path(self):
        """Admin passes the gate; result is a success OR a clean handled failure."""
        with self.set_user(self.admin_email):
            self.expectErrorLog("Failed to get default webhook URL")
            result = msa.get_default_webhook_url()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        if result.get("success"):
            data = result.get("data") or {}
            self.assertIn("mode_label", data)

    # ===== mollie_member_reconciliation.get_context =====

    def test_recon_get_context_sets_page_flags_for_admin(self):
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                context = frappe._dict()
                mmr.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)

    def test_recon_get_context_denies_plain_user(self):
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                mmr.get_context(frappe._dict())

    # ===== get_member_reconciliation_data (no Mollie key) =====

    def test_recon_data_no_mollie_key_returns_failure(self):
        with self.set_user(self.admin_email):
            self.expectErrorLog("Member Reconciliation Error")
            result = mmr.get_member_reconciliation_data()
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    def test_recon_data_key_lookup_failure_writes_exactly_one_error_log_row(self):
        """#1162: one failed API-key lookup must not fan out into two Error Log rows.

        MollieReconciliationService.__init__ builds a
        ``MollieBaseClient(use_backend_api=False)`` to talk to Mollie. Before the fix,
        that call did not pass ``suppress_api_error_log=True``, so when the Live
        Secret Key is unconfigured, ``MollieBaseClient._get_api_key_from_settings()``
        BOTH logged its own "Failed to get Mollie API key" row (argument-swapped --
        because the message has no newline it is not rescued by frappe's swap
        heuristic, so the row recorded no traceback at all) AND re-raised, which this
        page's own outer ``except`` then logged a SECOND time as "Member
        Reconciliation Error". One failure, two rows -- the same amplification shape
        #1145 fixed for the neighbouring subscription-audit page (#1130).

        ``frappe.flags.in_test`` is flipped off for the duration of the call:
        ``MollieBaseClient`` substitutes a dummy key whenever ``in_test`` is set (so
        ~87 other tests don't need real Mollie credentials), which bypasses the real
        key-lookup branch entirely -- the same reason this bug could only be found by
        a bench console invocation, never by ``bench run-tests`` (see #1162).

        The Live Secret Key is explicitly cleared (not just assumed absent) so this
        test is deterministic regardless of what a sibling test in the same shard
        left behind in ``Mollie Settings``.
        """
        from frappe.utils.password import (
            get_decrypted_password,
            remove_encrypted_password,
            set_encrypted_password,
        )

        DT = "Mollie Settings"

        def _set_live_key(value):
            if value:
                set_encrypted_password(DT, DT, value, "live_secret_key")
            else:
                remove_encrypted_password(DT, DT, "live_secret_key")
            # Blank the column too, so get_password() falls through to __Auth.
            frappe.db.set_single_value(DT, "live_secret_key", "", update_modified=False)
            frappe.clear_document_cache(DT, DT)

        orig_live_key = get_decrypted_password(DT, DT, "live_secret_key", raise_exception=False)
        orig_in_test = frappe.flags.in_test
        _set_live_key(None)
        frappe.flags.in_test = False
        try:
            with self.set_user(self.admin_email):
                self.expectErrorLog("Member Reconciliation Error")
                marker = frappe.utils.now_datetime()
                before = {
                    r.name
                    for r in frappe.get_all(
                        "Error Log", filters={"creation": [">=", marker]}, fields=["name"]
                    )
                }
                result = mmr.get_member_reconciliation_data()
                rows = frappe.get_all(
                    "Error Log",
                    filters={"creation": [">=", marker]},
                    fields=["name", "method"],
                    order_by="creation asc",
                )
                rows = [r for r in rows if r.name not in before]
        finally:
            frappe.flags.in_test = orig_in_test
            _set_live_key(orig_live_key)

        self.assertFalse(result.get("success"))
        titles = [r.method for r in rows]
        self.assertEqual(
            titles,
            ["Member Reconciliation Error"],
            f"expected exactly one Error Log row for a failed key lookup, got: {titles}",
        )

    # ===== update_member_mollie_fields (real Member, no Mollie needed) =====

    def _make_member(self):
        member = self.create_test_member(
            first_name="Recon",
            last_name="Member",
            email=f"recon-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1988-03-03",
        )
        return member

    def test_update_member_fields_persists_changes(self):
        """Updating Mollie fields really writes them to the Member record."""
        member = self._make_member()
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(
                    member_id=member.name,
                    mollie_subscription_id="sub_TEST123",
                    subscription_status="active",
                )
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"), msg=result)

        data = result.get("data") or {}
        self.assertIn("mollie_subscription_id", data.get("updated_fields", []))
        self.assertIn("subscription_status", data.get("updated_fields", []))

        # Verify persistence in the DB, not just the return payload.
        member.reload()
        self.assertEqual(member.mollie_subscription_id, "sub_TEST123")
        self.assertEqual(member.subscription_status, "active")

    def test_update_member_fields_clear_subscription_id(self):
        """Passing an empty subscription id clears the field (set to None)."""
        member = self._make_member()
        member.db_set("mollie_subscription_id", "sub_OLD")
        frappe.db.commit()

        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(
                    member_id=member.name,
                    mollie_subscription_id="",  # explicit clear
                )
        self.assertTrue(result.get("success"), msg=result)
        member.reload()
        self.assertIn(member.mollie_subscription_id, (None, ""))

    def test_update_member_fields_no_fields_provided(self):
        """With no updatable values supplied the endpoint reports a clean failure."""
        member = self._make_member()
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(member_id=member.name)
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("No fields", str(result))

    def test_update_member_fields_missing_member_returns_failure(self):
        """A non-existent member id produces a handled failure, WITHOUT reaching
        frappe.get_doc (#1334): existence is checked first via frappe.db.exists,
        so this no longer logs "Member Reconciliation Update Error" -- that log
        only fires from the generic `except Exception` further down, which a
        missing id can no longer reach.
        """
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(
                    member_id="NONEXISTENT-MEMBER-XYZ",
                    subscription_status="active",
                )
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        # Pin the exact refusal (not just success=False): this must be the SAME
        # message the "exists but forbidden" branch returns (#1334), not the old
        # "Unable to update member. Please contact support." from the bare except.
        self.assertEqual(
            result.get("error", {}).get("message"),
            "Insufficient permissions to update this member",
        )

    # ===== #1334: existence oracle =====

    def test_update_member_fields_unauthorized_cannot_distinguish_missing_from_forbidden(self):
        """An unauthorized caller must get the IDENTICAL refusal whether
        member_id is a real Member outside their scope, or doesn't exist at all.

        The attacker must clear the @critical_api security-tier decorator to
        reach this function's body at all. Empirically, on this site, EVERY
        Role Profile that clears CRITICAL (authorization_policy.py's
        ROLE_PROFILE_SECURITY_MAPPING) bundles the "Verenigingen Staff" role,
        so doctype-level Member write is unconditionally granted to any caller
        who can reach this endpoint at all.

        This test's "out of scope" attacker is a CONSTRUCTED scenario, not a
        state that arises in this app today -- see #1366. Member DOES have a
        custom `has_permission` hook (has_member_permission, hooks/permissions.py)
        that grants Roles.ADMIN_ROLES ("Verenigingen Staff" included) full
        access; the User Permission row `_grant_chapter_user_permission` inserts
        still denies write here only because Frappe controller hooks can only
        DENY, never grant, so the ADMIN_ROLES bypass can't override a User
        Permission denial (frappe/permissions.py:481-498). But this app
        deliberately does not use Chapter User Permissions for scoping (it uses
        permission_query_conditions instead) and actively removes any such row
        via `cleanup_chapter_user_permissions_for_admins` (a User.on_update
        hook) plus two historical patches that purged them app-wide. So the
        reachable population for this specific oracle is near-zero today; this
        test proves the CODE-LEVEL mechanism is closed (hygiene + a hedge
        against DocPerm/the hook ever changing), not that it was being
        exploited.
        """
        attacker_email = f"mollie-attacker-{frappe.generate_hash()[:8]}@example.com"
        self._make_user(attacker_email, roles=["Verenigingen National Board Member"])

        allowed_chapter = self.create_test_chapter()
        other_chapter = self.create_test_chapter()
        self._grant_chapter_user_permission(attacker_email, allowed_chapter.name)

        member_out_of_scope = self.create_test_member(current_chapter=other_chapter.name)

        with self.set_user(attacker_email):
            # Sanity/control: doc-level permission genuinely denies this
            # specific, existing, out-of-scope member. Without this, the test
            # below would prove nothing about the oracle -- it would just be
            # comparing two calls that both happen to fail for the same
            # reason (e.g. an unrelated whitelist gate).
            self.assertFalse(
                frappe.has_permission(
                    "Member", "write", frappe.get_doc("Member", member_out_of_scope.name)
                ),
                "test setup is broken: the User Permission does not actually scope this attacker",
            )

            forbidden_result = mmr.update_member_mollie_fields(
                member_id=member_out_of_scope.name, subscription_status="active"
            )
            missing_result = mmr.update_member_mollie_fields(
                member_id="NONEXISTENT-MEMBER-XYZ-1334", subscription_status="active"
            )

        for result in (forbidden_result, missing_result):
            self.assertIsInstance(result, dict)
            self.assertFalse(result.get("success"))

        forbidden_result.pop("timestamp", None)
        missing_result.pop("timestamp", None)
        self.assertEqual(
            forbidden_result,
            missing_result,
            "an out-of-scope existing member and a nonexistent member must refuse identically",
        )

    def test_update_member_fields_owner_admin_still_succeeds(self):
        """Positive control: the #1334 fix must not refuse a genuinely
        authorized caller. The admin user (Roles.ADMIN_ROLES-equivalent here)
        can still write a real member -- proving the reordering didn't turn
        the permission branch into dead code.
        """
        member = self._make_member()
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(
                    member_id=member.name,
                    subscription_status="active",
                )
        self.assertTrue(result.get("success"), msg=result)
