"""
Debug Helper Functions for E-Boekhouden Integration

This module provides utility functions for debugging and troubleshooting
E-Boekhouden API integration issues.
"""

import json
from typing import Any, Dict, Optional

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient
from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def fetch_raw_mutation_data(mutation_id: int) -> Dict[str, Any]:
    """
    Fetch raw mutation data from E-Boekhouden REST API for debugging purposes.

    This function retrieves the unprocessed mutation data directly from the
    E-Boekhouden API to help diagnose import issues and understand the API
    response structure.

    **Security Note**: This is a development-only function that should not be
    accessible in production environments. It's protected by the @development_only_api
    decorator which restricts access based on site configuration.

    Args:
        mutation_id: The E-Boekhouden mutation ID to fetch

    Returns:
        Dictionary containing:
        - success: Boolean indicating if fetch was successful
        - mutation_id: The requested mutation ID
        - raw_data: Complete unprocessed mutation data from API
        - key_fields: Extracted key fields for quick reference
        - row_count: Number of rows in the mutation
        - rows: List of row data
        - error: Error message if fetch failed

    Example:
        >>> result = fetch_raw_mutation_data(9234)
        >>> print(result['raw_data'])
        {
            "id": 9234,
            "type": 7,
            "date": "2019-12-31",
            "rows": [...]
        }

    Usage in Frappe Desk:
        Can be called from the browser console or custom scripts:
        ```javascript
        frappe.call({
            method: 'verenigingen.e_boekhouden.utils.debug_helpers.fetch_raw_mutation_data',
            args: { mutation_id: 9234 },
            callback: (r) => console.log(r.message)
        });
        ```
    """
    try:
        # Initialize REST client (auto-loads settings)
        client = EBoekhoudenRESTClient()

        # Fetch mutation detail from API
        mutation_data = client.get_mutation_detail(int(mutation_id))

        if not mutation_data:
            return {
                "success": False,
                "mutation_id": mutation_id,
                "error": "Mutation not found or API returned no data",
            }

        # Extract key fields for quick reference
        key_fields = {
            "id": mutation_data.get("id"),
            "type": mutation_data.get("type"),
            "date": mutation_data.get("date"),
            "description": mutation_data.get("description"),
            "ledgerId": mutation_data.get("ledgerId"),
            "relationId": mutation_data.get("relationId"),
            "invoiceNumber": mutation_data.get("invoiceNumber"),
            "inExVat": mutation_data.get("inExVat"),
        }

        # Get rows
        rows = mutation_data.get("rows", [])

        return {
            "success": True,
            "mutation_id": mutation_id,
            "raw_data": mutation_data,
            "key_fields": key_fields,
            "row_count": len(rows),
            "rows": rows,
        }

    except Exception as e:
        frappe.log_error(
            title=f"Debug: Failed to fetch mutation {mutation_id}",
            message=f"Error: {str(e)}\n\n{frappe.get_traceback()}",
        )

        return {
            "success": False,
            "mutation_id": mutation_id,
            "error": str(e),
            "traceback": frappe.get_traceback(),
        }


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def print_mutation_structure(mutation_id: int) -> str:
    """
    Fetch and pretty-print mutation data structure for console debugging.

    This is a convenience wrapper around fetch_raw_mutation_data() that
    formats the output for easy reading in logs or console.

    Args:
        mutation_id: The E-Boekhouden mutation ID to fetch

    Returns:
        Formatted string representation of the mutation data

    Example:
        >>> print(print_mutation_structure(9234))
        ================================================================================
        RAW MUTATION 9234 DATA
        ================================================================================
        {
          "id": 9234,
          "type": 7,
          ...
        }
    """
    result = fetch_raw_mutation_data(mutation_id)

    if not result.get("success"):
        return f"ERROR: {result.get('error')}"

    output = []
    output.append("=" * 80)
    output.append(f"RAW MUTATION {mutation_id} DATA")
    output.append("=" * 80)
    output.append(json.dumps(result["raw_data"], indent=2, ensure_ascii=False))
    output.append("")
    output.append("=" * 80)
    output.append("KEY FIELDS:")
    output.append("=" * 80)

    for key, value in result["key_fields"].items():
        output.append(f"  {key}: {value}")

    output.append("")
    output.append("=" * 80)
    output.append(f"ROWS: {result['row_count']} total")
    output.append("=" * 80)

    for idx, row in enumerate(result["rows"]):
        output.append(f"\nRow {idx + 1}:")
        output.append(json.dumps(row, indent=2, ensure_ascii=False))

    return "\n".join(output)
