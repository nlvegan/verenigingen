# Admin Tools

This directory contains administrative tools and utilities for maintaining the Verenigingen system.

## Tools

### fix_chapter_member_status.py

Fixes Chapter Member records where members are terminated/deceased/suspended but still marked as enabled in chapters.

**Problem**: The mijnrood CSV import was not properly setting `enabled=0` and `status='Inactive'` for non-Active members when assigning them to chapters. This caused terminated members to appear in active member counts on chapter dashboards.

**Solution**: This tool identifies and fixes mismatched records where `Member.status != 'Active'` but `Chapter Member.enabled = 1`.

**Usage via bench console**:

```bash
# Interactive usage
bench --site [sitename] console

>>> from admin_tools.fix_chapter_member_status import fix_all_chapters, fix_specific_chapter, get_mismatch_summary

# Get quick summary
>>> get_mismatch_summary()

# Dry run (safe - shows what would change)
>>> fix_all_chapters(dry_run=True)

# Apply fixes
>>> fix_all_chapters(dry_run=False)

# Fix specific chapter
>>> fix_specific_chapter('Utrecht', dry_run=True)
>>> fix_specific_chapter('Utrecht', dry_run=False)
```

**Usage via command line scripts**:

```bash
# Dry run - preview changes without modifying data
bench --site [sitename] console < admin_tools/fix_chapter_member_status_dryrun.py

# Apply fixes - modifies database records
bench --site [sitename] console < admin_tools/fix_chapter_member_status_apply.py
```

**Examples**:

```bash
# Check production site
bench --site veganisme.net console < admin_tools/fix_chapter_member_status_dryrun.py

# Fix development site
bench --site dev.veganisme.net console < admin_tools/fix_chapter_member_status_apply.py

# Fix staging site specific chapter
bench --site staging.veganisme.net console
>>> from admin_tools.fix_chapter_member_status import fix_specific_chapter
>>> fix_specific_chapter('Rotterdam', dry_run=False)
```

**Note**: The underlying code issue has been fixed in `verenigingen/doctype/chapter/managers/member_manager.py`, so future CSV imports will correctly handle non-Active members. This tool is only needed to correct existing mismatched data.

## Adding New Tools

When adding new administrative tools:

1. Create the main tool as a `.py` file with well-documented functions
2. Include usage examples in the docstring
3. Create convenience scripts (`_dryrun.py` and `_apply.py`) for command-line usage
4. Update this README with documentation
5. Use `[sitename]` placeholder in examples instead of hardcoded site names
