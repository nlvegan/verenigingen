#!/usr/bin/env python3
"""
Phase 4 Test Infrastructure Analysis
Comprehensive analysis of all 427 test files to categorize by purpose and value
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Set
from collections import defaultdict

class Phase4TestAnalyzer:
    """Analyzer for Phase 4 testing infrastructure rationalization"""
    
    def __init__(self, app_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.app_path = Path(app_path)
        self.test_files = []
        self.analysis_results = {}
        
        # Categorization patterns based on Phase 4 specifications
        self.categorization_patterns = {
            'CORE_BUSINESS': [
                r'test_member\.py$',
                r'test_membership\.py$', 
                r'test_volunteer\.py$',
                r'test_chapter\.py$',
                r'test_sepa_mandate\.py$',
                r'test_payment.*\.py$',
                r'test_invoice.*\.py$',
                r'test_member_lifecycle.*\.py$',
                r'test_membership_application.*\.py$',
                r'test_termination.*\.py$',
                r'test_dues.*\.py$'
            ],
            'EDGE_CASES': [
                r'.*edge_cases.*\.py$',
                r'.*comprehensive.*\.py$',
                r'.*regression.*\.py$',
                r'.*validation.*\.py$',
                r'.*security.*\.py$',
                r'.*performance.*\.py$',
                r'.*stress.*\.py$'
            ],
            'INTEGRATION': [
                r'.*integration.*\.py$',
                r'.*workflow.*\.py$',
                r'.*api.*\.py$',
                r'.*portal.*\.py$',
                r'.*dashboard.*\.py$',
                r'test_complete.*\.py$',
                r'test_end_to_end.*\.py$'
            ],
            'DEBUG_TEMP': [
                r'.*debug.*\.py$',
                r'.*temp.*\.py$',
                r'.*test_runner.*\.py$',
                r'.*smoke.*\.py$',
                r'.*simple.*\.py$',
                r'.*fix.*\.py$',
                r'.*patch.*\.py$',
                r'.*example.*\.py$',
                r'.*demo.*\.py$'
            ],
            'DUPLICATE': [
                r'.*_v2.*\.py$',
                r'.*_new.*\.py$', 
                r'.*_old.*\.py$',
                r'.*_backup.*\.py$',
                r'.*_copy.*\.py$',
                r'.*_working.*\.py$',
                r'.*_final.*\.py$'
            ]
        }
        
    def discover_test_files(self) -> List[Path]:
        """Discover all test files in the codebase"""
        test_files = []
        
        # Search all Python test files
        for test_file in self.app_path.rglob("test_*.py"):
            if test_file.is_file():
                test_files.append(test_file)
                
        print(f"📊 Discovered {len(test_files)} test files")
        return sorted(test_files)
    
    def analyze_test_file(self, test_file: Path) -> Dict:
        """Analyze individual test file for categorization"""
        analysis = {
            'path': str(test_file),
            'relative_path': str(test_file.relative_to(self.app_path)),
            'filename': test_file.name,
            'directory': str(test_file.parent),
            'size_bytes': test_file.stat().st_size,
            'line_count': 0,
            'test_method_count': 0,
            'has_base_test_case': False,
            'has_frappe_test_case': False,
            'has_unittest': False,
            'imports_factories': False,
            'category': 'UNKNOWN',
            'category_confidence': 0.0,
            'category_reasons': [],
            'complexity_score': 0,
            'business_value_score': 0,
            'maintenance_burden': 0,
            'recommendation': 'ANALYZE'
        }
        
        try:
            # Read and analyze file content
            content = test_file.read_text(encoding='utf-8')
            analysis['line_count'] = len(content.splitlines())
            
            # Count test methods
            test_methods = re.findall(r'def test_\w+\(', content)
            analysis['test_method_count'] = len(test_methods)
            
            # Check test framework usage
            analysis['has_base_test_case'] = 'VereningingenTestCase' in content or 'BaseTestCase' in content
            analysis['has_frappe_test_case'] = 'FrappeTestCase' in content
            analysis['has_unittest'] = 'unittest.TestCase' in content
            analysis['imports_factories'] = 'TestDataFactory' in content or 'test_data_factory' in content
            
            # Categorize based on patterns
            analysis['category'], analysis['category_confidence'], analysis['category_reasons'] = self.categorize_test_file(test_file, content)
            
            # Calculate complexity and value scores
            analysis['complexity_score'] = self.calculate_complexity_score(content, analysis)
            analysis['business_value_score'] = self.calculate_business_value_score(test_file, content, analysis)
            analysis['maintenance_burden'] = self.calculate_maintenance_burden(content, analysis)
            
            # Generate recommendation
            analysis['recommendation'] = self.generate_recommendation(analysis)
            
        except Exception as e:
            print(f"⚠️  Error analyzing {test_file}: {e}")
            analysis['error'] = str(e)
            
        return analysis
    
    def categorize_test_file(self, test_file: Path, content: str) -> Tuple[str, float, List[str]]:
        """Categorize test file based on patterns and content"""
        scores = defaultdict(list)
        reasons = []
        
        filename = test_file.name
        relative_path = str(test_file.relative_to(self.app_path))
        
        # Check filename patterns
        for category, patterns in self.categorization_patterns.items():
            for pattern in patterns:
                if re.search(pattern, filename, re.IGNORECASE):
                    scores[category].append(0.8)
                    reasons.append(f"Filename matches {category} pattern: {pattern}")
        
        # Check path patterns
        if 'archived' in relative_path or 'unused' in relative_path:
            scores['DEBUG_TEMP'].append(0.9)
            reasons.append("Located in archived/unused directory")
        elif 'integration' in relative_path:
            scores['INTEGRATION'].append(0.7)
            reasons.append("Located in integration directory")
        elif 'validation' in relative_path:
            scores['EDGE_CASES'].append(0.7)
            reasons.append("Located in validation directory")
        
        # Content-based categorization
        if 'class.*Test.*unittest.TestCase' in content:
            scores['DEBUG_TEMP'].append(0.5)
            reasons.append("Uses basic unittest framework")
        elif 'VereningingenTestCase' in content or 'BaseTestCase' in content:
            scores['CORE_BUSINESS'].append(0.6)
            reasons.append("Uses enhanced test framework")
        
        # Check for business logic keywords
        business_keywords = ['member', 'payment', 'invoice', 'sepa', 'volunteer', 'chapter', 'membership']
        for keyword in business_keywords:
            if keyword in filename.lower() and not any(temp in filename.lower() for temp in ['debug', 'temp', 'fix']):
                scores['CORE_BUSINESS'].append(0.4)
                reasons.append(f"Contains business keyword: {keyword}")
                break
        
        # Determine best category
        if not scores:
            return 'UNKNOWN', 0.0, ['No categorization patterns matched']
        
        # Calculate average scores for each category
        category_averages = {cat: sum(score_list) / len(score_list) for cat, score_list in scores.items()}
        best_category = max(category_averages.keys(), key=lambda k: category_averages[k])
        confidence = category_averages[best_category]
        
        return best_category, confidence, reasons
    
    def calculate_complexity_score(self, content: str, analysis: Dict) -> int:
        """Calculate complexity score (0-100)"""
        score = 0
        
        # Base score from line count
        score += min(analysis['line_count'] // 10, 30)
        
        # Test method count
        score += min(analysis['test_method_count'] * 2, 20)
        
        # Framework sophistication
        if analysis['has_base_test_case']:
            score += 10
        elif analysis['has_frappe_test_case']:
            score += 5
        
        # Complex patterns
        if 'mock' in content.lower():
            score += 5
        if 'patch' in content.lower():
            score += 5
        if 'setUp' in content or 'tearDown' in content:
            score += 5
        if 'frappe.db.sql' in content:
            score += 10
        
        return min(score, 100)
    
    def calculate_business_value_score(self, test_file: Path, content: str, analysis: Dict) -> int:
        """Calculate business value score (0-100)"""
        score = 0
        
        # Core business logic tests have high value
        if analysis['category'] == 'CORE_BUSINESS':
            score += 50
        elif analysis['category'] == 'INTEGRATION':
            score += 30
        elif analysis['category'] == 'EDGE_CASES':
            score += 20
        
        # Business domain coverage
        business_domains = {
            'member': 20, 'payment': 20, 'invoice': 15, 'sepa': 15,
            'volunteer': 10, 'chapter': 10, 'membership': 15
        }
        
        filename_lower = test_file.name.lower()
        for domain, value in business_domains.items():
            if domain in filename_lower:
                score += value
                break
        
        # Framework quality
        if analysis['has_base_test_case']:
            score += 10
        if analysis['imports_factories']:
            score += 5
        
        # Comprehensive tests
        if 'comprehensive' in filename_lower:
            score += 10
        
        return min(score, 100)
    
    def calculate_maintenance_burden(self, content: str, analysis: Dict) -> int:
        """Calculate maintenance burden score (0-100, higher = more burden)"""
        burden = 0
        
        # Complex setup/teardown
        if 'setUp' in content or 'tearDown' in content:
            burden += 10
        
        # Raw SQL usage
        burden += content.count('frappe.db.sql') * 5
        
        # Mock/patch complexity
        burden += content.count('mock') * 2
        burden += content.count('patch') * 2
        
        # Hardcoded values
        burden += content.count('CUST-') * 1  # Hardcoded customer IDs
        burden += content.count('SI-') * 1    # Hardcoded invoice IDs
        
        # File size burden
        if analysis['line_count'] > 500:
            burden += 20
        elif analysis['line_count'] > 200:
            burden += 10
        
        # Category-specific burden
        if analysis['category'] == 'DEBUG_TEMP':
            burden += 30
        elif analysis['category'] == 'DUPLICATE':
            burden += 40
        
        return min(burden, 100)
    
    def generate_recommendation(self, analysis: Dict) -> str:
        """Generate recommendation for test file"""
        category = analysis['category']
        business_value = analysis['business_value_score']
        maintenance_burden = analysis['maintenance_burden']
        confidence = analysis['category_confidence']
        
        if category == 'DEBUG_TEMP' or category == 'DUPLICATE':
            return 'REMOVE'
        elif category == 'CORE_BUSINESS' and business_value >= 50:
            return 'KEEP'
        elif category == 'INTEGRATION' and business_value >= 30:
            return 'KEEP'
        elif category == 'EDGE_CASES':
            if maintenance_burden > 50:
                return 'CONSOLIDATE'
            else:
                return 'KEEP'
        elif business_value < 20 and maintenance_burden > 40:
            return 'REMOVE'
        elif confidence < 0.5:
            return 'MANUAL_REVIEW'
        else:
            return 'CONSOLIDATE'
    
    def run_comprehensive_analysis(self) -> Dict:
        """Run comprehensive analysis of all test files"""
        print("🔍 Starting Phase 4 Test Infrastructure Analysis...")
        
        # Discover all test files
        self.test_files = self.discover_test_files()
        
        # Analyze each file
        analyses = []
        for i, test_file in enumerate(self.test_files, 1):
            print(f"📝 Analyzing {i}/{len(self.test_files)}: {test_file.name}")
            analysis = self.analyze_test_file(test_file)
            analyses.append(analysis)
        
        # Generate summary statistics
        summary = self.generate_summary_statistics(analyses)
        
        # Create consolidation plan
        consolidation_plan = self.create_consolidation_plan(analyses)
        
        results = {
            'metadata': {
                'total_files': len(self.test_files),
                'analysis_timestamp': '2025-07-28',
                'analyzer_version': '1.0.0'
            },
            'summary': summary,
            'consolidation_plan': consolidation_plan,
            'detailed_analyses': analyses
        }
        
        return results
    
    def generate_summary_statistics(self, analyses: List[Dict]) -> Dict:
        """Generate summary statistics from analyses"""
        summary = {
            'total_files': len(analyses),
            'total_lines': sum(a['line_count'] for a in analyses),
            'total_test_methods': sum(a['test_method_count'] for a in analyses),
            'by_category': defaultdict(int),
            'by_recommendation': defaultdict(int),
            'framework_usage': {
                'VereningingenTestCase': 0,
                'FrappeTestCase': 0,
                'unittest': 0,
                'unknown': 0
            },
            'average_scores': {
                'complexity': 0,
                'business_value': 0,
                'maintenance_burden': 0
            }
        }
        
        for analysis in analyses:
            summary['by_category'][analysis['category']] += 1
            summary['by_recommendation'][analysis['recommendation']] += 1
            
            if analysis['has_base_test_case']:
                summary['framework_usage']['VereningingenTestCase'] += 1
            elif analysis['has_frappe_test_case']:
                summary['framework_usage']['FrappeTestCase'] += 1
            elif analysis['has_unittest']:
                summary['framework_usage']['unittest'] += 1
            else:
                summary['framework_usage']['unknown'] += 1
        
        # Calculate averages
        if analyses:
            summary['average_scores']['complexity'] = sum(a['complexity_score'] for a in analyses) / len(analyses)
            summary['average_scores']['business_value'] = sum(a['business_value_score'] for a in analyses) / len(analyses)
            summary['average_scores']['maintenance_burden'] = sum(a['maintenance_burden'] for a in analyses) / len(analyses)
        
        return dict(summary)
    
    def create_consolidation_plan(self, analyses: List[Dict]) -> Dict:
        """Create specific consolidation plan for Phase 4.2"""
        plan = {
            'files_to_remove': [],
            'files_to_keep': [],
            'consolidation_groups': [],
            'manual_review_required': [],
            'migration_to_enhanced_framework': []
        }
        
        # Group by recommendation
        by_recommendation = defaultdict(list)
        for analysis in analyses:
            by_recommendation[analysis['recommendation']].append(analysis)
        
        # Files to remove
        plan['files_to_remove'] = by_recommendation['REMOVE']
        
        # Files to keep as-is
        plan['files_to_keep'] = by_recommendation['KEEP']
        
        # Manual review needed
        plan['manual_review_required'] = by_recommendation['MANUAL_REVIEW']
        
        # Create consolidation groups for CONSOLIDATE recommendation
        consolidate_files = by_recommendation['CONSOLIDATE']
        plan['consolidation_groups'] = self.create_consolidation_groups(consolidate_files)
        
        # Find files that should migrate to enhanced framework
        for analysis in analyses:
            if not analysis['has_base_test_case'] and analysis['business_value_score'] >= 30:
                plan['migration_to_enhanced_framework'].append(analysis)
        
        return plan
    
    def create_consolidation_groups(self, consolidate_files: List[Dict]) -> List[Dict]:
        """Create consolidation groups for similar test files"""
        groups = []
        
        # Group by business domain
        domain_groups = defaultdict(list)
        for analysis in consolidate_files:
            filename = analysis['filename'].lower()
            
            # Determine primary domain
            domain = 'other'
            if 'member' in filename:
                domain = 'member'
            elif 'payment' in filename:
                domain = 'payment'
            elif 'volunteer' in filename:
                domain = 'volunteer'
            elif 'sepa' in filename:
                domain = 'sepa'
            elif 'chapter' in filename:
                domain = 'chapter'
            elif 'invoice' in filename:
                domain = 'invoice'
            
            domain_groups[domain].append(analysis)
        
        # Create consolidation groups
        for domain, files in domain_groups.items():
            if len(files) >= 2:  # Only consolidate if multiple files
                groups.append({
                    'domain': domain,
                    'files': files,
                    'suggested_name': f'test_{domain}_comprehensive.py',
                    'consolidation_reason': f'Multiple {domain} test files can be consolidated',
                    'estimated_reduction': len(files) - 1
                })
        
        return groups
    
    def save_analysis_results(self, results: Dict, output_file: str = None):
        """Save analysis results to JSON file"""
        if output_file is None:
            output_file = f"{self.app_path}/phase4_test_analysis_results.json"
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"💾 Analysis results saved to: {output_file}")
    
    def print_summary_report(self, results: Dict):
        """Print summary report to console"""
        summary = results['summary'] 
        plan = results['consolidation_plan']
        
        print("\n" + "="*80)
        print("📊 PHASE 4 TEST INFRASTRUCTURE ANALYSIS SUMMARY")
        print("="*80)
        
        print(f"\n📁 TOTAL FILES ANALYZED: {summary['total_files']}")
        print(f"📝 TOTAL LINES OF CODE: {summary['total_lines']:,}")
        print(f"🧪 TOTAL TEST METHODS: {summary['total_test_methods']:,}")
        
        print(f"\n📊 CATEGORIZATION RESULTS:")
        for category, count in summary['by_category'].items():
            percentage = (count / summary['total_files']) * 100
            print(f"  {category:15}: {count:3d} files ({percentage:5.1f}%)")
        
        print(f"\n🎯 RECOMMENDATIONS:")
        for recommendation, count in summary['by_recommendation'].items():
            percentage = (count / summary['total_files']) * 100
            print(f"  {recommendation:20}: {count:3d} files ({percentage:5.1f}%)")
        
        print(f"\n🏗️  FRAMEWORK USAGE:")
        for framework, count in summary['framework_usage'].items():
            percentage = (count / summary['total_files']) * 100
            print(f"  {framework:20}: {count:3d} files ({percentage:5.1f}%)")
        
        print(f"\n⚡ AVERAGE SCORES:")
        print(f"  Complexity:          {summary['average_scores']['complexity']:5.1f}/100")
        print(f"  Business Value:      {summary['average_scores']['business_value']:5.1f}/100")
        print(f"  Maintenance Burden:  {summary['average_scores']['maintenance_burden']:5.1f}/100")
        
        print(f"\n🎯 CONSOLIDATION PLAN SUMMARY:")
        print(f"  Files to Remove:     {len(plan['files_to_remove']):3d}")
        print(f"  Files to Keep:       {len(plan['files_to_keep']):3d}")
        print(f"  Consolidation Groups: {len(plan['consolidation_groups']):3d}")
        print(f"  Manual Review:       {len(plan['manual_review_required']):3d}")
        print(f"  Framework Migration: {len(plan['migration_to_enhanced_framework']):3d}")
        
        # Calculate projected reduction
        files_removed = len(plan['files_to_remove'])
        files_consolidated = sum(group['estimated_reduction'] for group in plan['consolidation_groups'])
        total_reduction = files_removed + files_consolidated
        final_count = summary['total_files'] - total_reduction
        reduction_percentage = (total_reduction / summary['total_files']) * 100
        
        print(f"\n📈 PROJECTED OUTCOME:")
        print(f"  Current Files:       {summary['total_files']:3d}")
        print(f"  Files to Remove:     {files_removed:3d}")
        print(f"  Files Consolidated:  {files_consolidated:3d}")
        print(f"  Final File Count:    {final_count:3d}")
        print(f"  Reduction:           {total_reduction:3d} files ({reduction_percentage:.1f}%)")
        print(f"  Target (30% reduction): {int(summary['total_files'] * 0.7):3d} files")
        
        if reduction_percentage >= 30:
            print("  ✅ Target reduction achieved!")
        else:
            print("  ⚠️  Additional consolidation needed to reach 30% target")
        
        print("\n" + "="*80)

def main():
    """Main function for command-line usage"""
    analyzer = Phase4TestAnalyzer()
    results = analyzer.run_comprehensive_analysis()
    
    # Save results
    analyzer.save_analysis_results(results)
    
    # Print summary
    analyzer.print_summary_report(results)
    
    print(f"\n🎯 Next Steps:")
    print(f"1. Review detailed analysis in phase4_test_analysis_results.json")
    print(f"2. Execute Phase 4.2 consolidation plan")
    print(f"3. Migrate remaining tests to VereningingenTestCase framework")
    print(f"4. Streamline TestDataFactory methods")

if __name__ == "__main__":
    main()