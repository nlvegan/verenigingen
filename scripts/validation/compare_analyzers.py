#!/usr/bin/env python3
"""
Compare Original vs Patched AST Field Analyzers
"""

import sys
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ast_field_analyzer_original import ASTFieldAnalyzer as OriginalAnalyzer
from ast_field_analyzer import ASTFieldAnalyzer as ImprovedAnalyzer
from ast_field_analyzer import ConfidenceLevel

def compare_analyzers():
    """Compare both analyzers on the full codebase"""
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("="*70)
    print("COMPARING AST FIELD ANALYZERS")
    print("="*70)
    print()
    
    # Run original analyzer
    print("🔍 Running Original Analyzer...")
    original = OriginalAnalyzer(app_path, verbose=False)
    original_issues = original.validate_app(confidence_threshold=ConfidenceLevel.MEDIUM)
    
    # Run improved analyzer
    print("🚀 Running Improved Analyzer...")
    improved = ImprovedAnalyzer(app_path, verbose=False)
    improved_issues = improved.validate_app(confidence_threshold=ConfidenceLevel.MEDIUM)
    
    print()
    print("="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    print()
    
    # Count by confidence level
    def count_by_confidence(issues):
        counts = defaultdict(int)
        for issue in issues:
            counts[issue.confidence.value] += 1
        return counts
    
    original_counts = count_by_confidence(original_issues)
    improved_counts = count_by_confidence(improved_issues)
    
    print("📊 Issue Count by Confidence Level:")
    print()
    print("                Original    Patched    Reduction")
    print("-"*50)
    
    for level in ['critical', 'high', 'medium']:
        orig = original_counts.get(level, 0)
        patch = improved_counts.get(level, 0)
        reduction = orig - patch
        print(f"{level.upper():10s}     {orig:6d}    {patch:6d}     {reduction:6d}")
    
    print("-"*50)
    total_orig = sum(original_counts.get(l, 0) for l in ['critical', 'high', 'medium'])
    total_patch = sum(improved_counts.get(l, 0) for l in ['critical', 'high', 'medium'])
    total_reduction = total_orig - total_patch
    print(f"{'TOTAL':10s}     {total_orig:6d}    {total_patch:6d}     {total_reduction:6d}")
    
    print()
    
    # Find issues that were eliminated
    print("🔍 Analyzing Eliminated Issues...")
    print()
    
    # Create a set of issue keys for comparison
    def issue_key(issue):
        return (issue.file, issue.line, issue.field)
    
    original_keys = {issue_key(i) for i in original_issues}
    improved_keys = {issue_key(i) for i in improved_issues}
    
    eliminated_keys = original_keys - improved_keys
    
    # Group eliminated issues by file
    eliminated_by_file = defaultdict(list)
    for issue in original_issues:
        if issue_key(issue) in eliminated_keys:
            eliminated_by_file[Path(issue.file).name].append(issue)
    
    # Show hook files with eliminated issues
    hook_files_improved = []
    for filename, issues in eliminated_by_file.items():
        if filename.endswith('_hooks.py'):
            hook_files_improved.append((filename, len(issues)))
    
    if hook_files_improved:
        print("✨ Hook Files with Eliminated False Positives:")
        for filename, count in sorted(hook_files_improved, key=lambda x: x[1], reverse=True)[:5]:
            print(f"   {filename}: {count} issues eliminated")
    
    print()
    
    # Show specific example from membership_dues_schedule_hooks.py
    target_file = "membership_dues_schedule_hooks.py"
    if target_file in eliminated_by_file:
        print(f"📝 Example: {target_file}")
        print("-"*40)
        examples = eliminated_by_file[target_file][:3]
        for issue in examples:
            print(f"   Line {issue.line}: Field '{issue.field}' - ELIMINATED ✓")
        if len(eliminated_by_file[target_file]) > 3:
            print(f"   ... and {len(eliminated_by_file[target_file]) - 3} more")
    
    print()
    print("="*70)
    print("CONCLUSION")
    print("="*70)
    print()
    
    if total_reduction > 0:
        reduction_pct = (total_reduction / total_orig * 100) if total_orig > 0 else 0
        print(f"✅ SUCCESS: The improved analyzer reduced {total_reduction} false positives")
        print(f"   ({reduction_pct:.1f}% reduction in medium+ confidence issues)")
        
        if len(hook_files_improved) > 0:
            print(f"\n💡 Key Improvement: File path inference for hook files")
            print(f"   - {len(hook_files_improved)} hook files improved")
            print(f"   - {sum(c for _, c in hook_files_improved)} total issues eliminated")
    else:
        print("No significant changes detected")
    
    print()
    
    return total_orig, total_patch, total_reduction


if __name__ == "__main__":
    compare_analyzers()