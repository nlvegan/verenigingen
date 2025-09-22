#!/usr/bin/env python3
"""
Quick runner script for N+1 Query Pattern Analysis

This script provides convenient access to the N+1 scanner with different analysis modes.
"""

import sys
import os
from pathlib import Path

# Add the app path to Python path for imports
app_path = Path(__file__).parent.parent
sys.path.append(str(app_path))

from verenigingen.scripts.n_plus_one_scanner import N1CodebaseScanner, run_scan


def analyze_high_priority_only(base_path: str):
    """Run analysis focusing only on high-priority files"""
    print("🎯 HIGH-PRIORITY N+1 ANALYSIS")
    print("=" * 50)
    
    scanner = N1CodebaseScanner(base_path)
    all_patterns = scanner.scan_codebase(exclude_tests=True)
    
    # Filter to high severity only
    high_patterns = [p for p in all_patterns if p.severity == 'high']
    
    print(f"\n📊 HIGH SEVERITY SUMMARY:")
    print(f"Total high-severity patterns: {len(high_patterns)}")
    
    # Group by file
    files_with_high = {}
    for pattern in high_patterns:
        file_path = str(Path(pattern.file_path).relative_to(Path(base_path)))
        if file_path not in files_with_high:
            files_with_high[file_path] = []
        files_with_high[file_path].append(pattern)
    
    print(f"Files with high-severity issues: {len(files_with_high)}")
    
    print("\n🚨 CRITICAL FILES TO FIX FIRST:")
    print("-" * 40)
    
    # Sort by number of issues
    sorted_files = sorted(files_with_high.items(), key=lambda x: len(x[1]), reverse=True)
    
    for file_path, patterns in sorted_files[:10]:  # Top 10
        print(f"{len(patterns):2d} issues: {file_path}")
        
        # Show the most critical pattern from each file
        for pattern in patterns[:1]:  # Just show first pattern per file
            print(f"    Line {pattern.line_number}: {pattern.pattern_type}")
            print(f"    Context: {pattern.context}")
            print(f"    Fix: {pattern.suggested_fix[:100]}...")
            print()


def show_pattern_statistics(base_path: str):
    """Show detailed statistics about N+1 patterns"""
    print("📊 N+1 PATTERN STATISTICS")
    print("=" * 50)
    
    scanner = N1CodebaseScanner(base_path)
    all_patterns = scanner.scan_codebase(exclude_tests=True)
    
    # Pattern type analysis
    pattern_counts = {}
    severity_counts = {'high': 0, 'medium': 0, 'low': 0}
    
    for pattern in all_patterns:
        pattern_type = pattern.pattern_type
        pattern_counts[pattern_type] = pattern_counts.get(pattern_type, 0) + 1
        severity_counts[pattern.severity] += 1
    
    print("📋 PATTERN TYPES:")
    for pattern_type, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {count:3d} - {pattern_type}")
    
    print("\n🔥 SEVERITY DISTRIBUTION:")
    total = sum(severity_counts.values())
    for severity, count in severity_counts.items():
        percentage = (count / total) * 100 if total > 0 else 0
        print(f"  {severity.upper():6s}: {count:3d} ({percentage:5.1f}%)")
    
    print(f"\n📁 TOTAL FILES AFFECTED: {len(scanner.file_stats)}")
    print(f"🔍 TOTAL PATTERNS FOUND: {total}")


def analyze_api_endpoints(base_path: str):
    """Focus analysis on API endpoints and public-facing code"""
    print("🌐 API ENDPOINT N+1 ANALYSIS") 
    print("=" * 50)
    
    scanner = N1CodebaseScanner(base_path)
    all_patterns = scanner.scan_codebase(exclude_tests=True)
    
    # Filter patterns from API-related files
    api_keywords = ['api/', 'templates/pages/', 'webhook', 'whitelist']
    api_patterns = []
    
    for pattern in all_patterns:
        file_path = pattern.file_path.lower()
        context = pattern.context.lower()
        
        if any(keyword in file_path or keyword in context for keyword in api_keywords):
            api_patterns.append(pattern)
    
    print(f"🎯 API-RELATED PATTERNS: {len(api_patterns)}")
    
    # Group by severity
    api_high = [p for p in api_patterns if p.severity == 'high']
    api_medium = [p for p in api_patterns if p.severity == 'medium'] 
    
    print(f"   High severity: {len(api_high)}")
    print(f"   Medium severity: {len(api_medium)}")
    
    if api_high:
        print("\n🚨 CRITICAL API ISSUES:")
        print("-" * 30)
        
        for pattern in api_high[:5]:  # Show top 5
            relative_path = str(Path(pattern.file_path).relative_to(Path(base_path)))
            print(f"📍 {relative_path}:{pattern.line_number}")
            print(f"   Pattern: {pattern.pattern_type}")
            print(f"   Context: {pattern.context}")
            print(f"   Fix: {pattern.suggested_fix}")
            print()


def main():
    """Main entry point with different analysis modes"""
    if len(sys.argv) < 2:
        print("Usage: python run_n_plus_one_analysis.py <mode> [app_path]")
        print("\nModes:")
        print("  full      - Complete analysis with full report")
        print("  high      - High-priority issues only") 
        print("  stats     - Pattern statistics")
        print("  api       - API endpoint analysis")
        print("  bench     - Run from bench environment")
        return
    
    mode = sys.argv[1]
    app_path = sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).parent.parent)
    
    try:
        if mode == 'full':
            scanner = N1CodebaseScanner(app_path)
            patterns = scanner.scan_codebase(exclude_tests=True)
            report = scanner.generate_report()
            print(report)
            
        elif mode == 'high':
            analyze_high_priority_only(app_path)
            
        elif mode == 'stats':
            show_pattern_statistics(app_path)
            
        elif mode == 'api':
            analyze_api_endpoints(app_path)
            
        elif mode == 'bench':
            # Use the existing run_scan function for bench integration
            patterns = run_scan()
            print(f"\n✅ Analysis complete. Found {len(patterns)} patterns.")
            
        else:
            print(f"Unknown mode: {mode}")
            
    except Exception as e:
        print(f"❌ Error running analysis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()