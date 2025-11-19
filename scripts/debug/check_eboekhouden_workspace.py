#!/usr/bin/env python3
"""
Debug script to check E-Boekhouden workspace status
"""

import json
import os
import sys

def check_eboekhouden_workspace():
    """Check E-Boekhouden workspace in fixtures and database"""
    
    print("🔍 Checking E-Boekhouden Workspace Status")
    print("=" * 50)
    
    # Check fixtures file
    fixtures_path = os.path.join(frappe.get_app_path("verenigingen"), "verenigingen", "fixtures", "workspace.json")
    
    if not os.path.exists(fixtures_path):
        print("❌ Fixtures file not found:", fixtures_path)
        return
    
    print("✅ Fixtures file exists:", fixtures_path)
    
    # Load and parse fixtures
    with open(fixtures_path, 'r') as f:
        workspaces = json.load(f)
    
    # Find E-Boekhouden workspace
    eboekhouden_workspace = None
    for ws in workspaces:
        if ws.get("name") == "E-Boekhouden":
            eboekhouden_workspace = ws
            break
    
    if not eboekhouden_workspace:
        print("❌ E-Boekhouden workspace not found in fixtures")
        return
    
    print("✅ E-Boekhouden workspace found in fixtures")
    print(f"   - Label: {eboekhouden_workspace.get('label')}")
    print(f"   - Public: {eboekhouden_workspace.get('public')}")
    print(f"   - Hidden: {eboekhouden_workspace.get('is_hidden')}")
    print(f"   - Total links: {len(eboekhouden_workspace.get('links', []))}")
    
    # Check linked doctypes
    print("\n📋 Checking linked DocTypes:")
    missing_doctypes = []
    
    for link in eboekhouden_workspace.get('links', []):
        if link.get('link_type') == 'DocType' and link.get('link_to'):
            doctype_name = link['link_to']
            # Check if doctype directory exists
            doctype_path = f"/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/{doctype_name.lower().replace(' ', '_').replace('-', '_')}"
            
            if os.path.exists(doctype_path):
                print(f"   ✅ {doctype_name} - DocType exists")
            else:
                print(f"   ❌ {doctype_name} - DocType directory not found at {doctype_path}")
                missing_doctypes.append(doctype_name)
    
    # Summary
    print("\n📊 Summary:")
    if missing_doctypes:
        print(f"   ❌ Found {len(missing_doctypes)} missing DocTypes: {', '.join(missing_doctypes)}")
    else:
        print("   ✅ All linked DocTypes exist")
    
    # Check why validator might not catch this
    print("\n🔧 Workspace Validator Analysis:")
    print("   - The workspace validator checks the DATABASE, not the fixtures file")
    print("   - If the workspace hasn't been imported to the database, it won't be validated")
    print("   - The pre-commit hook only runs when workspace.json or workspace_*.py files change")
    print("   - The validator needs to be enhanced to check fixtures file content")
    
    return eboekhouden_workspace, missing_doctypes

if __name__ == "__main__":
    check_eboekhouden_workspace()
