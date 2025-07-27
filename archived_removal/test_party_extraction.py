"""
Test API for eBoekhouden party extraction
Whitelisted functions to test party extraction with sample data
"""

import frappe


@frappe.whitelist()
def test_party_extraction_with_samples():
    """Test party extraction with sample Dutch banking descriptions"""

    try:
        from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

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
            {
                "id": "12351",
                "MutatieType": 6,  # Money Paid
                "description": "EBH-Money Paid-12351: Automatische incasso Utilities & More B.V.",
                "amount": 156.78,
                "date": "2025-01-08",
            },
        ]

        results = []
        extractor = EBoekhoudenPartyExtractor("NVV")

        for mutation in test_mutations:
            result = {
                "mutation_id": mutation["id"],
                "type": mutation["MutatieType"],
                "type_name": "Money Received" if mutation["MutatieType"] == 5 else "Money Paid",
                "original_description": mutation["description"],
                "amount": mutation["amount"],
            }

            # Extract party information
            party_info = extractor.extract_party_from_mutation(mutation)

            if party_info:
                result.update(
                    {
                        "party_extracted": True,
                        "party_name": party_info["party_name"],
                        "party_type": party_info["party_type"],
                        "extraction_method": party_info["extraction_method"],
                        "cleaned_description": party_info["cleaned_description"],
                    }
                )
            else:
                result.update(
                    {
                        "party_extracted": False,
                        "party_name": None,
                        "party_type": None,
                        "extraction_method": "none",
                        "cleaned_description": extractor._clean_description(mutation["description"]),
                    }
                )

            results.append(result)

        return {
            "success": True,
            "total_tested": len(test_mutations),
            "extracted_count": len([r for r in results if r["party_extracted"]]),
            "results": results,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_pattern_matching():
    """Test individual pattern matching with various descriptions"""

    try:
        from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

        extractor = EBoekhoudenPartyExtractor("NVV")

        test_descriptions = [
            "Betaling van ABC Company",
            "Huur aan Kantoor Verhuur BV",
            "Contributie van Vereniging Test",
            "Incasso Energiebedrijf Nederland",
            "Payment from International Client Ltd",
            "Transfer to Supplier & Partners B.V.",
            "Ontvangen van Klant Services",
            "Betaald aan Leverancier-Test",
            "EBH-Money Received-123: van Stichting Natuur & Milieu",
            "Overboeking van Donateur Particulier",
            "Automatische incasso Verzekeringmaatschappij Nederland NV",
        ]

        results = []

        for desc in test_descriptions:
            party_name = extractor._extract_party_name_from_description(desc)
            cleaned = extractor._clean_description(desc)
            is_valid = extractor._is_valid_party_name(party_name) if party_name else False

            results.append(
                {
                    "original_description": desc,
                    "cleaned_description": cleaned,
                    "extracted_name": party_name,
                    "is_valid_name": is_valid,
                }
            )

        return {
            "success": True,
            "total_tested": len(test_descriptions),
            "successful_extractions": len([r for r in results if r["extracted_name"]]),
            "valid_extractions": len([r for r in results if r["is_valid_name"]]),
            "results": results,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_party_resolution_simulation():
    """Test party resolution without actually creating parties"""

    try:
        from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

        extractor = EBoekhoudenPartyExtractor("NVV")

        # Test with sample account types
        test_scenarios = [
            {
                "party_info": {
                    "party_name": "Test Supplier BV",
                    "party_type": "Supplier",
                    "relation_id": None,
                },
                "account": "Accounts Payable - NVV",
                "expected_assignment": True,
            },
            {
                "party_info": {"party_name": "Test Customer", "party_type": "Customer", "relation_id": None},
                "account": "Accounts Receivable - NVV",
                "expected_assignment": True,
            },
            {
                "party_info": {"party_name": "Some Company", "party_type": "Supplier", "relation_id": None},
                "account": "Cash - NVV",  # Bank account - no party assignment expected
                "expected_assignment": False,
            },
        ]

        results = []

        for scenario in test_scenarios:
            # Check account type
            account_type = frappe.db.get_value("Account", scenario["account"], "account_type")

            result = {
                "account": scenario["account"],
                "account_type": account_type,
                "party_info": scenario["party_info"],
                "expected_assignment": scenario["expected_assignment"],
            }

            # Simulate party resolution logic
            if account_type in ["Receivable", "Payable"]:
                expected_party_type = "Customer" if account_type == "Receivable" else "Supplier"
                assignment_possible = scenario["party_info"]["party_type"] == expected_party_type
                result["assignment_possible"] = assignment_possible
                result["expected_party_type"] = expected_party_type
            else:
                result["assignment_possible"] = False
                result["expected_party_type"] = None

            results.append(result)

        return {"success": True, "scenarios_tested": len(test_scenarios), "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}
