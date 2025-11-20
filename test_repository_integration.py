#!/usr/bin/env python
"""Quick test script for DuesScheduleRepository integration"""

import sys

sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")

# Test imports
try:
    from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository

    print("✓ DuesScheduleRepository import successful")
except Exception as e:
    print(f"✗ DuesScheduleRepository import failed: {e}")
    sys.exit(1)

try:
    from verenigingen.utils.member_utils import (
        get_member_active_or_paused_schedule,
        get_member_dues_schedule,
        get_member_dues_schedule_name,
        has_active_dues_schedule,
        has_any_dues_schedule,
    )

    print("✓ member_utils helper functions import successful")
except Exception as e:
    print(f"✗ member_utils import failed: {e}")
    sys.exit(1)

print("\n✓ All imports successful! Ready for testing.")
