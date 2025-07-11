#!/usr/bin/env python3
"""
Setup E-Boekhouden workspace for new installations
Run this script if you installed the verenigingen app and the E-Boekhouden workspace is empty
"""

import sys
import os

# Instructions for users
def main():
    print("🔧 E-Boekhouden Workspace Setup")
    print("=" * 50)
    print()
    print("If your E-Boekhouden workspace is empty after installing the verenigingen app,")
    print("run this command from your frappe-bench directory:")
    print()
    print("   bench --site YOUR_SITE_NAME execute verenigingen.api.fix_workspace.fix_eboekhouden_workspace")
    print()
    print("Replace YOUR_SITE_NAME with your actual site name.")
    print()
    print("This will:")
    print("  ✅ Install the E-Boekhouden workspace")
    print("  ✅ Verify all links are working")
    print("  ✅ Remove any broken links")
    print()
    print("The workspace includes links to:")
    print("  - E-Boekhouden Migration")
    print("  - E-Boekhouden Settings") 
    print("  - E-Boekhouden Dashboard")
    print("  - Account Mapping")
    print("  - Ledger Mapping")
    print("  - Item Mapping")
    print("  - Import Log")
    print()

if __name__ == "__main__":
    main()