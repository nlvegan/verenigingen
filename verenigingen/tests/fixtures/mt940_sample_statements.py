"""
Realistic MT940 bank-statement samples for testing the MT940 import parser.

These are hand-crafted MT940 strings modelled on real Dutch bank output
(ABN AMRO, ING, Rabobank, Triodos). They embed SEPA structured data in the
:86: field (the /CNTP/, /REMI/, /EREF/, /MREF/ tags Dutch banks use) so that
the full mt940 -> extract_sepa_data_enhanced pipeline can be exercised end to
end with NO mocking. The numbers/names are obviously fictitious test data.

Lives under tests/fixtures/ so the test-quality validators skip it.

Each helper returns a tuple ``(mt940_text, expected)`` where ``expected`` is a
dict of the SEPA values the parser should produce. ``parse_first(text)`` is a
convenience that runs the real WoLpH/mt940 library and returns the first
parsed Transaction object.
"""

import base64
import os
import tempfile


def parse_statements(mt940_text):
    """Parse MT940 text with the real mt940 library and return the transactions.

    Writes to a temp .sta file (the library expects a path), parses, then
    deletes the file. Returns a list of mt940.models.Transaction objects.
    """
    import mt940

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as tmp:
        tmp.write(mt940_text)
        path = tmp.name
    try:
        return list(mt940.parse(path))
    finally:
        if os.path.exists(path):
            os.unlink(path)


def parse_first(mt940_text):
    """Parse and return the first transaction object (convenience for tests)."""
    txns = parse_statements(mt940_text)
    return txns[0] if txns else None


def as_base64(mt940_text):
    """Return the statement encoded as base64 (the import API input format)."""
    return base64.b64encode(mt940_text.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# Sample statements
# ---------------------------------------------------------------------------

# A single incoming SEPA credit transfer with full structured data.
SEPA_INCOMING_CREDIT = """ABNANL2A
:20:STATEMENT001
:25:NL02ABNA0123456789
:28C:00001/001
:60F:C231201EUR1000,00
:61:2312011201C150,00NTRFNONREF//BANKREF001
:86:/CNTP/NL44RABO0123456789/RABONL2U/Jan de Vries/Amsterdam/NL//REMI/USTD//Contributie 2024/EREF/INV-2024-0001/
:62F:C231201EUR1150,00
-"""

EXPECTED_SEPA_INCOMING_CREDIT = {
    "eref": "INV-2024-0001",
    "svwz": "Contributie 2024",
    "counterparty": "Jan de Vries",
    "counterparty_iban": "NL44RABO0123456789",
    "is_incoming": True,
    "amount": 150.00,
}


# A single outgoing SEPA direct debit (withdrawal) with mandate reference.
SEPA_OUTGOING_DEBIT = """INGBNL2A
:20:STATEMENT002
:25:NL02ABNA0123456789
:28C:00002/001
:60F:C231202EUR1150,00
:61:2312021202D75,50NDDTNONREF//BANKREF002
:86:/CNTP/NL20INGB0001234567/INGBNL2A/Energie Leverancier BV/Rotterdam/NL//REMI/USTD//Maandnota energie/EREF/E2E-9988/MREF/MNDT-555/
:62F:C231202EUR1074,50
-"""

EXPECTED_SEPA_OUTGOING_DEBIT = {
    "eref": "E2E-9988",
    "mref": "MNDT-555",
    "svwz": "Maandnota energie",
    "counterparty": "Energie Leverancier BV",
    "counterparty_iban": "NL20INGB0001234567",
    "is_incoming": False,
    "amount": -75.50,
}


# Payment whose remittance info redundantly repeats "Betaling van <name> <iban>".
SEPA_REDUNDANT_PREFIX = """ABNANL2A
:20:STATEMENT003
:25:NL02ABNA0123456789
:28C:00003/001
:60F:C231203EUR1074,50
:61:2312031203C25,00NTRFNONREF//BANKREF003
:86:/CNTP/NL96INGB0005119504/INGBNL2A/Hr M E J Eggermont/Utrecht/NL//REMI/USTD//Betaling van M E J Eggermont NL96INGB0005119504 Contributie januari/
:62F:C231203EUR1099,50
-"""


# ING statement using an internal account reference (L + digits) instead of IBAN.
# Used to exercise the internal-transfer/non-IBAN account-ref branch.
ING_INTERNAL_TRANSFER = """INGBNL2A
:20:STATEMENT004
:25:NL02ABNA0123456789
:28C:00004/001
:60F:C231204EUR1099,50
:61:2312041204D500,00NTRFNONREF//BANKREF004
:86:/CNTP/L96981341//Spaarrekening/Amsterdam/NL//REMI/USTD//Naar spaarrekening/TRCD/00370/
:62F:C231204EUR599,50
-"""


# A statement carrying a TRCD booking code but no SVWZ text, so description
# falls back to the translated Dutch booking code.
TRCD_ONLY_DESCRIPTION = """INGBNL2A
:20:STATEMENT005
:25:NL02ABNA0123456789
:28C:00005/001
:60F:C231205EUR599,50
:61:2312051205C300,00NTRFNONREF//BANKREF005
:86:/CNTP/NL80RABO0999888777/RABONL2U/Stichting Goede Doelen/Den Haag/NL//TRCD/00100/
:62F:C231205EUR899,50
-"""


# Multi-transaction statement (3 entries) for batch / count testing.
MULTI_TRANSACTION = """ABNANL2A
:20:STATEMENT006
:25:NL02ABNA0123456789
:28C:00006/001
:60F:C231206EUR899,50
:61:2312061206C100,00NTRFNONREF//BANKREFA
:86:/CNTP/NL44RABO0123456789/RABONL2U/Donor One/Amsterdam/NL//REMI/USTD//Donatie A/EREF/EREF-A/
:61:2312061206C200,00NTRFNONREF//BANKREFB
:86:/CNTP/NL20INGB0001234567/INGBNL2A/Donor Two/Rotterdam/NL//REMI/USTD//Donatie B/EREF/EREF-B/
:61:2312061206D50,00NDDTNONREF//BANKREFC
:86:/CNTP/NL80RABO0999888777/RABONL2U/Supplier Three/Den Haag/NL//REMI/USTD//Kosten C/EREF/EREF-C/
:62F:C231206EUR1149,50
-"""


# Two identical-content entries -> should hash to the same duplicate id.
DUPLICATE_ENTRIES = """ABNANL2A
:20:STATEMENT007
:25:NL02ABNA0123456789
:28C:00007/001
:60F:C231207EUR1149,50
:61:2312071207C42,00NTRFNONREF//SAME
:86:/CNTP/NL44RABO0123456789/RABONL2U/Repeat Donor/Amsterdam/NL//REMI/USTD//Zelfde betaling/EREF/EREF-DUP/
:61:2312071207C42,00NTRFNONREF//SAME
:86:/CNTP/NL44RABO0123456789/RABONL2U/Repeat Donor/Amsterdam/NL//REMI/USTD//Zelfde betaling/EREF/EREF-DUP/
:62F:C231207EUR1233,50
-"""


# Completely malformed content (not MT940 at all) for error-path testing.
GARBAGE_CONTENT = "this is not a valid mt940 file at all\njust some random text\n"
