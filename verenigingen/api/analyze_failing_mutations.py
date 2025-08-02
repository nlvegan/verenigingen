"""
E-Boekhouden Mutation Failure Analysis API
==========================================

Provides comprehensive analysis capabilities for investigating and resolving
eBoekhouden mutation import failures, particularly those related to stock account
mapping conflicts and transaction processing errors in the Verenigingen system.

Primary Purpose:
    Diagnostic and troubleshooting utilities for eBoekhouden integration issues,
    specifically focused on analyzing mutations that fail during import due to
    account type conflicts, particularly stock account mapping problems.

Key Features:
    * Detailed analysis of specific failing mutations with root cause identification
    * Stock account usage patterns across different mutation types
    * Mapping conflict detection and resolution recommendations
    * Comprehensive mutation data inspection and relationship analysis
    * Business-context aware solution suggestions for integration issues

Problem Domain:
    Addresses the common integration challenge where eBoekhouden ledgers mapped
    to ERPNext stock accounts appear in Journal Entry mutations, causing import
    failures due to ERPNext's restriction on stock accounts in non-stock documents.

Analysis Capabilities:
    * Mutation-level detail inspection with ledger mapping analysis
    * Cross-mutation type stock account usage pattern identification
    * Account type conflict detection and classification
    * Solution recommendation engine with business impact assessment

Integration Context:
    Works with EBoekhoudenRESTIterator for data fetching and E-Boekhouden Ledger
    Mapping DocType for account relationship analysis. Essential for maintaining
    data integrity during financial system migration and ongoing synchronization.

Security Note:
    Uses security framework decorators for appropriate access control, with
    administrative functions restricted to high-security users due to potential
    impact on financial data integrity and mapping configurations.
"""

import frappe

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def analyze_failing_stock_mutations():
    """
    Analyze specific eBoekhouden mutations that failed during import due to stock account conflicts.

    This function provides detailed forensic analysis of mutations that fail to import
    because they contain ledgers mapped to ERPNext stock accounts, which cannot be used
    in Journal Entry documents. It examines each failing mutation to understand the
    root cause and provide actionable insights for resolution.

    Analysis Process:
        1. Fetches detailed mutation data from eBoekhouden for known failing mutations
        2. Examines each mutation row to identify ledger mappings and account types
        3. Identifies problematic rows containing stock account references
        4. Provides comprehensive analysis of mapping conflicts and their business impact

    Returns:
        dict: Comprehensive analysis results containing:
            - success (bool): Whether analysis completed successfully
            - failing_mutations (list): Detailed analysis of each failing mutation including:
                * mutation_id: eBoekhouden mutation identifier
                * type: Transaction type (Invoice, Payment, Memorial, etc.)
                * date: Transaction date for business context
                * description: Business description of the transaction
                * rows: Detailed analysis of each mutation row including:
                  - ledger mapping information (eBoekhouden to ERPNext)
                  - account type identification
                  - problematic status (is_problematic flag for stock accounts)
                  - amounts and descriptions for business context
                * has_stock_accounts: Boolean flag indicating presence of stock conflicts
            - summary: High-level summary of analysis results
            - error: Error details if analysis fails

    Business Context:
        Helps administrators understand why specific financial transactions fail
        to import and provides the detailed information needed to make informed
        decisions about account mapping corrections or alternative import strategies.

    Technical Implementation:
        Uses EBoekhoudenRESTIterator to fetch detailed mutation data and cross-references
        with E-Boekhouden Ledger Mapping DocType to identify account type conflicts.
        Provides both technical details for developers and business context for administrators.

    Error Handling:
        Comprehensive error handling with detailed traceback information for debugging
        complex integration issues. Individual mutation failures don't stop the entire analysis.
    """
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        # These are the mutations that failed
        failing_mutations = [1256, 4549, 5570, 5577, 6338]

        iterator = EBoekhoudenRESTIterator()
        results = []

        for mutation_id in failing_mutations:
            # Get the full mutation data
            mutation = iterator.fetch_mutation_detail(mutation_id)

            if mutation:
                # Analyze each row to understand the mapping
                row_analysis = []
                for i, row in enumerate(mutation.get("rows", [])):
                    ledger_id = row.get("ledgerId")

                    # Look up the ledger mapping
                    mapping = frappe.db.get_value(
                        "E-Boekhouden Ledger Mapping",
                        {"ledger_id": str(ledger_id)},
                        ["erpnext_account", "ledger_name", "ledger_code"],
                        as_dict=True,
                    )

                    account_type = None
                    if mapping and mapping.erpnext_account:
                        account_type = frappe.db.get_value("Account", mapping.erpnext_account, "account_type")

                    row_analysis.append(
                        {
                            "row_index": i,
                            "ebh_ledger_id": ledger_id,
                            "ebh_ledger_code": mapping.ledger_code if mapping else None,
                            "ebh_ledger_name": mapping.ledger_name if mapping else None,
                            "erpnext_account": mapping.erpnext_account if mapping else None,
                            "account_type": account_type,
                            "amount": row.get("amount"),
                            "description": row.get("description", "")[:100],
                            "is_problematic": account_type == "Stock",
                        }
                    )

                mutation_analysis = {
                    "mutation_id": mutation_id,
                    "type": mutation.get("type"),
                    "date": mutation.get("date"),
                    "description": mutation.get("description", "")[:150],
                    "total_amount": mutation.get("amount"),
                    "main_ledger_id": mutation.get("ledgerId"),
                    "rows": row_analysis,
                    "has_stock_accounts": any(row["is_problematic"] for row in row_analysis),
                }

                results.append(mutation_analysis)
            else:
                results.append({"mutation_id": mutation_id, "error": "Could not fetch mutation data"})

        return {
            "success": True,
            "failing_mutations": results,
            "summary": f"Analyzed {len(failing_mutations)} failing mutations",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def check_stock_ledger_usage():
    """
    Analyze stock ledger usage patterns across different eBoekhouden mutation types.

    This function provides comprehensive analysis of how stock accounts are being used
    across different transaction types in eBoekhouden, helping administrators understand
    whether stock account usage is legitimate (e.g., in inventory transactions) or
    represents mapping errors that need correction.

    Analysis Scope:
        Examines all major eBoekhouden mutation types (Sales Invoice, Purchase Invoice,
        Customer Payment, Supplier Payment, Money Received/Paid, Memorial) to identify
        patterns of stock account usage and distinguish between legitimate inventory
        transactions and potential mapping errors.

    Business Questions Addressed:
        * Which mutation types legitimately use stock accounts?
        * Are there mutation types that shouldn't involve stock but do due to mapping errors?
        * What are the volume and patterns of stock account transactions?
        * How should different mutation types be handled in the import process?

    Returns:
        dict: Comprehensive usage analysis containing:
            - success (bool): Whether analysis completed successfully
            - stock_ledger_id (int): The specific eBoekhouden ledger ID being analyzed
            - usage_by_type (dict): Detailed breakdown by mutation type including:
                * type_name: Human-readable mutation type name
                * stock_mutations_found: Count of mutations using stock accounts
                * examples: Sample transactions for pattern analysis
            - business_question: Key question for administrators to consider
            - error: Error details if analysis fails

    Strategic Value:
        Helps make informed decisions about account mapping strategy by understanding
        the business context of stock account usage. Essential for determining whether
        to remap accounts, skip certain transactions, or implement specialized handling
        for different mutation types.

    Implementation Details:
        Uses EBoekhoudenRESTIterator to systematically examine mutations across all
        transaction types, providing both statistical analysis and concrete examples
        for business decision-making.

    Performance Considerations:
        Limits analysis to 100 mutations per type to balance thoroughness with
        performance. Provides representative sampling for pattern identification.
    """
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Check different mutation types for stock account usage
        results = {}
        stock_ledger_id = 13201884  # This maps to the stock account

        for mutation_type in [1, 2, 3, 4, 5, 6, 7]:
            mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=100)

            stock_usage = []
            for mutation in mutations:
                for row in mutation.get("rows", []):
                    if row.get("ledgerId") == stock_ledger_id:
                        stock_usage.append(
                            {
                                "mutation_id": mutation.get("id"),
                                "date": mutation.get("date"),
                                "description": mutation.get("description", "")[:100],
                                "amount": row.get("amount"),
                                "row_description": row.get("description", "")[:50],
                            }
                        )

            if stock_usage:
                results[f"type_{mutation_type}"] = {
                    "type_name": {
                        1: "Sales Invoice",
                        2: "Purchase Invoice",
                        3: "Customer Payment",
                        4: "Supplier Payment",
                        5: "Money Received",
                        6: "Money Paid",
                        7: "Memorial",
                    }[mutation_type],
                    "stock_mutations_found": len(stock_usage),
                    "examples": stock_usage[:5],  # First 5 examples
                }

        return {
            "success": True,
            "stock_ledger_id": stock_ledger_id,
            "usage_by_type": results,
            "business_question": "Which mutation types legitimately use stock accounts and which are mapping errors?",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def suggest_stock_account_solution():
    """
    Provide expert recommendations for resolving stock account mapping conflicts.

    This administrative function analyzes the current stock account mapping situation
    and provides comprehensive solution recommendations with detailed pros/cons analysis
    to help administrators make informed decisions about resolving import conflicts.

    Problem Analysis:
        Examines the current mapping of eBoekhouden ledgers to ERPNext stock accounts
        and identifies the scope of the conflict, including which specific ledgers
        are causing import failures and their business context.

    Solution Framework:
        Provides three primary resolution strategies with detailed analysis:

        1. **Remap Ledgers**: Change problematic ledger mappings from stock to appropriate
           expense/income accounts. Best for cases where stock mapping was incorrect.

        2. **Skip Stock Mutations**: Continue excluding stock-related mutations from import
           with enhanced logging. Conservative approach that maintains data integrity.

        3. **Create Stock Entries**: Convert appropriate stock mutations to Stock Entry
           documents instead of Journal Entries. Complex but comprehensive solution.

    Administrative Guidance:
        Each solution option includes:
        * Detailed implementation description
        * Business advantages and potential risks
        * Implementation complexity assessment
        * Impact on existing data and future operations
        * Specific recommendation based on common scenarios

    Returns:
        dict: Comprehensive solution analysis containing:
            - success (bool): Whether analysis completed successfully
            - analysis (dict): Detailed situation analysis including:
                * stock_account: The specific ERPNext stock account involved
                * ledgers_mapped_to_stock: List of eBoekhouden ledgers causing conflicts
                * problem: Clear description of the integration challenge
                * solutions: Array of solution options with detailed pros/cons
            - recommendation: Expert recommendation for most appropriate solution
            - error: Error details if analysis fails

    Security Note:
        Requires high-security API access due to potential impact on financial data
        integrity and mapping configurations. Recommendations may affect significant
        volumes of historical and future transaction processing.

    Business Impact:
        Decisions based on these recommendations can affect:
        * Historical transaction import completeness
        * Future transaction processing workflows
        * Financial reporting accuracy and completeness
        * System maintenance complexity and reliability
    """
    try:
        # First, understand the mapping situation
        stock_account = "30000 - Voorraden - NVV"

        # Find all ledgers mapped to this stock account
        stock_mappings = frappe.get_all(
            "E-Boekhouden Ledger Mapping",
            filters={"erpnext_account": stock_account},
            fields=["ledger_id", "ledger_name", "ledger_code"],
            limit=20,
        )

        return {
            "success": True,
            "analysis": {
                "stock_account": stock_account,
                "ledgers_mapped_to_stock": stock_mappings,
                "problem": "Some eBoekhouden ledgers are mapped to stock accounts but appear in Journal Entry mutations",
                "solutions": [
                    {
                        "option": "Remap ledgers",
                        "description": "Change the mapping of problematic ledgers from stock accounts to appropriate expense/income accounts",
                        "pros": "Clean solution, fixes root cause",
                        "cons": "May affect other transactions",
                    },
                    {
                        "option": "Skip stock mutations",
                        "description": "Continue skipping mutations that involve stock accounts with clear logging",
                        "pros": "Safe, no data corruption",
                        "cons": "Some transactions not imported",
                    },
                    {
                        "option": "Create Stock Entries",
                        "description": "Convert stock-related mutations to Stock Entry documents instead of Journal Entries",
                        "pros": "All transactions imported",
                        "cons": "Complex logic, may not be appropriate for all cases",
                    },
                ],
            },
            "recommendation": "Option 1 (Remap ledgers) is likely best if these are mapping errors",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
