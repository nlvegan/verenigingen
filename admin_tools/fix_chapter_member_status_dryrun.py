"""
Quick dry run script for fixing Chapter Member status mismatches

Usage:
    bench --site [sitename] console < admin_tools/fix_chapter_member_status_dryrun.py
"""

from admin_tools.fix_chapter_member_status import fix_all_chapters

print("\nRunning dry run to check for Chapter Member status mismatches...\n")
result = fix_all_chapters(dry_run=True)
