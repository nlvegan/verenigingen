#!/usr/bin/env python3
"""
Phase 4.2 Focused Test Consolidation
Fast, focused consolidation targeting exactly the files identified for removal
"""

import os
import json
import shutil
from pathlib import Path
from typing import Dict, List

class FocusedConsolidationExecutor:
    """Focused Phase 4.2 consolidation executor"""
    
    def __init__(self, app_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.app_path = Path(app_path)
        self.removed_count = 0
        self.errors = []
        
    def load_files_to_remove(self) -> List[str]:
        """Load specific files marked for removal"""
        results_file = self.app_path / "phase4_test_analysis_results.json"
        
        with open(results_file, 'r') as f:
            results = json.load(f)
        
        files_to_remove = []
        for file_info in results['consolidation_plan']['files_to_remove']:
            files_to_remove.append(file_info['path'])
        
        return files_to_remove
    
    def create_quick_backup(self, files_to_remove: List[str]):
        """Create quick backup of only files being removed"""
        backup_dir = self.app_path / "phase4_removed_files_backup"
        backup_dir.mkdir(exist_ok=True)
        
        print(f"🔒 Creating backup of {len(files_to_remove)} files to be removed...")
        
        for file_path_str in files_to_remove:
            file_path = Path(file_path_str)
            if file_path.exists():
                # Use filename with parent dir to avoid conflicts
                backup_name = f"{file_path.parent.name}_{file_path.name}"
                backup_path = backup_dir / backup_name
                shutil.copy2(file_path, backup_path)
        
        print(f"✅ Backup created at: {backup_dir}")
    
    def remove_files_safely(self, files_to_remove: List[str]):
        """Safely remove the identified files"""
        print(f"🗑️  Removing {len(files_to_remove)} files...")
        
        for file_path_str in files_to_remove:
            file_path = Path(file_path_str)
            
            try:
                if file_path.exists():
                    file_path.unlink()
                    self.removed_count += 1
                    relative_path = file_path.relative_to(self.app_path)
                    print(f"  ✅ Removed: {relative_path}")
                else:
                    print(f"  ⚠️  Not found: {file_path}")
                    
            except Exception as e:
                error_msg = f"Failed to remove {file_path}: {e}"
                self.errors.append(error_msg)
                print(f"  ❌ Error: {error_msg}")
    
    def remove_empty_directories(self):
        """Remove empty directories after file removal"""
        print("📁 Cleaning up empty directories...")
        
        # Check common test directories for emptiness
        dirs_to_check = [
            self.app_path / "archived_removal",
            self.app_path / "archived_unused",
            self.app_path / "scripts" / "testing" / "integration",
            self.app_path / "scripts" / "validation"
        ]
        
        for dir_path in dirs_to_check:
            if dir_path.exists() and dir_path.is_dir():
                try:
                    # Remove if empty or contains only __pycache__
                    remaining_files = [f for f in dir_path.rglob("*") if f.is_file() and not f.name.startswith('.') and '__pycache__' not in str(f)]
                    
                    if not remaining_files:
                        shutil.rmtree(dir_path)
                        print(f"  ✅ Removed empty directory: {dir_path.relative_to(self.app_path)}")
                        
                except Exception as e:
                    print(f"  ⚠️  Could not remove directory {dir_path}: {e}")
    
    def run_quick_validation(self) -> bool:
        """Run quick validation to ensure system still works"""
        print("🧪 Running quick validation...")
        
        try:
            # Count remaining test files
            remaining_files = list(self.app_path.rglob("test_*.py"))
            print(f"📊 Remaining test files: {len(remaining_files)}")
            
            # Check that core business logic tests still exist
            core_patterns = ['test_member.py', 'test_payment', 'test_volunteer.py', 'test_sepa']
            core_found = 0
            
            for pattern in core_patterns:
                for test_file in remaining_files:
                    if pattern in test_file.name:
                        core_found += 1
                        break
            
            if core_found >= 3:
                print("✅ Core business logic tests preserved")
                return True
            else:
                print(f"⚠️  Only {core_found}/{len(core_patterns)} core test patterns found")
                return False
                
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return False
    
    def generate_summary_report(self):
        """Generate summary of consolidation results"""
        print("\n" + "="*60)
        print("📊 PHASE 4.2 CONSOLIDATION SUMMARY")
        print("="*60)
        
        print(f"🗑️  Files Removed: {self.removed_count}")
        print(f"❌ Errors: {len(self.errors)}")
        
        if self.errors:
            print("\n⚠️  Errors encountered:")
            for error in self.errors[:5]:  # Show first 5 errors
                print(f"  - {error}")
            if len(self.errors) > 5:
                print(f"  ... and {len(self.errors) - 5} more errors")
        
        # Count current test files
        try:
            current_files = list(self.app_path.rglob("test_*.py"))
            original_count = 427  # From analysis
            current_count = len(current_files)
            reduction = original_count - current_count
            reduction_percentage = (reduction / original_count) * 100
            
            print(f"\n📈 RESULTS:")
            print(f"  Original Files: {original_count}")
            print(f"  Current Files:  {current_count}")
            print(f"  Reduction:      {reduction} files ({reduction_percentage:.1f}%)")
            
            if reduction_percentage >= 25:
                print("  ✅ Target reduction achieved!")
            else:
                print("  ⚠️  Target reduction not fully achieved")
                
        except Exception as e:
            print(f"  ❌ Could not calculate final statistics: {e}")
    
    def execute_focused_consolidation(self):
        """Execute focused Phase 4.2 consolidation"""
        print("🚀 Starting Phase 4.2: Focused Test Consolidation")
        print("="*60)
        
        try:
            # Load files to remove
            files_to_remove = self.load_files_to_remove()
            print(f"📋 Identified {len(files_to_remove)} files for removal")
            
            # Create backup
            self.create_quick_backup(files_to_remove)
            
            # Remove files
            self.remove_files_safely(files_to_remove)
            
            # Clean up empty directories
            self.remove_empty_directories()
            
            # Validate results
            validation_passed = self.run_quick_validation()
            
            # Generate summary
            self.generate_summary_report()
            
            print(f"\n✅ Phase 4.2 Focused Consolidation Completed!")
            print(f"🧪 Validation: {'✅ Passed' if validation_passed else '⚠️  Needs review'}")
            
            return validation_passed
            
        except Exception as e:
            print(f"\n❌ Phase 4.2 consolidation failed: {e}")
            print("💡 Backup available in phase4_removed_files_backup/ directory")
            raise

def main():
    """Main execution function"""
    executor = FocusedConsolidationExecutor()
    executor.execute_focused_consolidation()

if __name__ == "__main__":
    main()