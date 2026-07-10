"""
Real-DB coverage sweep for EBoekhoudenPartyResolver.

The pre-existing test_party_resolver.py exercises the same methods but mocks
``frappe`` wholesale (so its DB-touching assertions never actually hit a
Customer/Supplier table). This module re-tests the DB-touching and pure
branches AGAINST THE REAL DATABASE using EnhancedTestCase: it creates real
Customer/Supplier rows and asserts the persisted fields, drives the real
duplicate-name dedup against seeded clashes, and exercises the real Party
Enrichment Queue doctype.

OUT OF SCOPE (live eBoekhouden HTTP seam; enforcer bans mocking it):
    fetch_relation_details, enrich_provisional_parties, enrich_party,
    resolve_customer/_resolve_party end-to-end (all call fetch_relation_details
    which does a live ``requests.get`` to the eBoekhouden REST API).

Run with:
    cd /home/frappeuser/frappe-bench && bench --site veg11.veganisme.org \
        run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_party_resolver_coverage
"""

import frappe

from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver
from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPartyResolverExtraction(EnhancedTestCase):
    """Pure extraction branches of _extract_party_name_and_type and helpers.

    These are pure (no DB) but the prior mock-based tests never verified the
    real branch interactions; we keep them lean and only cover the branches the
    mock suite leaves on the table (English companyName, supplier fallback
    inside the type extractor, description fallback path, whitespace-only name
    falling through, missing-id final fallback).
    """

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def test_english_company_name_field(self):
        """companyName (English legacy) resolves to Company entity type."""
        name, entity = self.resolver._extract_party_name_and_type(
            {"id": "1", "companyName": "Acme Holdings Ltd"}, "Customer", []
        )
        self.assertEqual(name, "Acme Holdings Ltd")
        self.assertEqual(entity, "Company")

    def test_whitespace_only_name_falls_through_to_fallback(self):
        """A name of only whitespace must not be accepted; falls to final fallback."""
        name, entity = self.resolver._extract_party_name_and_type(
            {"id": "777", "name": "   ", "type": "B"}, "Customer", []
        )
        # whitespace-only name is rejected -> final customer fallback
        self.assertEqual(name, "E-Boekhouden Relation 777")
        self.assertEqual(entity, "Individual")

    def test_first_name_only(self):
        """Only a first name still yields a stripped full name."""
        name, entity = self.resolver._extract_party_name_and_type(
            {"id": "2", "voornaam": "Sander"}, "Customer", []
        )
        self.assertEqual(name, "Sander")
        self.assertEqual(entity, "Individual")

    def test_supplier_fallback_invoked_inside_type_extractor(self):
        """For a Supplier with no name fields, the supplier fallback path runs."""
        # 'company' is one of the supplier fallback name fields
        name, entity = self.resolver._extract_party_name_and_type(
            {"id": "3", "company": "Leverancier BV"}, "Supplier", []
        )
        self.assertEqual(name, "Leverancier BV")
        self.assertEqual(entity, "Company")

    def test_missing_id_uses_unknown_in_fallback(self):
        """Final fallback uses 'Unknown' when there is no id key at all."""
        name, entity = self.resolver._extract_party_name_and_type({}, "Customer", [])
        self.assertEqual(name, "E-Boekhouden Relation Unknown")
        self.assertEqual(entity, "Individual")

    def test_supplier_final_fallback_format(self):
        """Supplier with truly empty data gets the supplier-shaped fallback."""
        name, entity = self.resolver._extract_party_name_and_type({"id": "99"}, "Supplier", [])
        self.assertEqual(name, "Supplier 99 (eBoekhouden)")
        self.assertEqual(entity, "Individual")

    # --- _extract_supplier_fallback_name direct branches ---

    def test_supplier_fallback_address_extraction(self):
        """A street string yields a business-name guess with the eBoekhouden tag."""
        result = self.resolver._extract_supplier_fallback_name(
            {"id": "5", "straat": "Slagerij Van Dijk 12"}, []
        )
        self.assertIsNotNone(result)
        self.assertIn("Slagerij Van Dijk", result)
        self.assertIn("(eBoekhouden)", result)

    def test_supplier_fallback_numeric_address_rejected(self):
        """A purely-numeric address must not become a name."""
        result = self.resolver._extract_supplier_fallback_name({"id": "5", "street": "12345"}, [])
        self.assertIsNone(result)

    def test_supplier_fallback_truncates_company_field_to_50(self):
        """Company-field names are truncated to 50 chars."""
        long_company = "X" * 80
        result = self.resolver._extract_supplier_fallback_name({"id": "5", "naam": long_company}, [])
        self.assertEqual(result, "X" * 50)

    def test_extract_name_from_description_empty_debug_info(self):
        """No debug info -> no description-based name."""
        self.assertIsNone(self.resolver._extract_name_from_description([]))

    def test_extract_name_from_description_no_description_marker(self):
        """Debug strings without 'description' yield None."""
        self.assertIsNone(self.resolver._extract_name_from_description(["some unrelated log line"]))


class TestHandleDuplicateNameRealDB(EnhancedTestCase):
    """_handle_duplicate_name driven against real Customer/Supplier rows."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()
        self._group = resolve_non_group_customer_group()

    def _make_customer(self, name, relation_code):
        """Create a real Customer row with a forced name and relation code."""
        cust = frappe.new_doc("Customer")
        cust.customer_name = name
        cust.customer_type = "Company"
        cust.customer_group = self._group
        cust.territory = "All Territories"
        cust.name = name
        cust.eboekhouden_relation_code = str(relation_code)
        cust.insert(ignore_permissions=True)
        return cust.name

    def test_no_clash_returns_proposed(self):
        """A name that does not exist is returned untouched, not 'already exists'."""
        unique = "Brand New Co " + frappe.generate_hash(length=6)
        final, exists = self.resolver._handle_duplicate_name("Customer", unique, "100", [])
        self.assertEqual(final, unique)
        self.assertFalse(exists)

    def test_same_relation_returns_existing(self):
        """A clash on the SAME relation code returns the existing row directly."""
        name = "Same Relation Co " + frappe.generate_hash(length=6)
        self._make_customer(name, "200")
        final, exists = self.resolver._handle_duplicate_name("Customer", name, "200", [])
        self.assertEqual(final, name)
        self.assertTrue(exists)

    def test_different_relation_gets_unique_suffix(self):
        """A clash on a DIFFERENT relation code produces a (relation_id)-suffixed name."""
        name = "Clash Co " + frappe.generate_hash(length=6)
        self._make_customer(name, "300")
        # Same proposed name, different incoming relation id -> must disambiguate
        final, exists = self.resolver._handle_duplicate_name("Customer", name, "301", [])
        self.assertEqual(final, f"{name[:120]} (301)")
        self.assertFalse(exists)

    def test_unique_suffix_already_taken_returns_existing(self):
        """If the disambiguated name already exists too, return it as already-existing."""
        token = frappe.generate_hash(length=8)
        base = f"Twice Clash {token}"
        incoming_rel = f"R{token}"  # unique relation id avoids collision with seeded row
        self._make_customer(base, "seed-original")  # original (different relation)
        self._make_customer(f"{base[:120]} ({incoming_rel})", "seed-variant")  # variant pre-exists
        final, exists = self.resolver._handle_duplicate_name("Customer", base, incoming_rel, [])
        self.assertEqual(final, f"{base[:120]} ({incoming_rel})")
        self.assertTrue(exists)


class TestCreateProvisionalPartyRealDB(EnhancedTestCase):
    """_create_provisional_party creating real Customer/Supplier rows."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def test_creates_real_provisional_customer(self):
        """A provisional Customer row is persisted with the expected fields."""
        rel = "C" + frappe.generate_hash(length=8)
        with self.assertNoErrorLog():
            name = self.resolver._create_provisional_party("Customer", rel, [])
        self.assertEqual(name, f"E-Boekhouden Customer {rel}")
        self.assertTrue(frappe.db.exists("Customer", name))
        cust = frappe.get_doc("Customer", name)
        self.assertEqual(cust.customer_name, f"E-Boekhouden Customer {rel}")
        self.assertEqual(cust.eboekhouden_relation_code, rel)
        self.assertEqual(cust.territory, "All Territories")
        # group must be a non-group (leaf) node — same one the resolver picks
        self.assertEqual(cust.customer_group, resolve_non_group_customer_group())

    def test_creates_real_provisional_supplier(self):
        """A provisional Supplier row is persisted with the expected name/group."""
        rel = "S" + frappe.generate_hash(length=8)
        with self.assertNoErrorLog():
            name = self.resolver._create_provisional_party("Supplier", rel, [])
        self.assertEqual(name, f"Supplier {rel} (eBoekhouden)")
        self.assertTrue(frappe.db.exists("Supplier", name))
        supp = frappe.get_doc("Supplier", name)
        self.assertEqual(supp.supplier_name, f"Supplier {rel} (eBoekhouden)")
        self.assertEqual(supp.supplier_group, "All Supplier Groups")
        self.assertEqual(supp.eboekhouden_relation_code, rel)

    def test_provisional_idempotent_returns_existing(self):
        """Calling twice for the same relation returns the existing row, no duplicate."""
        rel = "C" + frappe.generate_hash(length=8)
        first = self.resolver._create_provisional_party("Customer", rel, [])
        debug = []
        second = self.resolver._create_provisional_party("Customer", rel, debug)
        self.assertEqual(first, second)
        self.assertTrue(any("already exists" in m for m in debug))


class TestCreatePartyFromRelationRealDB(EnhancedTestCase):
    """_create_party_from_relation creating real parties from API-shaped dicts."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def test_creates_customer_with_contact_and_tax(self):
        """A full relation dict creates a Customer with email/mobile/tax_id set."""
        rel_id = frappe.generate_hash(length=8)
        relation = {
            "id": rel_id,
            "name": "Volledige Klant BV " + frappe.generate_hash(length=4),
            "type": "B",
            "email": "klant@example.org",
            "telefoon": "+31201234567",
            "btwNummer": "NL123456789B01",
        }
        with self.assertNoErrorLog():
            name = self.resolver._create_party_from_relation("Customer", relation, [])
        self.assertTrue(frappe.db.exists("Customer", name))
        cust = frappe.get_doc("Customer", name)
        self.assertEqual(cust.customer_name, relation["name"])
        self.assertEqual(cust.customer_type, "Company")
        self.assertEqual(cust.email_id, "klant@example.org")
        self.assertEqual(cust.mobile_no, "+31201234567")
        self.assertEqual(cust.tax_id, "NL123456789B01")
        self.assertEqual(cust.eboekhouden_relation_code, rel_id)

    def test_creates_supplier_individual_minimal(self):
        """Minimal personal relation creates a Supplier with Individual type."""
        rel_id = frappe.generate_hash(length=8)
        relation = {
            "id": rel_id,
            "voornaam": "Jan",
            "achternaam": "Bakker " + frappe.generate_hash(length=4),
        }
        with self.assertNoErrorLog():
            name = self.resolver._create_party_from_relation("Supplier", relation, [])
        self.assertTrue(frappe.db.exists("Supplier", name))
        supp = frappe.get_doc("Supplier", name)
        self.assertEqual(supp.supplier_type, "Individual")
        self.assertEqual(supp.supplier_group, "All Supplier Groups")
        self.assertEqual(supp.eboekhouden_relation_code, rel_id)

    def test_create_returns_existing_on_same_relation_clash(self):
        """If a Customer with the same name+relation already exists, return it (no insert)."""
        rel_id = frappe.generate_hash(length=8)
        relation = {"id": rel_id, "name": "Dubbele Klant " + frappe.generate_hash(length=4), "type": "B"}
        first = self.resolver._create_party_from_relation("Customer", relation, [])
        # Second call: _handle_duplicate_name sees same relation code -> already_exists
        second = self.resolver._create_party_from_relation("Customer", relation, [])
        self.assertEqual(first, second)


class TestUpdatePartyWithFreshDataRealDB(EnhancedTestCase):
    """_update_party_with_fresh_data against a real provisional Customer."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def test_provisional_customer_gets_real_name(self):
        """A provisional-named Customer is renamed to the better API name and saved."""
        rel = "C" + frappe.generate_hash(length=8)
        prov_name = self.resolver._create_provisional_party("Customer", rel, [])
        # name starts with "E-Boekhouden" -> eligible for update
        relation = {"id": rel, "name": "Echte Naam BV " + frappe.generate_hash(length=4), "type": "B"}
        with self.assertNoErrorLog():
            updated = self.resolver._update_party_with_fresh_data("Customer", prov_name, relation, [])
        self.assertTrue(updated)
        cust = frappe.get_doc("Customer", prov_name)
        self.assertEqual(cust.customer_name, relation["name"])
        self.assertEqual(cust.customer_type, "Company")

    def test_good_name_not_overwritten(self):
        """A Customer that already has a real (non-provisional) name is left untouched."""
        rel_id = frappe.generate_hash(length=8)
        relation = {"id": rel_id, "name": "Goede Naam BV " + frappe.generate_hash(length=4), "type": "B"}
        name = self.resolver._create_party_from_relation("Customer", relation, [])
        # Now attempt to update with a different name; should refuse (name not provisional)
        new_relation = {"id": rel_id, "name": "Andere Naam", "type": "B"}
        debug = []
        updated = self.resolver._update_party_with_fresh_data("Customer", name, new_relation, debug)
        self.assertFalse(updated)
        self.assertEqual(frappe.db.get_value("Customer", name, "customer_name"), relation["name"])

    def test_update_missing_party_returns_false(self):
        """Updating a non-existent party is caught and returns False."""
        debug = []
        updated = self.resolver._update_party_with_fresh_data(
            "Customer", "Does Not Exist " + frappe.generate_hash(length=6), {"id": "1", "name": "X"}, debug
        )
        self.assertFalse(updated)
        self.assertTrue(any("Failed to update" in m for m in debug))


class TestEnrichmentQueueRealDB(EnhancedTestCase):
    """add_to_enrichment_queue against the real Party Enrichment Queue doctype."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def test_adds_real_queue_entry(self):
        """A queue entry is created with the expected fields."""
        rel = frappe.generate_hash(length=8)
        prov = self.resolver._create_provisional_party("Customer", rel, [])
        with self.assertNoErrorLog():
            qname = self.resolver.add_to_enrichment_queue("Customer", prov, rel, [])
        self.assertTrue(frappe.db.exists("Party Enrichment Queue", qname))
        entry = frappe.get_doc("Party Enrichment Queue", qname)
        self.assertEqual(entry.party_doctype, "Customer")
        self.assertEqual(entry.party_name, prov)
        self.assertEqual(entry.eboekhouden_relation_id, rel)
        self.assertEqual(entry.status, "Pending")
        self.assertEqual(entry.priority, "High")

    def test_does_not_duplicate_pending_entry(self):
        """A second add for the same pending party returns the existing entry."""
        rel = frappe.generate_hash(length=8)
        prov = self.resolver._create_provisional_party("Customer", rel, [])
        first = self.resolver.add_to_enrichment_queue("Customer", prov, rel, [])
        debug = []
        second = self.resolver.add_to_enrichment_queue("Customer", prov, rel, debug)
        self.assertEqual(first, second)
        self.assertTrue(any("already in enrichment queue" in m for m in debug))


class TestGetDefaultPartyRealDB(EnhancedTestCase):
    """_get_default_party must always throw (generic creation disabled)."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def test_customer_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.resolver._get_default_party("Customer")

    def test_supplier_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.resolver._get_default_party("Supplier")


class TestAddPartyAddressRealDB(EnhancedTestCase):
    """_add_party_address creates and links a real Address from relation data."""

    def setUp(self):
        super().setUp()
        self.resolver = EBoekhoudenPartyResolver()

    def _linked_addresses(self, doctype, name):
        return frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": doctype, "link_name": name, "parenttype": "Address"},
            pluck="parent",
        )

    def test_add_party_address_creates_linked_address(self):
        """Relation address fields (adres/postcode/plaats) create a linked Address."""
        rel = frappe.generate_hash(length=8)
        name = self.resolver._create_provisional_party("Customer", rel, [])
        party = frappe.get_doc("Customer", name)
        debug = []
        self.resolver._add_party_address(
            party, {"adres": "Keizersgracht 123", "postcode": "1015 CJ", "plaats": "Amsterdam"}, debug
        )
        linked = self._linked_addresses("Customer", name)
        self.assertEqual(len(linked), 1)
        addr = frappe.get_doc("Address", linked[0])
        self.assertEqual(addr.address_line1, "Keizersgracht 123")
        self.assertEqual(addr.city, "Amsterdam")
        self.assertEqual(addr.pincode, "1015 CJ")
        self.assertTrue(any("Created address" in m for m in debug))

    def test_add_party_address_no_data_is_noop(self):
        """Empty address fields create no Address and log the skip."""
        rel = frappe.generate_hash(length=8)
        name = self.resolver._create_provisional_party("Customer", rel, [])
        party = frappe.get_doc("Customer", name)
        debug = []
        self.resolver._add_party_address(party, {"adres": "", "plaats": ""}, debug)
        self.assertEqual(self._linked_addresses("Customer", name), [])
        self.assertTrue(any("No usable address" in m for m in debug))

    def test_legacy_supplier_wrapper_creates_address(self):
        """add_supplier_address delegates to _add_party_address and creates the Address."""
        rel = frappe.generate_hash(length=8)
        name = self.resolver._create_provisional_party("Supplier", rel, [])
        supplier = frappe.get_doc("Supplier", name)
        self.resolver.add_supplier_address(supplier, {"adres": "Damrak 1", "plaats": "Amsterdam"}, [])
        self.assertEqual(len(self._linked_addresses("Supplier", name)), 1)
