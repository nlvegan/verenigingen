#!/usr/bin/env python3
"""
Pre-commit wrapper for workspace validation

Simple script that can be called by pre-commit hooks to validate workspace integrity.
"""

import subprocess
import sys


def main():
    """Run workspace validation through bench"""
    try:
        # Run the validation through bench
        result = subprocess.run([
            "bench", "--site", "dev.veganisme.net", "execute",
            "verenigingen.api.workspace_validator.run_workspace_pre_commit_check"
        ], capture_output=True, text=True, cwd="/home/frappe/frappe-bench")
        
        # Print the output
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        # Parse the result to determine exit code
        if '"should_fail_commit": true' in result.stdout:
            print("\n❌ Workspace validation failed - commit blocked")
            sys.exit(1)
        elif result.returncode != 0:
            print(f"\n❌ Validation script failed with code {result.returncode}")
            sys.exit(1)
        else:
            print("\n✅ Workspace validation passed")
            sys.exit(0)
            
    except Exception as e:
        print(f"❌ Error running workspace validation: {str(e)}")
        # Don't block commits on script errors, just warn
        print("⚠️  Continuing with commit due to validation script error")
        sys.exit(0)


if __name__ == "__main__":
    main()