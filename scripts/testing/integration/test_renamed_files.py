#!/usr/bin/env python3
"""
Test imports of renamed core files to ensure they work correctly
"""

def test_renamed_file_imports():
    """Test that all renamed core files can be imported"""
    
    test_cases = [
        ("SEPA Processor", "verenigingen.verenigingen.doctype.direct_debit_batch.sepa_processor", "SEPAProcessor"),
        ("SEPA Validator", "verenigingen.utils.sepa_validator", "validate_sepa_integration"),
        ("Dues Schedule Manager", "verenigingen.verenigingen.doctype.membership.dues_schedule_manager", "sync_membership_with_dues_schedule"),
        ("Payment History Subscriber", "verenigingen.events.subscribers.payment_history_subscriber", None),
        ("eBoekhouden Payment Import", "verenigingen.utils.eboekhouden.eboekhouden_payment_import", "create_payment_entry"),
        ("eBoekhouden COA Import", "verenigingen.utils.eboekhouden.eboekhouden_coa_import", "coa_import_with_bank_accounts"),
    ]
    
    results = []
    
    for name, module_path, function_name in test_cases:
        try:
            module = __import__(module_path, fromlist=[function_name] if function_name else [])
            
            if function_name:
                func = getattr(module, function_name)
                results.append(f"✓ {name}: Module and function '{function_name}' imported successfully")
            else:
                results.append(f"✓ {name}: Module imported successfully")
                
        except ImportError as e:
            results.append(f"✗ {name}: Import failed - {e}")
        except AttributeError as e:
            results.append(f"✗ {name}: Function not found - {e}")
        except Exception as e:
            results.append(f"✗ {name}: Unexpected error - {e}")
    
    # Print results
    print("=" * 60)
    print("RENAMED FILE IMPORT TEST RESULTS")
    print("=" * 60)
    
    for result in results:
        print(result)
    
    # Summary
    success_count = sum(1 for r in results if r.startswith("✓"))
    total_count = len(results)
    
    print("\n" + "=" * 60)
    print(f"SUMMARY: {success_count}/{total_count} files imported successfully")
    
    if success_count == total_count:
        print("🎉 All renamed core files are working correctly!")
        return True
    else:
        print("⚠️  Some renamed files have import issues")
        return False

if __name__ == "__main__":
    test_renamed_file_imports()