# Copyright (c) 2025, Foppe de Haan and contributors
# For license information, please see license.txt

"""
Branch-coverage tests for ``verenigingen.services.customer_handling_service``.

These complement ``test_customer_handling_service_integration.py`` by exercising
the previously-uncovered branches: the similar-customer warning paths in
``create_customer_for_member``; the Mollie-linking helpers
(``update_customer_mandate``, ``link_customer_to_mollie``,
``get_customer_mollie_info``, ``validate_customer_setup``); and the
``ensure_donor_customer_exists`` lifecycle.

All tests use a real Frappe database (no business-logic mocking) and run as the
default Administrator user.

FLAGGED for review (see also the session summary): the Mollie-linking helpers
reference Customer fields that do NOT exist on this site's schema:
``mollie_customer_id`` and ``custom_mollie_dues_mandate`` (only
``custom_mollie_customer_id`` exists). ``update_customer_mandate`` filters
``frappe.get_all("Customer", {"mollie_customer_id": ...})`` which raises a
1054 "Unknown column" error, swallowed into an error result -- the method can
never succeed on this schema. None of these helpers have production callers.
The tests below CHARACTERIZE this actual current behaviour rather than assert an
aspirational success the schema cannot deliver.
"""

import frappe

from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCustomerHandlingServiceCoverage(EnhancedTestCase):
    """Cover the Mollie-linking + warning branches of CustomerHandlingService."""

    def setUp(self):
        super().setUp()
        self.service = CustomerHandlingService()
        self._customers = []

    def tearDown(self):
        for name in self._customers:
            try:
                if frappe.db.exists("Customer", name):
                    frappe.delete_doc("Customer", name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _new_customer(self, customer_name):
        """Insert a real leaf-grouped Customer and track it for cleanup."""
        from verenigingen.services.customer_group_resolver import (
            resolve_non_group_customer_group,
        )

        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.customer_group = resolve_non_group_customer_group()
        customer.territory = "All Territories"
        customer.insert()
        self._customers.append(customer.name)
        frappe.db.commit()
        return customer

    # ============================================ create_customer_for_member: warning branches

    def _drop_member_customer(self, member):
        """create_test_member auto-creates a Customer named after the member.
        Delete it outright (and unlink) so it doesn't collide with / pollute the
        similar-name search this test sets up itself."""
        existing = member.customer
        if existing:
            member.db_set("customer", None, update_modified=False)
            member.reload()
            if frappe.db.exists("Customer", existing):
                try:
                    frappe.delete_doc("Customer", existing, force=True)
                except Exception:
                    self._customers.append(existing)
            frappe.db.commit()

    def test_create_customer_exact_name_match_warning_branch_executes(self):
        """Drive the exact-name-match warning branch INSIDE
        create_customer_for_member (suppress_messages=False): an existing Customer
        named exactly like the member's full_name makes the method build the
        ``customer_info`` string and msgprint it, then delegate to the canonical
        creator.

        The delegated insert collides on the Customer PK (= customer_name). The
        downstream retry helper de-duplicates by re-deriving a ' - N' suffix ONLY
        when Selling Settings names Customers by 'Customer Name'; otherwise the
        collision exhausts the retry and raises DuplicateEntryError. We assert the
        warning branch ran (via the exact-match lookup it depends on) and accept
        either downstream outcome, wrapping the call in a savepoint so a poisoned
        insert never leaks past this test.

        NOTE: ``DuplicateEntryError`` is a subclass of ``NameError`` (not
        ``ValidationError``), so the service's re-raise guard misses it and wraps
        it in a ``ServiceError`` via ``handle_error`` -- that is what surfaces."""
        from verenigingen.utils.service_error_handler import ServiceError

        h = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Exact",
            last_name=f"Dup{h}",
            email=f"exact.dup.{h}@test.invalid",
            birth_date="1990-01-01",
        )
        full_name = member.full_name
        self._drop_member_customer(member)
        existing = self._new_customer(full_name)

        # Precondition the warning branch keys off.
        self.assertIsNotNone(self.service.find_exact_customer_match(full_name))

        self.expectErrorLog()
        frappe.db.savepoint("exact_match_branch")
        try:
            created = self.service.create_customer_for_member(member, suppress_messages=False)
        except (ServiceError, frappe.exceptions.DuplicateEntryError):
            # No suffix-dedup on this site: collision surfaced after the warning
            # (wrapped by the service's generic error handler).
            created = None
        finally:
            frappe.db.rollback(save_point="exact_match_branch")

        if created is not None:
            # Dedup path: a distinctly-named Customer was produced.
            self.assertNotEqual(created, existing.name)
        else:
            # No-dedup path: the savepoint rollback must have removed any partially
            # inserted Customer, so the only one with this name is the pre-existing
            # fixture (a regression that silently returned None without raising, or
            # that leaked an orphan row, would trip this).
            same_name = frappe.get_all("Customer", filters={"customer_name": full_name}, pluck="name")
            self.assertEqual(same_name, [existing.name])

    def test_create_customer_similar_but_not_exact_warns(self):
        """A customer whose name CONTAINS the member's full_name as a substring
        (but is not an exact match) hits the 'similar names' warning branch; a new
        customer is then created for the member."""
        h = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Sim",
            last_name=f"{h}",
            email=f"sim.{h}@test.invalid",
            birth_date="1991-02-02",
        )
        self._drop_member_customer(member)

        # check_similar_customers searches Customer.customer_name LIKE %full_name%,
        # so the pre-existing customer must CONTAIN the member's full_name (be a
        # superstring), and must not equal it.
        self._new_customer(f"{member.full_name} Other")

        similar = self.service.check_similar_customers(member.full_name)
        self.assertTrue(similar)
        self.assertIsNone(self.service.find_exact_customer_match(member.full_name))

        created = self.service.create_customer_for_member(member, suppress_messages=False)
        self.assertIsNotNone(created)
        self._customers.append(created)
        self.assertEqual(frappe.db.get_value("Customer", created, "customer_name"), member.full_name)

    def test_create_customer_returns_db_linked_existing_without_member_customer(self):
        """When member.customer is empty but a Customer already carries this
        member in its ``member`` link, the service finds it via the DB constraint
        check, back-links member.customer, and returns the existing name."""
        h = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="DbLink",
            last_name=f"{h}",
            email=f"dblink.{h}@test.invalid",
            birth_date="1989-03-03",
        )
        # Reuse the Customer the factory already linked to this member (the
        # Customer.member column is UNIQUE, so we cannot create a second). Make
        # sure that customer carries the member back-link, then clear
        # member.customer so the in-memory short-circuit is NOT taken and the DB
        # constraint-check branch fires.
        existing_customer = member.customer
        self.assertTrue(existing_customer, "factory should auto-create a customer")
        self._customers.append(existing_customer)
        if not frappe.db.get_value("Customer", existing_customer, "member"):
            frappe.db.set_value("Customer", existing_customer, "member", member.name, update_modified=False)
            frappe.db.commit()
        member.db_set("customer", None, update_modified=False)
        member.reload()
        self.assertFalse(member.customer)

        result = self.service.create_customer_for_member(member, suppress_messages=True)
        self.assertEqual(result, existing_customer)
        # member.customer back-linked in memory via db_set.
        member.reload()
        self.assertEqual(member.customer, existing_customer)

    # ============================================ ensure_donor_customer_exists

    def test_ensure_donor_customer_empty_name_fails(self):
        result = self.service.ensure_donor_customer_exists("")
        self.assertFalse(result["success"])
        self.assertIn("required", result["message"].lower())

    def test_ensure_donor_customer_creates_when_absent(self):
        h = frappe.generate_hash(length=6)
        donor_name = f"Donor Cust {h}"
        result = self.service.ensure_donor_customer_exists(donor_name)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["created"])
        created_name = result["data"]["customer_name"]
        self._customers.append(created_name)
        self.assertTrue(frappe.db.exists("Customer", created_name))
        # Customer group must resolve to a leaf (ERPNext rejects group nodes).
        self.assertEqual(
            frappe.db.get_value(
                "Customer",
                created_name,
                "customer_group",
            )
            and frappe.db.get_value(
                "Customer Group",
                frappe.db.get_value("Customer", created_name, "customer_group"),
                "is_group",
            ),
            0,
        )

    def test_ensure_donor_customer_existing_short_circuits(self):
        """When a Customer with the donor's exact name already exists, the method
        reports created=False without inserting a second record."""
        h = frappe.generate_hash(length=6)
        donor_name = f"Existing Donor {h}"
        self._new_customer(donor_name)
        result = self.service.ensure_donor_customer_exists(donor_name)
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["created"])
        self.assertEqual(result["data"]["customer_name"], donor_name)

    # ============================================ link_customer_to_mollie

    def test_link_customer_to_mollie_no_customer_skips(self):
        result = self.service.link_customer_to_mollie("", {"customer_id": "cst_1"})
        self.assertEqual(result["status"], "skipped")

    def test_link_customer_to_mollie_no_ids_skips(self):
        h = frappe.generate_hash(length=6)
        customer = self._new_customer(f"LinkNoIds {h}")
        result = self.service.link_customer_to_mollie(
            customer.name, {"customer_id": None, "mandate_id": None}
        )
        self.assertEqual(result["status"], "skipped")

    def test_link_customer_to_mollie_sets_existing_customer_id_field(self):
        """custom_mollie_customer_id IS a real field on Customer; linking a
        validly-formatted Mollie id succeeds and persists. (mandate_id targets a
        phantom field guarded by hasattr, so it is silently ignored -- see module
        docstring.)

        NOTE: Customer.validate enforces the Mollie id format
        ``cst_[A-Za-z0-9]{10,14}`` on save, so a malformed id makes save() raise.
        """
        h = frappe.generate_hash(length=12)
        customer = self._new_customer(f"LinkOk {h[:6]}")
        cst_id = f"cst_{h[:12]}"  # valid format: cst_ + 12 alphanumerics
        result = self.service.link_customer_to_mollie(customer.name, {"customer_id": cst_id})
        self.assertEqual(result["status"], "success", msg=result.get("message"))
        self.assertEqual(
            frappe.db.get_value("Customer", customer.name, "custom_mollie_customer_id"),
            cst_id,
        )

    def test_link_customer_to_mollie_idempotent_second_call_skips(self):
        h = frappe.generate_hash(length=12)
        customer = self._new_customer(f"LinkIdem {h[:6]}")
        cst_id = f"cst_{h[:12]}"
        first = self.service.link_customer_to_mollie(customer.name, {"customer_id": cst_id})
        self.assertEqual(first["status"], "success", msg=first.get("message"))
        # Reload-free second call: same value already on the (cached) doc -> skipped.
        second = self.service.link_customer_to_mollie(customer.name, {"customer_id": cst_id})
        self.assertEqual(second["status"], "skipped")

    def test_link_customer_to_mollie_nonexistent_customer_errors(self):
        # frappe.get_doc on a missing Customer raises -> caught -> error status.
        self.expectErrorLog()
        result = self.service.link_customer_to_mollie(
            "NONEXISTENT-CUSTOMER-XYZ", {"customer_id": "cst_abcdefghij"}
        )
        self.assertEqual(result["status"], "error")

    # ============================================ validate_customer_setup

    def test_validate_customer_setup_missing_customer(self):
        result = self.service.validate_customer_setup("NONEXISTENT-CUSTOMER-XYZ")
        self.assertEqual(result["status"], "invalid")

    def test_validate_customer_setup_well_configured_customer(self):
        """A fully-populated customer either validates clean, or only warns about
        the (existing) custom_mollie_customer_id being unset -- never an error,
        and never an 'invalid' missing-field result."""
        h = frappe.generate_hash(length=6)
        customer = self._new_customer(f"Valid Setup {h}")
        result = self.service.validate_customer_setup(customer.name)
        self.assertIn(result["status"], ("valid", "warning"))
        if result["status"] == "warning":
            # The only legitimate warning is the unlinked Mollie customer id.
            self.assertIn("Mollie customer ID", result["message"])

    def test_validate_customer_setup_no_mollie_id_warns(self):
        """A customer with the real custom_mollie_customer_id field present but
        empty produces the 'No Mollie customer ID linked' warning."""
        h = frappe.generate_hash(length=6)
        customer = self._new_customer(f"NoMollie {h}")
        # Field exists and is empty on a fresh customer.
        self.assertFalse(frappe.db.get_value("Customer", customer.name, "custom_mollie_customer_id"))
        result = self.service.validate_customer_setup(customer.name)
        self.assertEqual(result["status"], "warning")
        self.assertIn("Mollie customer ID", result["message"])

    # ============================================ get_customer_mollie_info

    def test_get_customer_mollie_info_missing_customer(self):
        info = self.service.get_customer_mollie_info("NONEXISTENT-CUSTOMER-XYZ")
        self.assertEqual(info, {"customer_id": None, "mandate_id": None})

    def test_get_customer_mollie_info_existing_customer_returns_none_for_phantom_fields(self):
        """get_customer_mollie_info reads ``mollie_customer_id`` and
        ``custom_mollie_dues_mandate`` via getattr -- both are phantom fields on
        this schema, so a real, existing customer yields all-None. This
        CHARACTERIZES the dead-code behaviour (see module docstring)."""
        h = frappe.generate_hash(length=6)
        customer = self._new_customer(f"MollieInfo {h}")
        info = self.service.get_customer_mollie_info(customer.name)
        self.assertEqual(info, {"customer_id": None, "mandate_id": None})

    # ============================================ update_customer_mandate

    def test_update_customer_mandate_missing_args(self):
        result = self.service.update_customer_mandate("", "mdt_1")
        self.assertFalse(result["success"])
        self.assertIn("missing", result["message"].lower())

        result2 = self.service.update_customer_mandate("cst_1", "")
        self.assertFalse(result2["success"])

    def test_update_customer_mandate_phantom_field_query_errors(self):
        """update_customer_mandate filters Customer on the phantom column
        ``mollie_customer_id``; the resulting 1054 OperationalError is swallowed
        into an error result. This CHARACTERIZES the broken/dead method (see
        module docstring) -- it can never locate a customer on this schema."""
        self.expectErrorLog()
        result = self.service.update_customer_mandate("cst_anything", "mdt_anything")
        self.assertFalse(result["success"])
        # Pin the failure to the phantom *column* specifically, so an unrelated
        # swallowed exception (e.g. a broken create_result) can't pass this test.
        errors = " ".join(result.get("errors") or []) + (result.get("error") or "")
        self.assertIn("mollie_customer_id", errors)
