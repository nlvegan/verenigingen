#!/usr/bin/env python3
"""
Analyze remaining fallback logic in the eBoekhouden processing code
"""

import frappe


@frappe.whitelist()
def analyze_remaining_fallbacks():
    """Analyze where fallback logic still exists"""

    fallback_analysis = {
        "memorial_bookings_type_7": {
            "status": "✅ FALLBACKS REMOVED",
            "lines": ["2416-2452"],
            "description": "Removed all fallbacks - now fails explicitly if main ledger mapping not found",
            "change_made": "Replaced fallback logic with explicit error throwing",
        },
        "purchase_invoices_type_1": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["1007-1011", "1044-1070", "1086"],
            "fallbacks_present": [
                "Line 1007: Fallback to generic payable account if specific mapping not found",
                "Line 1047: Fallback account lookup for expense accounts",
                "Line 1070: Fallback to basic item with descriptive name",
                "Line 1086: Fallback to basic item with descriptive name",
            ],
            "should_remove": "❓ NEEDS DECISION - Could expose missing Purchase Invoice mappings",
        },
        "sales_invoices_type_2": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["1243-1247", "1279-1302", "1317"],
            "fallbacks_present": [
                "Line 1243: Fallback to generic receivable account if specific mapping not found",
                "Line 1282: Fallback account lookup for income accounts",
                "Line 1302: Fallback to basic item with descriptive name",
                "Line 1317: Fallback to basic item with descriptive name",
            ],
            "should_remove": "❓ NEEDS DECISION - Could expose missing Sales Invoice mappings",
        },
        "payment_entries_type_3_4": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["1859-1861"],
            "fallbacks_present": ["Line 1860: Fallback to generic bank account"],
            "should_remove": "❓ NEEDS DECISION - Could expose missing bank account mappings",
        },
        "money_transfers_type_5_6": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["3209-3211"],
            "fallbacks_present": ["Line 3211: Fallback to default bank account"],
            "should_remove": "❓ NEEDS DECISION - Could expose missing money transfer mappings",
        },
        "journal_entries_other": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["2612-2631"],
            "fallbacks_present": [
                "Line 2618: Fallback logic for unmapped accounts",
                "Line 2631: Create simple two-line entry as fallback",
            ],
            "should_remove": "❓ NEEDS DECISION - Could expose general journal entry mapping issues",
        },
        "party_creation": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["2921-2925", "3096"],
            "fallbacks_present": [
                "Line 2925: Final fallback to create/use default supplier",
                "Line 3096: Fallback to create/use default customer",
            ],
            "should_remove": "❓ NEEDS DECISION - Could expose missing party mappings",
        },
        "account_defaults": {
            "status": "❌ FALLBACKS REMAIN",
            "lines": ["3356", "3365", "3397", "4933"],
            "fallbacks_present": [
                "Line 3356: Final fallback bank account '1100 - Kas - NVV'",
                "Line 3365: Fallback receivable account '1300 - Debiteuren - NVV'",
                "Line 3397: Fallback payable account '19290 - Te betalen bedragen - NVV'",
                "Line 4933: Capital/equity account as fallback",
            ],
            "should_remove": "❓ NEEDS DECISION - Could expose missing account mappings",
        },
    }

    summary = {
        "total_fallback_areas": len(fallback_analysis),
        "fallbacks_removed": 1,  # Only memorial bookings
        "fallbacks_remaining": len(fallback_analysis) - 1,
        "recommendation": "Consider removing fallbacks systematically to expose real mapping issues",
    }

    return {
        "analysis": fallback_analysis,
        "summary": summary,
        "next_steps": [
            "1. Decide which transaction types should have fallbacks removed",
            "2. Remove fallbacks systematically for each transaction type",
            "3. Test import to see what mapping issues are exposed",
            "4. Fix revealed mapping problems instead of hiding them",
        ],
    }


@frappe.whitelist()
def recommend_fallback_removal_priority():
    """Recommend priority order for removing fallbacks"""

    return {
        "high_priority": {
            "memorial_bookings": "✅ ALREADY DONE - Critical for accurate journal entries",
            "account_defaults": "❌ REMOVE NEXT - Hard-coded account fallbacks hide mapping issues",
            "party_creation": "❌ REMOVE NEXT - Generic parties hide relation mapping issues",
        },
        "medium_priority": {
            "purchase_invoices": "❌ CONSIDER - Could expose supplier/expense account mapping issues",
            "sales_invoices": "❌ CONSIDER - Could expose customer/income account mapping issues",
            "payment_entries": "❌ CONSIDER - Could expose bank account mapping issues",
        },
        "low_priority": {
            "money_transfers": "❌ CONSIDER - Usually have good bank account mappings",
            "journal_entries_other": "❌ CONSIDER - May be needed for complex entries",
        },
        "approach": "Remove fallbacks incrementally and test each transaction type to expose hidden mapping issues",
    }
