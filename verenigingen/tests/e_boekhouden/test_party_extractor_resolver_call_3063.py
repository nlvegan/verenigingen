"""#3063: the extractor's relation-id lookup must actually reach EBoekhoudenPartyResolver.

``_resolve_party_by_relation_id`` used to build ``EBoekhoudenPartyResolver(self.company)``
although ``__init__`` takes no argument; the TypeError was swallowed (log + None), so a
mutation carrying a ``relationId`` never resolved a party. The resolver needs no company
(it reads the E-Boekhouden Settings single). Only the REST fetch is stubbed (network
boundary); everything behind it is real.
"""

import itertools
from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor
from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver
from verenigingen.tests.e_boekhouden.test_transaction_utils import _TxUtilsBase


class TestPartyExtractorResolverCall3063(_TxUtilsBase):
    _seq_3063 = itertools.count()

    def _resolve_3063(self, party_type):
        relation_id = f"3063{next(self._seq_3063)}{frappe.generate_hash(length=6)}"
        # Mock justified: network boundary only; None = "API unavailable", so the real
        # resolver takes its provisional-party path.
        with patch.object(EBoekhoudenPartyResolver, "fetch_relation_details", return_value=None):
            return EBoekhoudenPartyExtractor(self.company)._resolve_party_by_relation_id(
                relation_id, party_type
            )

    def test_unknown_customer_relation_resolves_through_the_resolver(self):
        party = self._resolve_3063("Customer")
        self.assertTrue(party, "resolver must be reached and return a party")
        self.assertTrue(frappe.db.exists("Customer", party))

    def test_unknown_supplier_relation_resolves_through_the_resolver(self):
        party = self._resolve_3063("Supplier")
        self.assertTrue(party, "resolver must be reached and return a party")
        self.assertTrue(frappe.db.exists("Supplier", party))

    def test_api_success_creates_the_party_with_the_api_name_and_relation_code(self):
        relation_id = f"3063{next(self._seq_3063)}{frappe.generate_hash(length=6)}"
        api_name = f"Probe 3063 API {frappe.generate_hash(length=6)} BV"
        details = {"id": relation_id, "name": api_name, "type": "B"}
        # Mock justified: network boundary only (API success branch)
        with patch.object(EBoekhoudenPartyResolver, "fetch_relation_details", return_value=details):
            party = EBoekhoudenPartyExtractor(self.company)._resolve_party_by_relation_id(
                relation_id, "Customer"
            )
        self.assertTrue(party)
        self.assertEqual(frappe.db.get_value("Customer", party, "customer_name"), api_name)
        self.assertEqual(frappe.db.get_value("Customer", party, "eboekhouden_relation_code"), relation_id)
