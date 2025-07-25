#!/usr/bin/env python3
"""Fetch and analyze specific payment mutations"""

import json
from datetime import datetime

# Run from bench console
def analyze_mutations():
    from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI
    
    # Initialize API
    settings = frappe.get_single("E-Boekhouden Settings")
    api = EBoekhoudenAPI(settings)
    
    # Specific mutations to analyze
    target_mutations = [7833, 5473, 6217]
    results = []
    
    print(f"\n{'='*80}")
    print(f"E-Boekhouden Payment Mutation Analysis")
    print(f"Analyzing mutations: {', '.join(map(str, target_mutations))}")
    print(f"{'='*80}\n")
    
    for mutation_id in target_mutations:
        print(f"\nFetching mutation {mutation_id}...")
        
        try:
            # Try to get mutation by ID directly
            result = api.make_request(f"v1/mutation/{mutation_id}", "GET")
            
            if result["success"]:
                mutation_data = json.loads(result["data"])
                
                # Pretty print the full structure
                print(f"\nMutation {mutation_id} - Full Structure:")
                print(json.dumps(mutation_data, indent=2))
                
                # Analyze key aspects
                print(f"\nMutation {mutation_id} - Analysis:")
                print(f"  Type: {mutation_data.get('type')} ({get_type_name(mutation_data.get('type'))})")
                print(f"  Date: {mutation_data.get('date')}")
                print(f"  Description: {mutation_data.get('description', '')[:100]}")
                print(f"  Invoice Number: {mutation_data.get('invoiceNumber')}")
                print(f"  Relation ID: {mutation_data.get('relationId')}")
                print(f"  Number of Rows: {len(mutation_data.get('rows', []))}")
                
                # Check for payment-specific fields
                rows = mutation_data.get('rows', [])
                if rows:
                    print(f"\n  Row Details:")
                    for i, row in enumerate(rows):
                        print(f"    Row {i+1}:")
                        print(f"      Ledger ID: {row.get('ledgerId')}")
                        print(f"      Amount: {row.get('amount')}")
                        print(f"      Description: {row.get('description', '')[:50]}")
                        print(f"      Invoice Number: {row.get('invoiceNumber')}")
                        print(f"      Relation ID: {row.get('relationId')}")
                
                # Look for any fields we haven't seen before
                all_keys = set(mutation_data.keys())
                known_keys = {'id', 'type', 'date', 'description', 'invoiceNumber', 'relationId', 'rows'}
                unknown_keys = all_keys - known_keys
                if unknown_keys:
                    print(f"\n  Additional Fields Found: {unknown_keys}")
                    for key in unknown_keys:
                        print(f"    {key}: {mutation_data.get(key)}")
                
                results.append({
                    "id": mutation_id,
                    "success": True,
                    "data": mutation_data
                })
                
            else:
                print(f"  ERROR: {result['error']}")
                results.append({
                    "id": mutation_id,
                    "success": False,
                    "error": result["error"]
                })
                
        except Exception as e:
            print(f"  EXCEPTION: {str(e)}")
            results.append({
                "id": mutation_id,
                "success": False,
                "error": str(e)
            })
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    
    # Check for multiple invoice support
    has_multiple_invoices = False
    for res in results:
        if res.get("success") and res.get("data"):
            rows = res["data"].get("rows", [])
            invoice_numbers = set()
            if res["data"].get("invoiceNumber"):
                invoice_numbers.add(res["data"].get("invoiceNumber"))
            for row in rows:
                if row.get("invoiceNumber"):
                    invoice_numbers.add(row.get("invoiceNumber"))
            if len(invoice_numbers) > 1:
                has_multiple_invoices = True
                print(f"\nMutation {res['id']} has multiple invoice references: {invoice_numbers}")
    
    print(f"\nMultiple Invoice Support: {'YES' if has_multiple_invoices else 'Not found in these samples'}")
    
    # Save results
    output_file = f"/home/frappe/frappe-bench/payment_mutations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")
    
    return results

def get_type_name(mutation_type):
    """Get human-readable name for mutation type"""
    type_mapping = {
        0: "Openstaande post (Opening Balance)",
        1: "Factuurontvangst (Purchase Invoice)",
        2: "Factuurbetaling (Sales Invoice)",
        3: "FactuurbetalingOntvangen (Customer Payment)",
        4: "FactuurbetalingVerstuurd (Supplier Payment)",
        5: "GeldOntvangen (Money Received)",
        6: "GeldUitgegeven (Money Spent)",
        7: "Memoriaal (Memorial/Journal)"
    }
    return type_mapping.get(mutation_type, f"Unknown Type {mutation_type}")

# Run the analysis
analyze_mutations()