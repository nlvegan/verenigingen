#!/usr/bin/env python3
"""
Script to sanitize filenames by removing version-related adjectives
and updating all references to them.
"""

import os
import re
import subprocess
from pathlib import Path

# Define the mapping of files to rename
RENAME_MAPPING = {
    # Core business logic files
    "sepa_processor.py": "sepa_processor.py",
    "SEPAProcessor": "SEPAProcessor",
    "dues_schedule_manager.py": "dues_schedule_manager.py", 
    "sepa_validator.py": "sepa_validator.py",
    "payment_history_subscriber.py": "payment_history_subscriber.py",
    "eboekhouden_payment_import.py": "eboekhouden_payment_import.py",
    "eboekhouden_coa_import.py": "eboekhouden_coa_import.py",
    
    # Test files (common patterns)
    "test_enhanced_": "test_",
    "test_comprehensive_": "test_",
    "test_advanced_": "test_",
    "test_simple_": "test_",
    "test_basic_": "test_",
    "test_final_": "test_",
    "test_new_": "test_",
    "test_improved_": "test_",
    "test_complete_": "test_",
    "_v2": "",
    "_enhanced": "",
    "_comprehensive": "",
    "_advanced": "",
    "_simple": "",
    "_basic": "",
    "_final": "",
    "_new": "",
    "_improved": "",
    "_complete": "",
}

def find_files_to_rename(base_path):
    """Find all files that need renaming based on the mapping"""
    files_to_rename = []
    
    for root, dirs, files in os.walk(base_path):
        # Skip node_modules and other irrelevant directories
        dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', '.git']]
        
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, base_path)
            
            # Check if file needs renaming
            for old_pattern, new_pattern in RENAME_MAPPING.items():
                if old_pattern in file:
                    new_filename = file.replace(old_pattern, new_pattern)
                    if new_filename != file:
                        files_to_rename.append({
                            'old_path': file_path,
                            'new_path': os.path.join(root, new_filename),
                            'old_name': file,
                            'new_name': new_filename,
                            'relative_old': relative_path,
                            'relative_new': os.path.relpath(os.path.join(root, new_filename), base_path)
                        })
                        break
    
    return files_to_rename

def update_file_references(base_path, old_name, new_name):
    """Update all references to a renamed file throughout the codebase"""
    
    # Find all files that might contain references
    extensions = ['.py', '.js', '.json', '.html', '.md', '.txt', '.yaml', '.yml']
    
    for root, dirs, files in os.walk(base_path):
        dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', '.git']]
        
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Check if file contains references to the old name
                    if old_name in content:
                        # Replace references
                        updated_content = content.replace(old_name, new_name)
                        
                        if updated_content != content:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(updated_content)
                            print(f"  Updated references in: {os.path.relpath(file_path, base_path)}")
                            
                except (UnicodeDecodeError, PermissionError):
                    # Skip binary files or files we can't read
                    continue

def main():
    """Main function to perform filename sanitization"""
    base_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🧹 Starting filename sanitization...")
    print("=" * 50)
    
    # Find files to rename
    files_to_rename = find_files_to_rename(base_path)
    
    print(f"Found {len(files_to_rename)} files to rename:")
    for file_info in files_to_rename[:10]:  # Show first 10
        print(f"  {file_info['relative_old']} → {file_info['relative_new']}")
    
    if len(files_to_rename) > 10:
        print(f"  ... and {len(files_to_rename) - 10} more files")
    
    # Ask for confirmation
    response = input(f"\nProceed with renaming {len(files_to_rename)} files? (y/N): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return
    
    # Perform renames and update references
    renamed_count = 0
    
    for file_info in files_to_rename:
        try:
            # Rename the file
            os.rename(file_info['old_path'], file_info['new_path'])
            print(f"✓ Renamed: {file_info['relative_old']} → {file_info['relative_new']}")
            
            # Update all references to this file
            old_filename = file_info['old_name']
            new_filename = file_info['new_name']
            
            # Update both filename and any class/function names
            update_file_references(base_path, old_filename, new_filename)
            
            # Remove file extensions for class/import name updates
            old_name_no_ext = old_filename.replace('.py', '').replace('.js', '').replace('.html', '')
            new_name_no_ext = new_filename.replace('.py', '').replace('.js', '').replace('.html', '')
            
            if old_name_no_ext != new_name_no_ext:
                update_file_references(base_path, old_name_no_ext, new_name_no_ext)
            
            renamed_count += 1
            
        except Exception as e:
            print(f"❌ Failed to rename {file_info['relative_old']}: {e}")
    
    print(f"\n🎉 Successfully renamed {renamed_count} files!")
    print("\n⚠️  Remember to:")
    print("  1. Test the application to ensure all imports work")
    print("  2. Update any documentation that references old filenames")
    print("  3. Check for any hardcoded string references that might have been missed")

if __name__ == "__main__":
    main()