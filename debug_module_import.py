#!/usr/bin/env python3

import os
import sys

# Add the Frappe path
sys.path.insert(0, "/home/frappe/frappe-bench")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")

# Set up environment for Frappe
os.environ["FRAPPE_SITE"] = "dev.veganisme.net"

try:
    import frappe

    from verenigingen.utils.sepa_admin_reporting import SEPAAdminReportGenerator

    print("✅ Successfully imported SEPAAdminReportGenerator")

    # Check if methods exist
    generator = SEPAAdminReportGenerator()
    methods_to_check = [
        "_analyze_mandate_lifecycle",
        "_analyze_performance_trends",
        "_calculate_trend",
        "_calculate_coefficient_of_variation",
    ]

    for method_name in methods_to_check:
        if hasattr(generator, method_name):
            print(f"✅ Method {method_name} exists")
        else:
            print(f"❌ Method {method_name} missing")

except ImportError as e:
    print(f"❌ Import error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
