#!/usr/bin/env python3
"""
Test script for eBoekhouden party extraction
Tests the party extractor with sample Dutch banking descriptions
"""

import os
import sys

# Add the app directory to the Python path
sys.path.append("/home/frappe/frappe-bench/apps/verenigingen")


def test_party_extraction():
    """Test party extraction with sample mutations"""

    # Import after path setup
    from verenigingen.utils.eboekhouden.party_extractor import EBoekhoudenPartyExtractor

    # Sample eBoekhouden mutations with Dutch descriptions
    test_mutations = [
        {
            "id": "12345",
            "MutatieType": 5,  # Money Received
            "description": "Betaling van Stichting Veganisme voor kantoorkosten",
            "amount": 250.00,
            "date": "2025-01-15",
        },
        {
            "id": "12346",
            "MutatieType": 6,  # Money Paid
            "description": "Huur betaald aan Kantoorgebouw BV voor januari",
            "amount": 1200.00,
            "date": "2025-01-01",
        },
        {
            "id": "12347",
            "MutatieType": 5,  # Money Received
            "description": "Contributie ontvangen van Nederlandse Vereniging voor Vegetariërs",
            "amount": 45.00,
            "date": "2025-01-10",
        },
        {
            "id": "12348",
            "MutatieType": 6,  # Money Paid
            "description": "Incasso ABN AMRO Bank voor bankkosten",
            "amount": 12.50,
            "date": "2025-01-05",
        },
        {
            "id": "12349",
            "MutatieType": 6,  # Money Paid
            "description": "Overboeking naar Energieleverancier Nederland BV",
            "amount": 89.45,
            "date": "2025-01-12",
        },
        {
            "id": "12350",
            "MutatieType": 5,  # Money Received
            "description": "Payment from Green Food Company for consulting services",
            "amount": 750.00,
            "date": "2025-01-20",
        },
    ]

    print("=== eBoekhouden Party Extraction Test ===\n")

    # Initialize party extractor
    extractor = EBoekhoudenPartyExtractor("NVV")

    for mutation in test_mutations:
        print(f"Testing Mutation {mutation['id']}:")
        print(
            f"  Type: {mutation['MutatieType']} ({'Money Received' if mutation['MutatieType'] == 5 else 'Money Paid'})"
        )
        print(f"  Description: '{mutation['description']}'")
        print(f"  Amount: €{mutation['amount']}")

        # Extract party information
        party_info = extractor.extract_party_from_mutation(mutation)

        if party_info:
            print(f"  ✅ EXTRACTED PARTY:")
            print(f"     Name: '{party_info['party_name']}'")
            print(f"     Type: {party_info['party_type']}")
            print(f"     Method: {party_info['extraction_method']}")
            print(f"     Cleaned Description: '{party_info['cleaned_description']}'")
        else:
            print(f"  ❌ NO PARTY EXTRACTED")

        print("-" * 50)

    print("\n=== Pattern Testing ===")

    # Test individual pattern matching
    test_descriptions = [
        "Betaling van ABC Company",
        "Huur aan Kantoor Verhuur BV",
        "Contributie van Vereniging Test",
        "Incasso Energiebedrijf Nederland",
        "Payment from International Client Ltd",
        "Transfer to Supplier & Partners B.V.",
        "Ontvangen van Klant Services",
        "Betaald aan Leverancier-Test",
    ]

    print("Testing individual descriptions:")
    for desc in test_descriptions:
        party_name = extractor._extract_party_name_from_description(desc)
        cleaned = extractor._clean_description(desc)

        print(f"  '{desc}'")
        print(f"    → Cleaned: '{cleaned}'")
        print(f"    → Extracted: '{party_name}'")
        print()


if __name__ == "__main__":
    test_party_extraction()
