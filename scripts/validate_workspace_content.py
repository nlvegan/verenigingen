#!/usr/bin/env python3
"""
Workspace Content Validation Script
Validates synchronization between workspace content field and database Card Breaks

Usage:
    python scripts/validate_workspace_content.py [workspace_name]
    
If no workspace_name provided, validates all workspaces.
"""

import sys
import json
import frappe


def main():
    """Main validation function"""
    
    # Initialize Frappe
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    
    try:
        if len(sys.argv) > 1:
            # Validate specific workspace
            workspace_name = sys.argv[1]
            print(f"🔍 Validating workspace: {workspace_name}")
            
            from verenigingen.api.workspace_content_validator import validate_workspace_content_sync
            result = validate_workspace_content_sync(workspace_name)
            
            print_validation_result(workspace_name, result)
            
            # Exit with error code if validation failed
            if result['status'] in ['failed', 'warning']:
                sys.exit(1)
                
        else:
            # Validate all workspaces
            print("🔍 Validating all workspaces...")
            
            from verenigingen.api.workspace_content_validator import validate_all_workspaces_content
            result = validate_all_workspaces_content()
            
            print_summary_result(result)
            
            # Exit with error code if validation failed
            if result['status'] in ['failed', 'warning']:
                sys.exit(1)
                
        print("✅ All validations passed!")
        
    except Exception as e:
        print(f"❌ Validation failed with error: {str(e)}")
        sys.exit(1)
    
    finally:
        frappe.destroy()


def print_validation_result(workspace_name: str, result: dict):
    """Print detailed validation result for a single workspace"""
    
    print(f"\n📊 VALIDATION RESULT FOR {workspace_name}")
    print("=" * 60)
    
    # Overall status
    status_icon = "✅" if result['status'] == 'passed' else ("⚠️" if result['status'] == 'warning' else "❌")
    print(f"Status: {status_icon} {result['status'].upper()}")
    
    # Synchronization info
    sync_pct = result['sync_analysis']['sync_percentage']
    sync_icon = "✅" if result['is_synchronized'] else "❌"
    print(f"Content Sync: {sync_icon} {sync_pct:.1f}% synchronized")
    
    # Empty sections info
    empty_icon = "✅" if not result['has_empty_sections'] else "❌"
    empty_count = len(result['empty_sections'])
    print(f"Empty Sections: {empty_icon} {empty_count} empty sections found")
    
    # Detailed issues
    if result['errors']:
        print(f"\n❌ ERRORS ({len(result['errors'])}):")
        for error in result['errors']:
            print(f"  • {error}")
    
    if result['warnings']:
        print(f"\n⚠️  WARNINGS ({len(result['warnings'])}):")
        for warning in result['warnings']:
            print(f"  • {warning}")
    
    # Content structure summary
    content = result['content_structure']
    print(f"\n📄 CONTENT STRUCTURE:")
    print(f"  Headers: {len(content['headers'])}")
    print(f"  Cards: {len(content['cards'])}")
    print(f"  Sections: {len(content['sections'])}")
    
    # Database structure summary  
    db = result['card_break_structure']
    print(f"\n🗃️  DATABASE STRUCTURE:")
    print(f"  Card Breaks: {db['total_breaks']}")
    print(f"  Links: {db['total_links']}")
    
    # Sync details
    sync = result['sync_analysis']
    if sync['content_only']:
        print(f"\n🔗 CONTENT-ONLY CARDS:")
        for card in sync['content_only']:
            print(f"  • {card}")
    
    if sync['db_only']:
        print(f"\n🗃️  DATABASE-ONLY CARD BREAKS:")
        for card in sync['db_only']:
            print(f"  • {card}")


def print_summary_result(result: dict):
    """Print summary result for all workspaces"""
    
    print(f"\n📊 VALIDATION SUMMARY")
    print("=" * 60)
    
    summary = result['summary']
    status_icon = "✅" if result['status'] == 'passed' else ("⚠️" if result['status'] == 'warning' else "❌")
    
    print(f"Overall Status: {status_icon} {result['status'].upper()}")
    print(f"Total Workspaces: {summary['total_workspaces']}")
    print(f"Workspaces with Sync Issues: {summary['workspaces_with_sync_issues']}")
    print(f"Workspaces with Empty Sections: {summary['workspaces_with_empty_sections']}")
    print(f"Total Errors: {summary['total_errors']}")
    print(f"Total Warnings: {summary['total_warnings']}")
    
    # Show problematic workspaces
    if summary['workspaces_with_sync_issues'] > 0 or summary['workspaces_with_empty_sections'] > 0:
        print(f"\n🔍 WORKSPACES WITH ISSUES:")
        
        for ws_name, ws_result in result['workspace_results'].items():
            if not ws_result['is_synchronized'] or ws_result['has_empty_sections']:
                sync_status = "✅" if ws_result['is_synchronized'] else "❌"
                empty_status = "✅" if not ws_result['has_empty_sections'] else "❌"
                print(f"  • {ws_name}: sync={sync_status} empty={empty_status}")


if __name__ == "__main__":
    main()