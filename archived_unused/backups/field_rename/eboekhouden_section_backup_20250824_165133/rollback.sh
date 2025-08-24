#!/bin/bash
# Rollback script for eboekhouden_section field rename
# Generated: 2025-08-24 16:51:33

echo "🔄 Rolling back eboekhouden_section field rename changes..."

# Restore custom_field.json
cp "/home/frappe/frappe-bench/apps/verenigingen/backups/field_rename/eboekhouden_section_backup_20250824_165133/custom_field.json" "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json"
echo "  ✅ Restored custom_field.json"

# Restore git stash if it exists
if [ -f "/home/frappe/frappe-bench/apps/verenigingen/backups/field_rename/eboekhouden_section_backup_20250824_165133/git_stash_ref.txt" ]; then
    echo "  🔄 Attempting to restore git stash..."
    git stash pop
    echo "  ✅ Git stash restored"
fi

echo "🎯 Rollback complete for eboekhouden_section"
echo "   Backup used: eboekhouden_section_backup_20250824_165133"
