"""
Real (no-mock) unit tests for the SEPA structured-data parser.

These feed genuine MT940 :86: structured-tag strings (modelled on Dutch/European
bank output) through the real parser and assert each field/branch is extracted
correctly. The module is pure logic (regex parsing + a salutation trie); the only
"input" is realistic bank text, exactly the data these functions parse in
production. No business logic is mocked.

Covers verenigingen/verenigingen_payments/utils/sepa_parser.py:
    - sanitize_party_name
    - is_placeholder_value
    - SalutationTrie / extract_salutation
    - parse_sepa_structured_data (CNTP/REMI/EREF/MREF/CREF/CRED/TRCD/SVWZ/ABWA
      and the alternative /NAME/, /IBAN/, /BIC/ formats)
    - extract_sepa_from_mt940_transaction
    - get_counterparty_from_sepa
    - get_description_from_sepa
"""

import unittest

from verenigingen.verenigingen_payments.utils.sepa_parser import (
    MAX_PARTY_NAME_LENGTH,
    MAX_SEPA_INPUT_LENGTH,
    SalutationTrie,
    extract_salutation,
    extract_sepa_from_mt940_transaction,
    get_counterparty_from_sepa,
    get_description_from_sepa,
    is_placeholder_value,
    parse_sepa_structured_data,
    sanitize_party_name,
)


class TestSanitizePartyName(unittest.TestCase):
    """sanitize_party_name - cleaning raw bank-statement names."""

    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_party_name(""), "")

    def test_none_returns_none(self):
        # Falsy guard returns the value unchanged.
        self.assertIsNone(sanitize_party_name(None))

    def test_plain_name_unchanged(self):
        self.assertEqual(sanitize_party_name("Jan de Vries"), "Jan de Vries")

    def test_accented_dutch_name_preserved(self):
        # Accented BMP chars must survive (Dutch/European names).
        self.assertEqual(sanitize_party_name("José Müller"), "José Müller")

    def test_control_characters_removed(self):
        self.assertEqual(sanitize_party_name("Jan\x00\x07de\x1fVries"), "JandeVries")

    def test_emoji_removed(self):
        # Non-BMP characters (emoji) are stripped.
        self.assertEqual(sanitize_party_name("Jan \U0001F600 Vries"), "Jan Vries")

    def test_whitespace_collapsed(self):
        self.assertEqual(sanitize_party_name("Jan    de\t\t Vries"), "Jan de Vries")

    def test_leading_trailing_whitespace_stripped(self):
        self.assertEqual(sanitize_party_name("   Jan de Vries   "), "Jan de Vries")

    def test_truncation_to_max_length(self):
        long_name = "A" * (MAX_PARTY_NAME_LENGTH + 50)
        result = sanitize_party_name(long_name)
        self.assertEqual(len(result), MAX_PARTY_NAME_LENGTH)

    def test_truncation_then_strip(self):
        # Truncation may leave trailing whitespace that gets stripped.
        long_name = "A" * (MAX_PARTY_NAME_LENGTH - 1) + " " + "B" * 10
        result = sanitize_party_name(long_name)
        self.assertLessEqual(len(result), MAX_PARTY_NAME_LENGTH)
        self.assertFalse(result.endswith(" "))


class TestIsPlaceholderValue(unittest.TestCase):
    """is_placeholder_value - detecting SEPA 'empty' sentinels."""

    def test_empty_string_is_placeholder(self):
        self.assertTrue(is_placeholder_value(""))

    def test_none_is_placeholder(self):
        self.assertTrue(is_placeholder_value(None))

    def test_nonref_is_placeholder(self):
        self.assertTrue(is_placeholder_value("NONREF"))

    def test_case_insensitive(self):
        self.assertTrue(is_placeholder_value("nonref"))
        self.assertTrue(is_placeholder_value("NotProvided"))

    def test_whitespace_padded_placeholder(self):
        self.assertTrue(is_placeholder_value("  NOTPROVIDED  "))

    def test_german_placeholder(self):
        self.assertTrue(is_placeholder_value("NICHT ANGEGEBEN"))

    def test_real_value_not_placeholder(self):
        self.assertFalse(is_placeholder_value("Jan de Vries"))


class TestSalutationTrie(unittest.TestCase):
    """SalutationTrie - low-level word-boundary prefix matching."""

    def setUp(self):
        self.trie = SalutationTrie({"hr": "Mr", "mw": "Mrs", "de heer": "Mr"})

    def test_empty_text_no_match(self):
        self.assertEqual(self.trie.match_prefix(""), (None, None, 0))

    def test_simple_match_with_boundary(self):
        key, sal, end = self.trie.match_prefix("hr Jansen")
        self.assertEqual(key, "hr")
        self.assertEqual(sal, "Mr")
        self.assertEqual(end, 2)

    def test_no_match_without_word_boundary(self):
        # "hrm" must NOT match "hr" - no whitespace boundary after the salutation.
        self.assertEqual(self.trie.match_prefix("hrmpff Jansen"), (None, None, 0))

    def test_longest_match_preferred(self):
        # "de heer" should win over a hypothetical shorter prefix.
        key, sal, end = self.trie.match_prefix("de heer Jansen")
        self.assertEqual(key, "de heer")
        self.assertEqual(end, 7)

    def test_no_match_when_salutation_is_entire_text(self):
        # No trailing whitespace -> the word-boundary check fails.
        self.assertEqual(self.trie.match_prefix("hr"), (None, None, 0))


class TestExtractSalutation(unittest.TestCase):
    """extract_salutation - splitting a Dutch salutation off a name."""

    def test_empty_name(self):
        self.assertEqual(extract_salutation(""), (None, ""))

    def test_no_salutation(self):
        self.assertEqual(extract_salutation("Jan de Vries"), (None, "Jan de Vries"))

    def test_hr_maps_to_mr(self):
        sal, name = extract_salutation("Hr M E J Eggermont")
        self.assertEqual(sal, "Mr")
        self.assertEqual(name, "M E J Eggermont")

    def test_mw_maps_to_mrs(self):
        sal, name = extract_salutation("Mw S Bostelaar")
        self.assertEqual(sal, "Mrs")
        self.assertEqual(name, "S Bostelaar")

    def test_case_insensitive(self):
        sal, name = extract_salutation("DHR Pietersen")
        self.assertEqual(sal, "Mr")
        self.assertEqual(name, "Pietersen")

    def test_familie_maps_to_none_salutation_but_strips(self):
        # "fam" is a known salutation key with value None: it's stripped but
        # produces no ERPNext salutation.
        sal, name = extract_salutation("fam Jansen")
        self.assertIsNone(sal)
        self.assertEqual(name, "Jansen")

    def test_academic_title(self):
        sal, name = extract_salutation("dr. Smit")
        self.assertEqual(sal, "Dr")
        self.assertEqual(name, "Smit")

    def test_salutation_substring_not_falsely_matched(self):
        # "Hribar" starts with "hr" but has no word boundary -> not a salutation.
        sal, name = extract_salutation("Hribar Jansen")
        self.assertIsNone(sal)
        self.assertEqual(name, "Hribar Jansen")


class TestParseSepaStructuredData(unittest.TestCase):
    """parse_sepa_structured_data - the core MT940 :86: tag parser."""

    def test_empty_text_returns_default_dict(self):
        result = parse_sepa_structured_data("")
        # All keys present, all empty.
        self.assertEqual(result["counterparty_name"], "")
        self.assertEqual(result["counterparty_account"], "")
        self.assertEqual(result["remittance_info"], "")
        self.assertEqual(
            set(result.keys()),
            {
                "counterparty_name",
                "counterparty_salutation",
                "counterparty_account",
                "counterparty_bic",
                "remittance_info",
                "end_to_end_ref",
                "mandate_ref",
                "creditor_ref",
                "transaction_code",
                "payment_purpose",
            },
        )

    def test_none_text_returns_default_dict(self):
        result = parse_sepa_structured_data(None)
        self.assertEqual(result["counterparty_name"], "")

    def test_cntp_full_extraction(self):
        text = "/CNTP/NL91ABNA0417164300/ABNANL2A/Jan de Vries/Amsterdam/NL/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_account"], "NL91ABNA0417164300")
        self.assertEqual(result["counterparty_bic"], "ABNANL2A")
        self.assertEqual(result["counterparty_name"], "Jan de Vries")

    def test_cntp_with_salutation(self):
        text = "/CNTP/NL91ABNA0417164300/ABNANL2A/Hr M E J Eggermont/Goes/NL/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_salutation"], "Mr")
        self.assertEqual(result["counterparty_name"], "M E J Eggermont")

    def test_cntp_account_whitespace_removed(self):
        # MT940 wraps long account numbers across lines -> embedded whitespace.
        text = "/CNTP/NL91 ABNA 0417 164300/ABNANL2A/Jan/Amsterdam/NL/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_account"], "NL91ABNA0417164300")

    def test_remi_remittance_info(self):
        text = "/REMI/USTD//Invoice 12345 membership/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["remittance_info"], "Invoice 12345 membership")

    def test_remi_does_not_split_on_dutch_en_of(self):
        # Dutch "e/o" (en/of = and/or) must NOT be treated as a tag boundary.
        text = "/REMI/USTD//Betaling e/o contributie/EREF/REF99"
        result = parse_sepa_structured_data(text)
        self.assertIn("e/o", result["remittance_info"])
        self.assertEqual(result["end_to_end_ref"], "REF99")

    def test_eref_extraction(self):
        result = parse_sepa_structured_data("/EREF/E2E-2024-000123/")
        self.assertEqual(result["end_to_end_ref"], "E2E-2024-000123")

    def test_mref_extraction(self):
        result = parse_sepa_structured_data("/MREF/MNDT-2024-555/")
        self.assertEqual(result["mandate_ref"], "MNDT-2024-555")

    def test_cref_extraction(self):
        result = parse_sepa_structured_data("/CREF/CRED-REF-001/")
        self.assertEqual(result["creditor_ref"], "CRED-REF-001")

    def test_cred_alias_extraction(self):
        # /CRED/ is accepted as an alias for the creditor reference.
        result = parse_sepa_structured_data("/CRED/NL12ZZZ123456780000/")
        self.assertEqual(result["creditor_ref"], "NL12ZZZ123456780000")

    def test_trcd_extraction(self):
        result = parse_sepa_structured_data("/TRCD/00100/")
        self.assertEqual(result["transaction_code"], "00100")

    def test_svwz_payment_purpose(self):
        result = parse_sepa_structured_data("/SVWZ/Mitgliedsbeitrag 2024/")
        self.assertEqual(result["payment_purpose"], "Mitgliedsbeitrag 2024")

    def test_abwa_overrides_counterparty_name(self):
        text = "/CNTP/NL91ABNA0417164300/ABNANL2A/Original Name/Amsterdam/NL//ABWA/Mw Actual Payer/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_name"], "Actual Payer")
        self.assertEqual(result["counterparty_salutation"], "Mrs")

    def test_name_alternative_format(self):
        # /NAME/ only fills counterparty_name when CNTP did not provide one.
        result = parse_sepa_structured_data("/NAME/Pietje Puk/")
        self.assertEqual(result["counterparty_name"], "Pietje Puk")

    def test_iban_alternative_format(self):
        result = parse_sepa_structured_data("/IBAN/NL69INGB0123456789/")
        self.assertEqual(result["counterparty_account"], "NL69INGB0123456789")

    def test_iban_alternative_whitespace_removed(self):
        result = parse_sepa_structured_data("/IBAN/NL69 INGB 0123 456789/")
        self.assertEqual(result["counterparty_account"], "NL69INGB0123456789")

    def test_bic_alternative_format(self):
        result = parse_sepa_structured_data("/BIC/INGBNL2A/")
        self.assertEqual(result["counterparty_bic"], "INGBNL2A")

    def test_name_does_not_override_cntp_name(self):
        # When CNTP already supplied a name, the alternative /NAME/ is ignored.
        text = "/CNTP/NL91ABNA0417164300/ABNANL2A/Primary Name/Amsterdam/NL//NAME/Secondary/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_name"], "Primary Name")

    def test_newlines_normalized_before_parsing(self):
        # MT940 :86: fields wrap at ~65 chars splitting tags; newlines are removed.
        text = "/CNTP/NL91ABNA041716\r\n4300/ABNANL2A/Jan de Vries/Amsterdam/NL/"
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_account"], "NL91ABNA0417164300")
        self.assertEqual(result["counterparty_name"], "Jan de Vries")

    def test_combined_tags(self):
        text = (
            "/CNTP/NL91ABNA0417164300/ABNANL2A/Jan de Vries/Amsterdam/NL/"
            "/REMI/USTD//Contributie 2024/"
            "/EREF/E2E-001/"
            "/MREF/MNDT-001/"
        )
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["counterparty_account"], "NL91ABNA0417164300")
        self.assertEqual(result["counterparty_name"], "Jan de Vries")
        self.assertEqual(result["remittance_info"], "Contributie 2024")
        self.assertEqual(result["end_to_end_ref"], "E2E-001")
        self.assertEqual(result["mandate_ref"], "MNDT-001")

    def test_no_tags_plain_text(self):
        # Free text with no SEPA tags yields all-empty result.
        result = parse_sepa_structured_data("Just a plain bank description")
        self.assertEqual(result["counterparty_name"], "")
        self.assertEqual(result["remittance_info"], "")

    def test_oversized_input_truncated_not_crashing(self):
        # DoS guard truncates to MAX_SEPA_INPUT_LENGTH; tag at start still parses.
        text = "/EREF/REF-START/" + ("X" * (MAX_SEPA_INPUT_LENGTH + 1000))
        result = parse_sepa_structured_data(text)
        self.assertEqual(result["end_to_end_ref"], "REF-START")


class TestExtractSepaFromMt940Transaction(unittest.TestCase):
    """extract_sepa_from_mt940_transaction - combining MT940 .data fields."""

    def test_combines_fields_and_parses(self):
        data = {
            "extra_details": "/CNTP/NL91ABNA0417164300/ABNANL2A/Jan de Vries/Amsterdam/NL/",
            "transaction_details": "/EREF/E2E-001/",
            "purpose": "",
            "description": None,
        }
        result = extract_sepa_from_mt940_transaction(data)
        self.assertEqual(result["counterparty_name"], "Jan de Vries")
        self.assertEqual(result["end_to_end_ref"], "E2E-001")

    def test_empty_data_dict(self):
        result = extract_sepa_from_mt940_transaction({})
        self.assertEqual(result["counterparty_name"], "")

    def test_none_values_handled(self):
        # None field values must not crash the str()/filter joining.
        data = {"extra_details": None, "description": "/MREF/MNDT-9/"}
        result = extract_sepa_from_mt940_transaction(data)
        self.assertEqual(result["mandate_ref"], "MNDT-9")


class TestGetCounterpartyFromSepa(unittest.TestCase):
    """get_counterparty_from_sepa - name/account selection with fallbacks."""

    def test_uses_sepa_values(self):
        sepa = {"counterparty_name": "Jan de Vries", "counterparty_account": "NL91ABNA0417164300"}
        name, account = get_counterparty_from_sepa(sepa)
        self.assertEqual(name, "Jan de Vries")
        self.assertEqual(account, "NL91ABNA0417164300")

    def test_falls_back_when_missing(self):
        name, account = get_counterparty_from_sepa(
            {"counterparty_name": "", "counterparty_account": ""},
            fallback_name="Fallback Co",
            fallback_account="NL00BANK0000000000",
        )
        self.assertEqual(name, "Fallback Co")
        self.assertEqual(account, "NL00BANK0000000000")

    def test_placeholder_name_filtered_to_empty(self):
        name, account = get_counterparty_from_sepa(
            {"counterparty_name": "NONREF", "counterparty_account": "NL91ABNA0417164300"}
        )
        self.assertEqual(name, "")
        self.assertEqual(account, "NL91ABNA0417164300")

    def test_empty_dict_no_fallback(self):
        name, account = get_counterparty_from_sepa({})
        self.assertEqual(name, "")
        self.assertEqual(account, "")


class TestGetDescriptionFromSepa(unittest.TestCase):
    """get_description_from_sepa - preferred description selection."""

    def test_prefers_remittance_info(self):
        sepa = {"remittance_info": "Contributie 2024", "payment_purpose": "Other"}
        self.assertEqual(get_description_from_sepa(sepa), "Contributie 2024")

    def test_falls_back_to_payment_purpose(self):
        sepa = {"remittance_info": "", "payment_purpose": "Mitgliedsbeitrag"}
        self.assertEqual(get_description_from_sepa(sepa), "Mitgliedsbeitrag")

    def test_falls_back_to_provided_description(self):
        sepa = {"remittance_info": "", "payment_purpose": ""}
        self.assertEqual(
            get_description_from_sepa(sepa, fallback_description="Raw bank text"),
            "Raw bank text",
        )

    def test_empty_when_nothing_available(self):
        self.assertEqual(get_description_from_sepa({}), "")


if __name__ == "__main__":
    unittest.main()
