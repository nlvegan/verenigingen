#!/usr/bin/env python3
"""
Field Rename Safety System

Provides backup, validation, and rollback capabilities for safe custom field renaming.

Author: Claude Code Assistant
Date: 2025-08-24
"""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List

class FieldRenameSafety:
    """Safety mechanisms for field renaming operations"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.backup_dir = self.app_path / 'backups' / 'field_rename'
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
    def create_pre_change_backup(self, field_name: str) -> str:
        """Create comprehensive backup before making changes"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{field_name}_backup_{timestamp}"
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)
        
        print(f"🛡️  Creating safety backup: {backup_name}")
        
        # 1. Backup custom_field.json
        source_fixture = self.app_path / 'verenigingen/fixtures/custom_field.json'
        backup_fixture = backup_path / 'custom_field.json'
        shutil.copy2(source_fixture, backup_fixture)
        
        # 2. Create git stash for current working state
        try:
            result = subprocess.run(['git', 'status', '--porcelain'], 
                                  capture_output=True, text=True, cwd=self.app_path)
            if result.stdout.strip():
                stash_result = subprocess.run(['git', 'stash', 'push', '-m', f'Pre {field_name} rename backup'], 
                                           capture_output=True, text=True, cwd=self.app_path)
                if stash_result.returncode == 0:
                    print(f"  ✅ Git stash created: {stash_result.stdout.strip()}")
                    
                    # Save stash reference
                    with open(backup_path / 'git_stash_ref.txt', 'w') as f:
                        f.write(f"Stash created at: {timestamp}\n")
                        f.write(f"Stash message: Pre {field_name} rename backup\n")
        except Exception as e:
            print(f"  ⚠️  Git stash failed: {e}")
        
        # 3. Create rollback script
        self._create_rollback_script(backup_path, field_name, backup_name)
        
        print(f"  ✅ Backup created at: {backup_path}")
        return str(backup_path)
    
    def _create_rollback_script(self, backup_path: Path, field_name: str, backup_name: str):
        """Create automated rollback script"""
        rollback_script = f"""#!/bin/bash
# Rollback script for {field_name} field rename
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

echo "🔄 Rolling back {field_name} field rename changes..."

# Restore custom_field.json
cp "{backup_path}/custom_field.json" "{self.app_path}/verenigingen/fixtures/custom_field.json"
echo "  ✅ Restored custom_field.json"

# Restore git stash if it exists
if [ -f "{backup_path}/git_stash_ref.txt" ]; then
    echo "  🔄 Attempting to restore git stash..."
    git stash pop
    echo "  ✅ Git stash restored"
fi

echo "🎯 Rollback complete for {field_name}"
echo "   Backup used: {backup_name}"
"""
        rollback_path = backup_path / 'rollback.sh'
        rollback_path.write_text(rollback_script)
        rollback_path.chmod(0o755)  # Make executable
        
        print(f"  📜 Rollback script created: {rollback_path}")
    
    def validate_field_rename(self, old_name: str, new_name: str) -> Dict:
        """Validate that field rename follows conventions"""
        print(f"🔍 Validating field rename: {old_name} → {new_name}")
        
        issues = []
        warnings = []
        
        # Check naming convention
        if not new_name.startswith('custom_'):
            issues.append(f"New name '{new_name}' doesn't start with 'custom_' prefix")
        
        # Check that old name exists in fixtures
        fixture_path = self.app_path / 'verenigingen/fixtures/custom_field.json'
        with open(fixture_path) as f:
            fields = json.load(f)
            
        old_field_found = False
        for field in fields:
            if field.get('fieldname') == old_name:
                old_field_found = True
                break
                
        if not old_field_found:
            issues.append(f"Old field name '{old_name}' not found in custom_field.json")
        
        # Check if new name already exists
        new_field_exists = False
        for field in fields:
            if field.get('fieldname') == new_name:
                new_field_exists = True
                break
                
        if new_field_exists:
            issues.append(f"New field name '{new_name}' already exists in fixtures")
        
        # Length check
        if len(new_name) > 140:  # Frappe limit
            issues.append(f"New field name too long: {len(new_name)} chars (max 140)")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings
        }
    
    def test_field_rename_impact(self, old_name: str, new_name: str) -> Dict:
        """Test the potential impact of renaming a field"""
        print(f"🧪 Testing impact of renaming: {old_name} → {new_name}")
        
        # Search for references
        references = []
        
        # Search Python files
        for py_file in self.app_path.rglob('*.py'):
            if 'node_modules' in str(py_file) or '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text()
                if old_name in content:
                    references.append(str(py_file.relative_to(self.app_path)))
            except:
                continue
        
        # Search JavaScript files
        for js_file in self.app_path.rglob('*.js'):
            if 'node_modules' in str(js_file):
                continue
            try:
                content = js_file.read_text()
                if old_name in content:
                    references.append(str(js_file.relative_to(self.app_path)))
            except:
                continue
        
        return {
            'total_files_with_references': len(set(references)),
            'reference_files': sorted(set(references))
        }
    
    def perform_safe_field_rename(self, old_name: str, new_name: str, doctype: str) -> bool:
        """Perform a complete safe field rename operation"""
        print(f"🚀 Starting safe field rename operation")
        print(f"   Field: {old_name} → {new_name}")
        print(f"   DocType: {doctype}")
        
        # Step 1: Validation
        validation = self.validate_field_rename(old_name, new_name)
        if not validation['valid']:
            print("❌ Validation failed:")
            for issue in validation['issues']:
                print(f"     {issue}")
            return False
        
        # Step 2: Impact assessment
        impact = self.test_field_rename_impact(old_name, new_name)
        print(f"  📊 Impact: {impact['total_files_with_references']} files to update")
        
        if impact['total_files_with_references'] > 10:
            print(f"  ⚠️  High impact detected - proceed with extreme caution")
        
        # Step 3: Create backup
        backup_path = self.create_pre_change_backup(old_name)
        
        # Step 4: Update custom_field.json
        try:
            self._update_custom_field_json(old_name, new_name, doctype)
            print(f"  ✅ Updated custom_field.json")
        except Exception as e:
            print(f"  ❌ Failed to update custom_field.json: {e}")
            return False
        
        print(f"🎯 Field rename completed successfully!")
        print(f"  Backup location: {backup_path}")
        print(f"  Next steps:")
        print(f"    1. Update {impact['total_files_with_references']} code files")
        print(f"    2. Test thoroughly")
        print(f"    3. Run rollback.sh if issues occur")
        
        return True
    
    def _update_custom_field_json(self, old_name: str, new_name: str, doctype: str):
        """Update the custom field JSON fixture"""
        fixture_path = self.app_path / 'verenigingen/fixtures/custom_field.json'
        
        with open(fixture_path) as f:
            fields = json.load(f)
        
        # Find and update the field
        for field in fields:
            if field.get('fieldname') == old_name and field.get('dt') == doctype:
                # Update fieldname
                field['fieldname'] = new_name
                
                # Update name (important for Frappe)
                old_field_name = field.get('name', '')
                if old_field_name:
                    new_field_name = old_field_name.replace(old_name, new_name)
                    field['name'] = new_field_name
                
                print(f"    Updated field: {old_field_name} → {new_field_name}")
                break
        
        # Save updated fields
        with open(fixture_path, 'w') as f:
            json.dump(fields, f, indent=1, ensure_ascii=False)

def main():
    """Demo/test the safety system"""
    safety = FieldRenameSafety("/home/frappe/frappe-bench/apps/verenigingen")
    
    # Test validation
    test_validation = safety.validate_field_rename("eboekhouden_section", "custom_eboekhouden_section")
    print(f"Validation test: {test_validation}")
    
    # Test impact assessment 
    test_impact = safety.test_field_rename_impact("eboekhouden_section", "custom_eboekhouden_section")
    print(f"Impact test: {test_impact}")

if __name__ == "__main__":
    main()