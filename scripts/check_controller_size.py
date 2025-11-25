#!/usr/bin/env python3
"""
Controller Size Enforcement Script

Prevents controller files from growing beyond established limits.
Part of service layer adoption enforcement strategy.

Usage:
    python scripts/check_controller_size.py

Exit Codes:
    0: All controllers within limits
    1: One or more controllers exceed limits
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Controller size limits (current baseline + 0% tolerance)
# These limits represent CURRENT state and should NOT grow
CONTROLLER_LIMITS = {
    "verenigingen/verenigingen/doctype/member/member.py": {
        "max_lines": 2160,
        "target_lines": 800,
        "description": "Member controller - core member lifecycle",
    },
    "verenigingen/verenigingen/doctype/volunteer/volunteer.py": {
        "max_lines": 1020,
        "target_lines": 500,
        "description": "Volunteer controller - volunteer management",
    },
    "verenigingen/verenigingen/doctype/membership_dues_schedule/membership_dues_schedule.py": {
        "max_lines": 2837,
        "target_lines": 800,
        "description": "Membership Dues Schedule - billing automation",
    },
}

# Warning threshold (90% of limit)
WARNING_THRESHOLD = 0.90


def count_lines(file_path: Path) -> int:
    """Count non-empty lines in a file.

    Args:
        file_path: Path to file

    Returns:
        Number of non-empty lines
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except FileNotFoundError:
        return 0


def check_controller_sizes() -> Tuple[List[str], List[str], bool]:
    """Check all controller file sizes against limits.

    Returns:
        Tuple of (violations, warnings, has_violations)
    """
    violations = []
    warnings = []
    has_violations = False

    # Get repository root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    print("🔍 Controller Size Check")
    print("=" * 70)
    print()

    for file_path, config in CONTROLLER_LIMITS.items():
        full_path = repo_root / file_path
        max_lines = config["max_lines"]
        target_lines = config["target_lines"]
        description = config["description"]

        line_count = count_lines(full_path)
        warning_limit = int(max_lines * WARNING_THRESHOLD)

        # Calculate progress toward target
        if line_count <= target_lines:
            progress_pct = 100
            status = "✅ TARGET ACHIEVED"
        else:
            progress_pct = int(((max_lines - line_count) / (max_lines - target_lines)) * 100)
            if line_count > max_lines:
                status = "❌ EXCEEDS LIMIT"
                has_violations = True
            elif line_count > warning_limit:
                status = "⚠️  WARNING"
            else:
                status = "✅ OK"

        print(f"📄 {file_path}")
        print(f"   {description}")
        print(f"   Current: {line_count:,} lines | Max: {max_lines:,} | Target: {target_lines:,}")
        print(f"   Status: {status}")

        if progress_pct <= 100 and line_count > target_lines:
            print(f"   Progress to target: {progress_pct}%")

        # Check for violations
        if line_count > max_lines:
            violations.append(
                f"{file_path}: {line_count:,} lines (max: {max_lines:,}, excess: +{line_count - max_lines:,})"
            )
        elif line_count > warning_limit:
            warnings.append(
                f"{file_path}: {line_count:,} lines (approaching limit: {max_lines:,}, remaining: {max_lines - line_count:,})"
            )

        print()

    return violations, warnings, has_violations


def main():
    """Main entry point."""
    violations, warnings, has_violations = check_controller_sizes()

    # Print summary
    print("=" * 70)
    print()

    if violations:
        print("❌ CONTROLLER SIZE VIOLATIONS DETECTED")
        print()
        print("The following controllers exceed their size limits:")
        print()
        for violation in violations:
            print(f"  • {violation}")
        print()
        print("⚠️  Policy: New business logic MUST be added to service layer")
        print("   Controllers should only orchestrate services, not implement logic")
        print()
        print("📚 See: docs/architecture/SERVICE_INFRASTRUCTURE_ARCHITECTURE.md")
        print()
        sys.exit(1)

    if warnings:
        print("⚠️  CONTROLLER SIZE WARNINGS")
        print()
        print("The following controllers are approaching their limits:")
        print()
        for warning in warnings:
            print(f"  • {warning}")
        print()
        print("💡 Consider extracting logic to service layer before adding more code")
        print()

    if not violations and not warnings:
        print("✅ ALL CONTROLLERS WITHIN SIZE LIMITS")
        print()
        print("   Great work maintaining service-oriented architecture!")
        print()

    print("📊 Summary:")
    print(f"   • {len(CONTROLLER_LIMITS)} controllers monitored")
    print(f"   • {len(violations)} violations")
    print(f"   • {len(warnings)} warnings")
    print()

    sys.exit(0)


if __name__ == "__main__":
    main()
