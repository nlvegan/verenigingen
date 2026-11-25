"""#2889: the connections-tab RPC must count only what the caller may see.

Real flow: every call goes through `frappe.override_whitelisted_method(...)` +
`frappe.get_attr` + `frappe.call`, the same resolution `frappe/handler.py` performs, so a
broken hook registration reddens these tests (calling the core function directly would
bypass the override on develop AND on the branch).

Probe shortcuts, stated: the Donation -> mandate link and the audit-log row are written
with `db.set_value` / `insert(ignore_permissions=True)`, standing in for whoever fills the
Link field on the form. Users get their roles through `create_test_user_with_roles`.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

CORE_METHOD = "frappe.desk.notifications.get_open_count"


class TestOpenCountPermissionAware2889(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        original_timeout = frappe.db.sql("SELECT @@session.max_statement_time")[0][0]
        self.addCleanup(frappe.db.sql, f"SET SESSION max_statement_time = {int(original_timeout)}")
        self.mandate = self._create_mandate()
        self.other_mandate = self._create_mandate()
        self.donor = self.create_test_donor(donor_name="OpenCount Donor A")
        self.other_donor = self.create_test_donor(donor_name="OpenCount Donor B")
        self.donation = self.create_test_donation(donor=self.donor.name)
        frappe.db.set_value("Donation", self.donation.name, "sepa_mandate", self.mandate.name)
        self.audit = self._create_audit_row(self.mandate.name)

    def _create_mandate(self):
        return frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-OC-{frappe.generate_hash(length=8)}",
                "account_holder_name": "Open Count Holder",
                "iban": "NL91ABNA0417164300",
                "sign_date": frappe.utils.today(),
            }
        ).insert(ignore_permissions=True)

    def _create_audit_row(self, mandate_name):
        row = frappe.get_doc(
            {
                "doctype": "SEPA Operation Audit Log",
                "operation_type": "sepa_mandate_creation",
                "operation_status": "success",
                "timestamp": frappe.utils.now_datetime(),
                "user": "Administrator",
                "sepa_mandate": mandate_name,
            }
        ).insert(ignore_permissions=True)
        return row

    def _user(self, roles):
        email = f"open-count-{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user_with_roles(email=email, roles=roles)
        return email

    def _call(self, user, name, doctype="SEPA Mandate", **kwargs):
        method = frappe.get_attr(frappe.override_whitelisted_method(CORE_METHOD))
        with self.as_user(user):
            return frappe.call(method, doctype=doctype, name=name, **kwargs)

    def _can_read(self, user, doctype, name=None):
        with self.as_user(user):
            return bool(frappe.has_permission(doctype, "read", doc=name))

    def _external(self, result):
        return {d["doctype"]: d for d in result["count"]["external_links_found"]}

    # --- wiring ---------------------------------------------------------------

    CORE_HELPERS = (
        "get_internal_links",
        "has_external_link_field",
        "get_external_link_fieldname",
        "get_external_link_fieldnames",
        "get_dynamic_link_filters",
        "get_child_doctypes_with_field",
        "get_external_links_in_child_tables",
        "get_filters_for",
    )

    def test_core_helpers_the_override_reuses_still_exist(self):
        """Drift guard: an upstream rename must redden this test, not every dashboard."""
        from frappe.desk import notifications

        missing = [n for n in self.CORE_HELPERS if not callable(getattr(notifications, n, None))]
        self.assertEqual(missing, [])

    def test_override_is_registered_and_dispatch_whitelisted(self):
        resolved = frappe.override_whitelisted_method(CORE_METHOD)
        self.assertEqual(
            resolved, "verenigingen.utils.security.permission_aware_open_count.get_open_count"
        )
        frappe.is_whitelisted(frappe.get_attr(resolved))  # raises when not dispatchable

    # --- F1: items= is an oracle over doctypes the viewer cannot read ---------------

    def test_items_the_dashboard_offers_to_nobody_without_read_are_not_probeable(self):
        staff = self._user(["Verenigingen Staff"])
        self.assertTrue(self._can_read(staff, "SEPA Mandate", self.mandate.name))
        self.assertFalse(self._can_read(staff, "Donation"))

        for name in (self.mandate.name, self.other_mandate.name):
            result = self._call(staff, name, items=["Donation"])
            self.assertNotIn("Donation", self._external(result), result)

    def test_control_a_donation_reader_still_gets_the_real_counts(self):
        """Real rows for the wrong behaviour to find: one Donation on `mandate`, none on
        `other_mandate`. Without this the refusal tests above could pass on an empty fixture."""
        for items in (["Donation"], None):
            kwargs = {} if items is None else {"items": items}
            linked = self._external(self._call("Administrator", self.mandate.name, **kwargs))
            unlinked = self._external(self._call("Administrator", self.other_mandate.name, **kwargs))
            self.assertEqual(linked["Donation"]["count"], 1, items)
            self.assertEqual(unlinked["Donation"]["count"], 0, items)

    def test_items_json_string_still_accepted(self):
        result = self._call("Administrator", self.mandate.name, items='["Donation"]')
        self.assertEqual(self._external(result)["Donation"]["count"], 1)

    def test_items_the_dashboard_does_not_offer_are_dropped_even_when_readable(self):
        """Staff may read SEPA Operation Audit Log and one row points at the mandate, but the
        SEPA Mandate dashboard does not offer that doctype, so a caller-supplied item must not
        reach it. (Core returns count 1 here.)"""
        staff = self._user(["Verenigingen Staff"])
        self.assertTrue(self._can_read(staff, "SEPA Operation Audit Log"))

        result = self._call(staff, self.mandate.name, items=["SEPA Operation Audit Log"])
        self.assertEqual(self._external(result), {}, result)

    def test_dropped_items_are_indistinguishable_from_nonexistent_ones(self):
        """forbidden (Donation), not offered (audit log) and nonexistent doctype names all
        answer the same on every channel: response, message_log, Error Log, status."""
        staff = self._user(["Verenigingen Staff"])
        probes = ["Donation", "SEPA Operation Audit Log", "No Such Doctype 2889"]
        seen = []
        for item in probes:
            log_before = len(frappe.local.message_log)
            errors_before = frappe.db.count("Error Log")
            result = self._call(staff, self.mandate.name, items=[item])
            seen.append(
                (
                    result,
                    len(frappe.local.message_log) - log_before,
                    frappe.db.count("Error Log") - errors_before,
                )
            )
        self.assertEqual(seen[0], seen[1], seen)
        self.assertEqual(seen[0], seen[2], seen)
        self.assertEqual(seen[0][0]["count"], {"external_links_found": [], "internal_links_found": []})

    def test_unhashable_or_non_string_items_do_not_crash(self):
        # Only a JSON string can carry non-strings past the dispatch type check.
        items = '["Donation", ["x"], 5, null]'
        result = self._call("Administrator", self.mandate.name, items=items)
        self.assertEqual(list(self._external(result)), ["Donation"])

    # --- F2: User Permissions must narrow the count ---------------------------------

    def _create_user_permission(self, user, donor_name):
        up = frappe.get_doc(
            {"doctype": "User Permission", "user": user, "allow": "Donor", "for_value": donor_name}
        ).insert(ignore_permissions=True)
        self.track_doc("User Permission", up.name)

    def test_user_permission_on_another_donor_hides_the_donation(self):
        restricted = self._user(["Verenigingen Administrator"])
        self._create_user_permission(restricted, self.other_donor.name)
        scoped_in = self._user(["Verenigingen Administrator"])
        self._create_user_permission(scoped_in, self.donor.name)

        # Control with the real row: the viewer scoped to THIS donation's donor still sees it.
        self.assertEqual(
            self._external(self._call(scoped_in, self.mandate.name, items=["Donation"]))["Donation"][
                "count"
            ],
            1,
        )
        for items in (["Donation"], None):
            kwargs = {} if items is None else {"items": items}
            got = self._external(self._call(restricted, self.mandate.name, **kwargs))
            self.assertEqual(got.get("Donation", {}).get("count", 0), 0, (items, got))

    # --- the doctype-level read gate, on an item the dashboard DOES offer -------------

    def test_an_offered_item_the_caller_cannot_read_is_dropped_not_raised(self):
        """Donation's own dashboard offers Payment Entry. A Verenigingen Administrator reads
        Donation but not Payment Entry: the item must vanish (core answers with a count of
        the records via get_all; get_list on it would raise PermissionError)."""
        webhook = self._user(["Verenigingen Administrator"])
        def payment_entry_entry(user):
            result = self._call(user, self.donation.name, doctype="Donation")
            return self._external(result).get("Payment Entry")

        # Control: a reader of both sees the offered Payment Entry entry.
        self.assertIsNotNone(payment_entry_entry("Administrator"))

        self.assertTrue(self._can_read(webhook, "Donation", self.donation.name))
        self.assertFalse(self._can_read(webhook, "Payment Entry"))
        self.assertIsNone(payment_entry_entry(webhook))
