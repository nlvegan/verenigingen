"""
Apply fixes for Chapter Member status mismatches

CAUTION: This script will modify database records. Run dry run first to preview changes.

Usage:
    # First, run dry run to preview:
    bench --site [sitename] console < admin_tools/fix_chapter_member_status_dryrun.py

    # Then, if you're satisfied, apply the fixes:
    bench --site [sitename] console < admin_tools/fix_chapter_member_status_apply.py
"""

from admin_tools.fix_chapter_member_status import fix_all_chapters

print("\nApplying fixes for Chapter Member status mismatches...\n")
print("=" * 80)
print("WARNING: This will modify database records")
print("=" * 80)
print()

result = fix_all_chapters(dry_run=False)

if result["success"]:
    print("\n✅ All fixes applied successfully!")
else:
    print("\n⚠️  Some errors occurred. Please review the output above.")
