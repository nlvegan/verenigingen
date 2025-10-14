# Deprecated Function Usage Report

🔍 Deprecated Function Usage Report
==================================================
Total deprecated usages found: 1
Functions affected: 1

🚨 Function: get_creation_user
   Usages: 1
   Reason: Compatibility function - marked for migration review
   Replacement: Verify if secure_operations.get_creation_user exists or should be implemented

   📍 verenigingen/utils/application_helpers.py:414
      "owner": get_creation_user(),
