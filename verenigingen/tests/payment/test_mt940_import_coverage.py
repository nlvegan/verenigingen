"""
Additional coverage tests for the MT940 import helpers.

These tests target genuinely-uncovered branches of
``verenigingen/verenigingen_payments/utils/mt940_import.py`` that the existing
``test_mt940_import_integration.py`` and ``test_mt940_parsing.py`` suites do not
exercise, in particular:

    - batch_preload_party_lookups()        : real Member / SEPA Mandate /
                                              Bank Account population + the
                                              bank_account_no indexing branch
    - find_party_by_iban_or_name()         : SEPA-Mandate (Priority 2) and
                                              Bank-Account-party (Priority 3)
                                              tiers, preloaded-lookups paths,
                                              and name-only internal transfer
    - find_own_bank_account_by_reference() : name-match (Priority 2) + empty args
    - extract_sepa_data_enhanced()         : creditor_ref / mref / whitespace
                                              normalisation / placeholder filter
    - get_enhanced_transaction_type()      : booking_text priority, Dutch
                                              booking-code mapping, SEPA
                                              purpose-code fallback
    - clean_description_redundancy()        : IBAN-dedup edge cases
    - create_enhanced_bank_transaction_from_mt940() : TRCD-only description
                                              fallback + SEPA-Mandate party link

Everything runs against REAL fixtures (frappe.new_doc().insert()) and the real
WoLpH/mt940 library. The only "doubles" are lightweight SimpleNamespace objects
standing in for parsed mt940 Transaction objects, used solely to feed pure
helper functions inputs that are awkward to express as full MT940 text.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures import mt940_sample_statements as S
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban
from verenigingen.verenigingen_payments.utils import mt940_import as M


def _iban(account_number):
    """Build a checksum-valid NL test IBAN with a given 10-digit account number.

    Frappe's Bank Account / Member doctypes validate IBAN MOD-97 checksums, so
    fixtures must use real valid IBANs (generate_test_iban computes the
    checksum) rather than hand-typed digit runs.
    """
    return generate_test_iban("RABO", account_number)


def _txn(data):
    """Build a minimal stand-in for a parsed mt940 Transaction.

    The real mt940 Transaction exposes parsed fields via ``.data`` (a dict) and
    an optional ``.sepa`` attribute. The pure extraction/classification helpers
    only read those two, so a SimpleNamespace is a faithful, mock-free double
    for feeding hand-built field combinations the canned MT940 samples don't
    cover.
    """
    ns = SimpleNamespace()
    ns.data = data
    return ns


class TestMT940ExtractSepaEnhanced(EnhancedTestCase):
    """extract_sepa_data_enhanced branches not covered by the sample suite."""

    def test_creditor_ref_and_mandate_from_data_fields(self):
        """creditor_ref / mref / counterparty fall back to the .data dict when
        no structured /CRED//MREF/ tags are present."""
        sd = M.extract_sepa_data_enhanced(
            _txn(
                {
                    "creditor_reference": "CRED-XYZ",
                    "mandate_reference": "MND-001",
                    "counterparty_name": "Acme BV",
                    "purpose": "Factuur 99",
                }
            )
        )
        self.assertEqual(sd["creditor_ref"], "CRED-XYZ")
        self.assertEqual(sd["mref"], "MND-001")
        self.assertEqual(sd["counterparty"], "Acme BV")
        self.assertEqual(sd["svwz"], "Factuur 99")

    def test_whitespace_and_linebreaks_normalised(self):
        """svwz, counterparty and IBAN have embedded MT940 line breaks removed
        and runs of (non-newline) whitespace collapsed.

        Normalisation order is: remove [\\r\\n]+ FIRST (no space inserted), THEN
        collapse remaining \\s+ to a single space. So 'Regel een\\r\\nRegel   twee'
        becomes 'Regel eenRegel twee' (the multiple spaces around 'twee' collapse
        but the line break joins the words with no gap)."""
        sd = M.extract_sepa_data_enhanced(
            _txn(
                {
                    "purpose": "Regel een\r\nRegel   twee",
                    "counterparty_name": "Naam\r\nMet  Breuk",
                    "counterparty_account": "NL44 RABO 0123 4567 89",
                }
            )
        )
        self.assertEqual(sd["svwz"], "Regel eenRegel twee")
        # Line break removed with no inserted space ('NaamMet'); the double space
        # between 'Met' and 'Breuk' collapses to one.
        self.assertEqual(sd["counterparty"], "NaamMet Breuk")
        # IBAN has ALL whitespace stripped (not just collapsed).
        self.assertEqual(sd["counterparty_iban"], "NL44RABO0123456789")

    def test_placeholder_counterparty_blanked(self):
        """A placeholder counterparty (e.g. 'NOTPROVIDED') is filtered to empty."""
        from verenigingen.verenigingen_payments.utils.sepa_parser import is_placeholder_value

        # Sanity-check the helper actually treats this as a placeholder, so the
        # test asserts a real branch rather than an accidental pass.
        self.assertTrue(is_placeholder_value("NOTPROVIDED"))

        sd = M.extract_sepa_data_enhanced(_txn({"counterparty_name": "NOTPROVIDED"}))
        self.assertEqual(sd["counterparty"], "")

    def test_non_iban_account_split_into_account_ref(self):
        """A non-IBAN account number lands in counterparty_account_ref, and the
        iban field is cleared."""
        sd = M.extract_sepa_data_enhanced(_txn({"counterparty_account": "L96981341"}))
        self.assertEqual(sd["counterparty_iban"], "")
        self.assertEqual(sd["counterparty_account_ref"], "L96981341")

    def test_sepa_attribute_used_as_fallback(self):
        """When the mt940 library exposes a .sepa dict, its EREF/SVWZ are used
        if no structured tags / data fields override them."""
        ns = _txn({})
        ns.sepa = {"EREF": "EREF-FROM-LIB", "SVWZ": "Lib purpose", "MREF": "MREF-LIB"}
        sd = M.extract_sepa_data_enhanced(ns)
        self.assertEqual(sd["eref"], "EREF-FROM-LIB")
        self.assertEqual(sd["svwz"], "Lib purpose")
        self.assertEqual(sd["mref"], "MREF-LIB")


class TestMT940TransactionTypeBranches(EnhancedTestCase):
    """get_enhanced_transaction_type priority ladder."""

    def test_booking_text_takes_priority(self):
        """A human-readable booking_text wins over every other classifier and is
        truncated to the ERPNext 50-char field limit."""
        long_text = "Incoming SEPA Credit Transfer From A Very Long Counterparty Name Indeed"
        result = M.get_enhanced_transaction_type(_txn({"booking_text": long_text}))
        self.assertEqual(result, long_text.strip()[:50])
        self.assertLessEqual(len(result), 50)

    def test_dutch_booking_code_mapped(self):
        """A known Dutch booking_key maps to its human-readable description."""
        self.assertEqual(
            M.get_enhanced_transaction_type(_txn({"booking_key": "186"})),
            "Direct Debit",
        )
        # ING-specific 5-digit TRCD code via gv_code alias.
        self.assertEqual(
            M.get_enhanced_transaction_type(_txn({"gv_code": "00370"})),
            "Interne overboeking",
        )

    def test_sepa_purpose_code_classification(self):
        """With no booking text/code, a SEPA purpose code in the SVWZ text drives
        the classification."""
        result = M.get_enhanced_transaction_type(
            _txn({"purpose": "Maandelijkse SALA uitbetaling"})
        )
        self.assertEqual(result, "Salary Payment")

    def test_amount_fallback_incoming_and_outgoing(self):
        """No text, no code, no purpose -> sign of the amount decides direction."""
        self.assertEqual(
            M.get_enhanced_transaction_type(_txn({"amount": SimpleNamespace(amount=42.0)})),
            "Incoming Transfer",
        )
        self.assertEqual(
            M.get_enhanced_transaction_type(_txn({"amount": SimpleNamespace(amount=-5.0)})),
            "Outgoing Transfer",
        )
        # Missing amount object -> treated as 0 -> Outgoing.
        self.assertEqual(
            M.get_enhanced_transaction_type(_txn({})),
            "Outgoing Transfer",
        )


class TestMT940CleanDescriptionRedundancy(EnhancedTestCase):
    """clean_description_redundancy edge cases beyond the sample suite."""

    def test_generic_pattern_requires_dutch_iban(self):
        """The generic prefix matcher only strips when the embedded IBAN is a
        Dutch NL IBAN; a non-NL IBAN prefix is left intact."""
        msg = "Betaling van Someone BE68539007547034 Echt bericht"
        # No counterparty info supplied, so only the generic NL-only pattern runs;
        # a BE IBAN does not match -> description unchanged.
        self.assertEqual(M.clean_description_redundancy(msg, "", ""), msg)

    def test_exact_prefix_match_is_case_insensitive(self):
        """The exact counterparty+IBAN prefix strip ignores case."""
        cleaned = M.clean_description_redundancy(
            "betaling VAN Jan Jansen NL12RABO0123456789 Het bericht",
            "Jan Jansen",
            "NL12RABO0123456789",
        )
        self.assertEqual(cleaned, "Het bericht")

    def test_none_description_returned_unchanged(self):
        self.assertIsNone(M.clean_description_redundancy(None, "X", "NL00BANK0000000000"))


class TestMT940FindOwnBankAccount(EnhancedTestCase):
    """find_own_bank_account_by_reference name-match & empty-args branches."""

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name

    def _make_company_bank_account(self, account_name, bank_account_no):
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        ba = frappe.new_doc("Bank Account")
        ba.account_name = account_name
        ba.bank = get_or_create_unknown_bank()
        ba.company = self.company
        ba.bank_account_no = bank_account_no
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))
        return ba

    def test_empty_args_returns_no_match(self):
        result = M.find_own_bank_account_by_reference(None, None, self.company)
        self.assertFalse(result["is_own_account"])
        self.assertIsNone(result["bank_account"])

    def test_name_match_priority_two(self):
        """When no internal ref matches but the counterparty name matches a
        company Bank Account's account_name, it's flagged as own account."""
        ba = self._make_company_bank_account(f"Spaarrekening {self.uid}", f"REF{self.uid}")
        result = M.find_own_bank_account_by_reference(
            account_ref=None, counterparty_name=f"Spaarrekening {self.uid}", company=self.company
        )
        self.assertTrue(result["is_own_account"])
        self.assertEqual(result["bank_account"], ba.name)

    def test_internal_ref_match_priority_one(self):
        """A bank_account_no match on the internal reference is Priority 1."""
        ba = self._make_company_bank_account(f"Internal {self.uid}", f"L77{self.uid[:6]}")
        result = M.find_own_bank_account_by_reference(
            account_ref=f"L77{self.uid[:6]}", counterparty_name="ignored", company=self.company
        )
        self.assertTrue(result["is_own_account"])
        self.assertEqual(result["bank_account"], ba.name)


class TestMT940FindPartyTiers(EnhancedTestCase):
    """find_party_by_iban_or_name Priority 2 / 3 tiers + preloaded paths."""

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name

    def _make_customer(self, name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = name
        customer.customer_type = "Individual"
        customer.insert()
        self.created_records.append(("Customer", customer.name))
        return customer

    def _make_member_with_customer(self, iban):
        """Create a Member (with linked Customer) and return its STORED iban.

        The Member doctype reformats the IBAN to the spaced display form on save
        (e.g. 'NL36 RABO 4444 4444 44'), so the value the Priority-1 SQL matches
        against is the stored one, not the unspaced input. Returning it lets the
        tier tests exercise a genuine IBAN match.
        """
        member = self.create_test_member(
            first_name="Tier",
            last_name=f"Member{self.uid}",
            email=f"tier.member.{self.uid}@example.com",
            iban=iban,
        )
        customer = self._make_customer(f"Tier Customer {self.uid}")
        frappe.db.set_value("Member", member.name, "customer", customer.name)
        stored_iban = frappe.db.get_value("Member", member.name, "iban")
        return member, customer, stored_iban

    def _make_mandate(self, member_name, iban):
        """Create a SEPA Mandate and return its STORED (spaced) iban."""
        from frappe.utils import today

        mandate = frappe.new_doc("SEPA Mandate")
        mandate.account_holder_name = f"Mandate Holder {self.uid}"
        mandate.iban = iban
        mandate.sign_date = today()
        mandate.member = member_name
        mandate.insert()
        self.created_records.append(("SEPA Mandate", mandate.name))
        return frappe.db.get_value("SEPA Mandate", mandate.name, "iban")

    def _make_party_bank_account(self, iban, party_type, party):
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Party BA {self.uid}"
        ba.bank = get_or_create_unknown_bank()
        ba.iban = iban
        ba.party_type = party_type
        ba.party = party
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))
        return ba

    # -- Priority 2: SEPA Mandate -> Member -> Customer ------------------- #

    def test_sepa_mandate_tier_matches_customer(self):
        """An IBAN that is NOT on the Member record but IS on a SEPA Mandate for
        that member still resolves to the member's Customer (Priority 2)."""
        member, customer, _member_iban = self._make_member_with_customer(_iban("1111111111"))
        mandate_iban = self._make_mandate(member.name, _iban("2222222222"))

        result = M.find_party_by_iban_or_name(
            iban=mandate_iban,
            counterparty_name="ignored for iban match",
            is_incoming=True,
            company=self.company,
        )
        self.assertEqual(result["party_type"], "Customer")
        self.assertEqual(result["party"], customer.name)
        self.assertFalse(result["is_internal_transfer"])

    # -- Priority 3: Bank Account party (no Member/Mandate) --------------- #

    def test_bank_account_party_tier(self):
        """An IBAN linked only via a party-bearing Bank Account resolves to that
        party (Priority 3), independent of direction/party_type guess."""
        iban = _iban("3333333333")
        supplier_customer = self._make_customer(f"BA Party {self.uid}")
        self._make_party_bank_account(iban, "Customer", supplier_customer.name)

        result = M.find_party_by_iban_or_name(
            iban=iban,
            counterparty_name="",
            is_incoming=False,  # would normally guess Supplier; BA wins
            company=self.company,
        )
        self.assertEqual(result["party_type"], "Customer")
        self.assertEqual(result["party"], supplier_customer.name)

    # -- preloaded_lookups path ------------------------------------------ #

    def test_preloaded_member_lookup_used(self):
        """When preloaded_lookups are supplied, the Member tier reads from them
        instead of querying (Priority 1, batch mode)."""
        _, customer, member_iban = self._make_member_with_customer(_iban("4444444444"))
        preloaded = M.batch_preload_party_lookups([member_iban])
        # The preload must have found the member -> customer.
        self.assertIn(member_iban, preloaded["member_by_iban"])
        self.assertEqual(preloaded["member_by_iban"][member_iban]["customer"], customer.name)

        result = M.find_party_by_iban_or_name(
            iban=member_iban,
            counterparty_name="",
            is_incoming=True,
            company=self.company,
            preloaded_lookups=preloaded,
        )
        self.assertEqual(result["party"], customer.name)

    def test_preloaded_mandate_lookup_used(self):
        """Batch mode also resolves via the preloaded SEPA-Mandate tier."""
        member, customer, _member_iban = self._make_member_with_customer(_iban("5555555555"))
        mandate_iban = self._make_mandate(member.name, _iban("6666666666"))

        preloaded = M.batch_preload_party_lookups([mandate_iban])
        self.assertIn(mandate_iban, preloaded["mandate_by_iban"])

        result = M.find_party_by_iban_or_name(
            iban=mandate_iban,
            counterparty_name="",
            is_incoming=True,
            company=self.company,
            preloaded_lookups=preloaded,
        )
        self.assertEqual(result["party"], customer.name)

    # -- name-only internal transfer (lines 312-321) --------------------- #

    def test_name_only_internal_transfer_no_iban(self):
        """With no IBAN and no internal ref, a counterparty NAME that matches a
        company Bank Account is still detected as an internal transfer."""
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        own = frappe.new_doc("Bank Account")
        own.account_name = f"Eigen Spaarrekening {self.uid}"
        own.bank = get_or_create_unknown_bank()
        own.company = self.company
        own.bank_account_no = f"OWNREF{self.uid[:6]}"
        own.insert()
        self.created_records.append(("Bank Account", own.name))

        result = M.find_party_by_iban_or_name(
            iban="",
            counterparty_name=f"Eigen Spaarrekening {self.uid}",
            is_incoming=False,
            internal_account_ref=None,
            company=self.company,
        )
        self.assertTrue(result["is_internal_transfer"])
        self.assertEqual(result["internal_bank_account"], own.name)
        self.assertIsNone(result["party"])


class TestMT940BatchPreload(EnhancedTestCase):
    """batch_preload_party_lookups population + edge cases."""

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name

    def _make_customer(self, name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = name
        customer.customer_type = "Individual"
        customer.insert()
        self.created_records.append(("Customer", customer.name))
        return customer

    def test_only_empty_ibans_returns_empty_structure(self):
        """A list of only blank IBANs short-circuits to empty dicts."""
        result = M.batch_preload_party_lookups(["", None, ""])
        self.assertEqual(result["member_by_iban"], {})
        self.assertEqual(result["mandate_by_iban"], {})
        self.assertEqual(result["bank_account_by_iban"], {})

    def test_member_and_bank_account_populated_together(self):
        """A single batch call populates BOTH member_by_iban and
        bank_account_by_iban for distinct IBANs in one shot."""
        ba_iban = _iban("8888888888")

        member = self.create_test_member(
            first_name="Batch",
            last_name=f"Member{self.uid}",
            email=f"batch.member.{self.uid}@example.com",
            iban=_iban("7777777777"),
        )
        customer = self._make_customer(f"Batch Customer {self.uid}")
        frappe.db.set_value("Member", member.name, "customer", customer.name)
        # Member reformats the IBAN to spaced form on save; match against stored.
        member_iban = frappe.db.get_value("Member", member.name, "iban")

        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        ba_party = self._make_customer(f"BA Party {self.uid}")
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Batch BA {self.uid}"
        ba.bank = get_or_create_unknown_bank()
        ba.iban = ba_iban  # Bank Account stores iban unspaced (as given)
        ba.party_type = "Customer"
        ba.party = ba_party.name
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))

        result = M.batch_preload_party_lookups([member_iban, ba_iban])
        self.assertEqual(result["member_by_iban"][member_iban]["customer"], customer.name)
        self.assertEqual(result["bank_account_by_iban"][ba_iban]["party"], ba_party.name)

    def test_bank_account_no_only_party_is_indexed(self):
        """A party-bearing Bank Account whose IBAN is stored ONLY in
        bank_account_no (not the iban column) must still be resolvable by the
        batch preloader -- the non-batch path matches `bank_account_no = %s OR
        iban = %s`, so batch mode must stay consistent.

        NOTE: this asserts the CORRECT behaviour. See the prod-bug report in the
        task summary: batch_preload_party_lookups()'s SQL selects only
        (iban, party, party_type) and never selects bank_account_no, so the
        `r.get("bank_account_no")` indexing branch is dead and such accounts are
        silently dropped from batch lookups (a real N+1-optimisation regression
        vs. the single-query path).
        """
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        acct_no_iban = "NL99RABO9999999999"
        party = self._make_customer(f"AcctNo Party {self.uid}")
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"AcctNo BA {self.uid}"
        ba.bank = get_or_create_unknown_bank()
        ba.bank_account_no = acct_no_iban  # stored in bank_account_no, NOT iban
        ba.party_type = "Customer"
        ba.party = party.name
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))

        result = M.batch_preload_party_lookups([acct_no_iban])
        # The single-query find_party_by_iban_or_name resolves this account, so
        # the batch preloader is expected to index it too.
        self.assertIn(
            acct_no_iban,
            result["bank_account_by_iban"],
            msg="Bank Account with party IBAN in bank_account_no should be preloaded",
        )


class TestMT940TrcdDescriptionFallback(EnhancedTestCase):
    """create_enhanced_bank_transaction_from_mt940 TRCD-only description path.

    When a transaction has no SVWZ remittance text but carries a /TRCD/<code>/
    booking code in extra_details, the description should fall back to the
    human-readable Dutch booking-code translation (optionally suffixed with the
    counterparty name).
    """

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name
        self.bank_account = self._ensure_bank_account()
        self._cleanup_bank_transactions()

    def _ensure_bank_account(self):
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        iban = "NL02ABNA0123456789"
        existing = frappe.db.get_value("Bank Account", {"bank_account_no": iban}, "name")
        if existing:
            return existing
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"MT940 TRCD Test {self.uid}"
        ba.bank = get_or_create_unknown_bank()
        ba.company = self.company
        ba.bank_account_no = iban
        ba.iban = iban
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))
        return ba.name

    def _cleanup_bank_transactions(self):
        for bt in frappe.get_all(
            "Bank Transaction", filters={"bank_account": self.bank_account}, fields=["name", "docstatus"]
        ):
            doc = frappe.get_doc("Bank Transaction", bt.name)
            if doc.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        self._cleanup_bank_transactions()
        super().tearDown()

    def test_trcd_in_extra_details_translated(self):
        """Unit-level check of the TRCD-translation branch via a hand-built
        transaction whose EXTRA_DETAILS carries the TRCD code -- the field the
        prod fallback actually inspects (mt940_import.py ~line 1109). 00100 ->
        'Inkomende overboeking', suffixed with the counterparty name."""
        ns = _txn(
            {
                "amount": SimpleNamespace(amount=300.0, currency="EUR"),
                "date": None,
                "extra_details": "/TRCD/00100/",
                "counterparty_name": "Stichting Goede Doelen",
            }
        )
        created = M.create_enhanced_bank_transaction_from_mt940(ns, self.bank_account, self.company)
        self.assertTrue(created)
        bt = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["description"],
        )[0]
        self.assertIn("Inkomende overboeking", bt.description)
        self.assertIn("Stichting Goede Doelen", bt.description)

    def test_unknown_trcd_code_uses_raw_extra_details(self):
        """An unrecognised TRCD code is not in DUTCH_BOOKING_CODES, so the raw
        extra_details string is used as the description (the else branch)."""
        ns = _txn(
            {
                "amount": SimpleNamespace(amount=-12.0, currency="EUR"),
                "date": None,
                "extra_details": "/TRCD/99999/",
            }
        )
        created = M.create_enhanced_bank_transaction_from_mt940(ns, self.bank_account, self.company)
        self.assertTrue(created)
        bt = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["description", "withdrawal"],
        )[0]
        self.assertIn("99999", bt.description)
        self.assertEqual(float(bt.withdrawal), 12.0)

    def test_trcd_in_transaction_details_translated_from_library_output(self):
        """End-to-end check on GENUINE library output (the reported prod bug).

        The TRCD_ONLY_DESCRIPTION sample puts /TRCD/00100/ in the SEPA blob that
        the WoLpH/mt940 library parses into the `transaction_details` field (with
        `extra_details` empty). create_enhanced_bank_transaction_from_mt940's
        TRCD-translation fallback must inspect `transaction_details` (where /TRCD/
        canonically lives), not only `extra_details` (the short :61: supplementary
        field), so for real library output the booking code is translated to its
        Dutch description and suffixed with the counterparty name.
        """
        result = M.process_mt940_document(S.TRCD_ONLY_DESCRIPTION, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

        bt = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["description", "deposit"],
        )[0]
        # 00100 -> 'Inkomende overboeking', suffixed with the CNTP counterparty.
        self.assertIn("Inkomende overboeking", bt.description)
        self.assertIn("Stichting Goede Doelen", bt.description)
        self.assertNotEqual(bt.description, M.DEFAULT_TRANSACTION_DESCRIPTION)
        self.assertEqual(float(bt.deposit), 300.00)
