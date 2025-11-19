"""Debug script to fetch mutation 9234 - place in verenigingen/utils/"""
import json

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient


@frappe.whitelist()
def fetch_raw_mutation(mutation_id):
    """Fetch and display raw mutation data from E-Boekhouden REST API"""
    # Get settings
    settings = frappe.get_single("E-Boekhouden Settings")
    client = EBoekhoudenRESTClient(settings.api_url, settings.get_password("api_token"))

    # Fetch mutation
    result = client.get_mutation(int(mutation_id))

    if result.get("success"):
        mutation_data = result.get("data")

        return {
            "success": True,
            "raw_data": mutation_data,
            "key_fields": {
                "id": mutation_data.get("id"),
                "MutatieNr": mutation_data.get("MutatieNr"),
                "amount": mutation_data.get("amount"),
                "bedrag": mutation_data.get("bedrag"),
                "Bedrag": mutation_data.get("Bedrag"),
                "BedragInvoer": mutation_data.get("BedragInvoer"),
                "type": mutation_data.get("type"),
                "Datum": mutation_data.get("Datum"),
                "Omschrijving": mutation_data.get("Omschrijving"),
            },
            "rows": mutation_data.get("Regels", []),
            "row_count": len(mutation_data.get("Regels", [])),
        }
    else:
        return {"success": False, "error": result.get("error")}
