#!/usr/bin/env python3
"""
Refactoring Metrics Validation Script

This script validates the actual measurable metrics from the 4-phase architectural 
refactoring to verify our coverage claims and identify gaps.
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, List, Set


def validate_refactoring_metrics():
    """
    Validate the actual metrics from the 4-phase refactoring
    """
    
    print("🔍 Validating 4-Phase Architectural Refactoring Metrics")
    print("=" * 70)
    
    metrics = {
        'timestamp': datetime.now().isoformat(),
        'security_analysis': {},
        'performance_analysis': {},
        'test_infrastructure_analysis': {},
        'architecture_analysis': {},
        'baseline_gaps': {},
        'verified_claims': {},
        'unverified_claims': {}
    }
    
    # 1. Security Coverage Validation
    print("\n1. Validating Security Coverage Claims...")
    metrics['security_analysis'] = analyze_security_coverage()
    
    # 2. Performance Measurement Analysis
    print("\n2. Analyzing Performance Claims...")
    metrics['performance_analysis'] = analyze_performance_claims()
    
    # 3. Test Infrastructure Quantification
    print("\n3. Quantifying Test Infrastructure...")
    metrics['test_infrastructure_analysis'] = analyze_test_infrastructure()
    
    # 4. Architecture Changes Assessment
    print("\n4. Assessing Architecture Changes...")
    metrics['architecture_analysis'] = analyze_architecture_changes()
    
    # 5. Identify Missing Baselines
    print("\n5. Identifying Baseline Gaps...")
    metrics['baseline_gaps'] = identify_baseline_gaps()
    
    # 6. Categorize Claims
    print("\n6. Categorizing Claims by Verifiability...")
    categorize_claims(metrics)
    
    # Generate comprehensive report
    generate_validation_report(metrics)
    
    return metrics


def analyze_security_coverage() -> Dict:
    """Analyze actual security coverage numbers"""
    
    analysis = {
        'total_api_files': 0,
        'financial_api_files': 0,
        'critical_api_decorated': 0,
        'actual_coverage_percentage': 0,
        'claimed_coverage_percentage': 91.7,
        'verification_status': 'PENDING'
    }
    
    api_dir = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    if not os.path.exists(api_dir):
        analysis['verification_status'] = 'ERROR - API directory not found'
        return analysis
    
    # Count total API files
    api_files = [f for f in os.listdir(api_dir) if f.endswith('.py') and f != '__init__.py']
    analysis['total_api_files'] = len(api_files)
    
    # Identify financial/critical API files
    financial_keywords = ['payment', 'sepa', 'invoice', 'financial', 'donor', 'batch', 'mandate']
    financial_apis = []
    critical_api_count = 0
    
    for filename in api_files:
        file_path = os.path.join(api_dir, filename)
        
        # Check if file contains financial operations
        is_financial = any(keyword in filename.lower() for keyword in financial_keywords)
        
        if is_financial:
            financial_apis.append(filename)
        
        # Count @critical_api decorators in file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                critical_api_count += content.count('@critical_api')
        except Exception as e:
            print(f"  Error reading {filename}: {e}")
    
    analysis['financial_api_files'] = len(financial_apis)
    
    # Count files with @critical_api decorators
    files_with_critical_api = 0
    for filename in api_files:
        file_path = os.path.join(api_dir, filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if '@critical_api' in content:
                    files_with_critical_api += 1
        except:
            continue
    
    analysis['critical_api_decorated'] = files_with_critical_api
    
    # Calculate actual coverage
    if analysis['financial_api_files'] > 0:
        # Count financial APIs with @critical_api
        secured_financial_apis = 0
        for filename in financial_apis:
            file_path = os.path.join(api_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if '@critical_api' in content:
                        secured_financial_apis += 1
            except:
                continue
        
        analysis['actual_coverage_percentage'] = round(
            (secured_financial_apis / analysis['financial_api_files']) * 100, 1
        )
    
    # Verify claim
    claimed_coverage = analysis['claimed_coverage_percentage']
    actual_coverage = analysis['actual_coverage_percentage']
    
    if abs(claimed_coverage - actual_coverage) <= 5:  # Allow 5% margin
        analysis['verification_status'] = 'VERIFIED'
    else:
        analysis['verification_status'] = f'DISPUTED - Claimed {claimed_coverage}%, Actual {actual_coverage}%'
    
    print(f"  📊 Total API files: {analysis['total_api_files']}")
    print(f"  💰 Financial API files: {analysis['financial_api_files']}")
    print(f"  🔒 Files with @critical_api: {analysis['critical_api_decorated']}")
    print(f"  📈 Actual coverage: {analysis['actual_coverage_percentage']}%")
    print(f"  ✅ Status: {analysis['verification_status']}")
    
    return analysis


def analyze_performance_claims() -> Dict:
    """Analyze performance improvement claims"""
    
    analysis = {
        'claimed_improvement': '16.76x improvement',
        'baseline_measurements_exist': False,
        'post_implementation_measurements_exist': False,
        'measurable_improvements': [],
        'verification_status': 'UNVERIFIABLE - No baseline measurements'
    }
    
    # Check for baseline measurement files
    baseline_files = [
        'performance_baselines.json',
        'performance_baseline_report.txt',
        'scripts/performance/establish_baselines.py'
    ]
    
    baseline_count = 0
    for filename in baseline_files:
        full_path = f'/home/frappe/frappe-bench/apps/verenigingen/{filename}'
        if os.path.exists(full_path):
            baseline_count += 1
            print(f"  📁 Found: {filename}")
    
    analysis['baseline_measurements_exist'] = baseline_count > 0
    
    # Look for performance-related improvements we can measure
    measurable_improvements = []
    
    # Check for SQL to ORM migrations
    sql_pattern_count = count_sql_patterns()
    if sql_pattern_count:
        measurable_improvements.append({
            'type': 'SQL Query Reduction',
            'metric': f'{sql_pattern_count} direct SQL calls found',
            'note': 'Could measure query efficiency improvements'
        })
    
    # Check for event handler optimizations
    event_handlers = count_event_handlers()
    if event_handlers:
        measurable_improvements.append({
            'type': 'Event Handler Optimization',
            'metric': f'{event_handlers} event handlers found',
            'note': 'Could measure processing time improvements'
        })
    
    analysis['measurable_improvements'] = measurable_improvements
    
    # Update verification status
    if analysis['baseline_measurements_exist']:
        analysis['verification_status'] = 'PARTIALLY_MEASURABLE - Baseline exists but no comparison'
    
    print(f"  📊 Baseline measurements exist: {analysis['baseline_measurements_exist']}")
    print(f"  📈 Measurable improvements identified: {len(measurable_improvements)}")
    print(f"  ✅ Status: {analysis['verification_status']}")
    
    return analysis


def analyze_test_infrastructure() -> Dict:
    """Quantify test infrastructure changes"""
    
    analysis = {
        'claimed_file_reduction': '427→302 files (29.3% reduction)',
        'actual_test_files': 0,
        'total_python_files': 0,
        'test_coverage_files': 0,
        'verification_status': 'PENDING'
    }
    
    # Count actual test files
    test_patterns = ['test_*.py', '*test*.py']
    test_files = []
    
    for root, dirs, files in os.walk('/home/frappe/frappe-bench/apps/verenigingen'):
        for file in files:
            if file.endswith('.py') and ('test' in file.lower() or file.startswith('test_')):
                test_files.append(os.path.join(root, file))
    
    analysis['actual_test_files'] = len(test_files)
    
    # Count total Python files
    python_files = []
    for root, dirs, files in os.walk('/home/frappe/frappe-bench/apps/verenigingen'):
        for file in files:
            if file.endswith('.py'):
                python_files.append(file)
    
    analysis['total_python_files'] = len(python_files)
    
    # Count test coverage-related files
    coverage_keywords = ['coverage', 'test_runner', 'base_test', 'factory']
    coverage_files = [f for f in test_files if any(keyword in f.lower() for keyword in coverage_keywords)]
    analysis['test_coverage_files'] = len(coverage_files)
    
    # Calculate test ratio
    test_ratio = (analysis['actual_test_files'] / analysis['total_python_files']) * 100
    analysis['test_ratio_percentage'] = round(test_ratio, 1)
    
    # Try to verify file reduction claim
    # Note: We can't verify historical reduction without version control history
    analysis['verification_status'] = 'UNVERIFIABLE - No historical baseline for file count'
    
    print(f"  📊 Current test files: {analysis['actual_test_files']}")
    print(f"  📁 Total Python files: {analysis['total_python_files']}")
    print(f"  📈 Test ratio: {analysis['test_ratio_percentage']}%")
    print(f"  🔧 Coverage infrastructure files: {analysis['test_coverage_files']}")
    print(f"  ✅ Status: {analysis['verification_status']}")
    
    return analysis


def analyze_architecture_changes() -> Dict:
    """Assess architecture change claims"""
    
    analysis = {
        'claimed_sql_to_orm': 'Unified data access',
        'claimed_service_layer': 'Service layer implementation',
        'claimed_mixin_consolidation': 'Mixin pattern consolidation',
        'actual_mixins_found': 0,
        'actual_service_files': 0,
        'actual_sql_usage': 0,
        'verification_status': 'PARTIAL'
    }
    
    # Count mixin usage
    mixin_count = 0
    for root, dirs, files in os.walk('/home/frappe/frappe-bench/apps/verenigingen'):
        for file in files:
            if 'mixin' in file.lower() and file.endswith('.py'):
                mixin_count += 1
    
    analysis['actual_mixins_found'] = mixin_count
    
    # Count service layer files
    service_patterns = ['service', 'manager', 'handler', 'processor']
    service_count = 0
    for root, dirs, files in os.walk('/home/frappe/frappe-bench/apps/verenigingen'):
        for file in files:
            if any(pattern in file.lower() for pattern in service_patterns) and file.endswith('.py'):
                service_count += 1
    
    analysis['actual_service_files'] = service_count
    
    # Count SQL usage (from earlier analysis)
    analysis['actual_sql_usage'] = count_sql_patterns()
    
    print(f"  🔧 Mixin files found: {analysis['actual_mixins_found']}")
    print(f"  🏗️ Service layer files: {analysis['actual_service_files']}")
    print(f"  💾 Direct SQL usage: {analysis['actual_sql_usage']}")
    print(f"  ✅ Status: {analysis['verification_status']}")
    
    return analysis


def identify_baseline_gaps() -> Dict:
    """Identify what baselines are missing"""
    
    gaps = {
        'missing_pre_measurements': [
            'Performance benchmarks before refactoring',
            'Security coverage before @critical_api implementation',
            'File count before cleanup',
            'Query performance before ORM migration'
        ],
        'missing_post_measurements': [
            'Current API response times',
            'Current memory usage patterns',
            'Current test execution times',
            'Current database query efficiency'
        ],
        'suggested_baselines_to_establish': [
            'API endpoint response time baselines',
            'Database query performance baselines',
            'Memory usage baselines',
            'Test suite execution time baselines',
            'Security audit baselines'
        ]
    }
    
    print(f"  ❌ Missing pre-measurements: {len(gaps['missing_pre_measurements'])}")
    print(f"  ❌ Missing post-measurements: {len(gaps['missing_post_measurements'])}")
    print(f"  💡 Suggested new baselines: {len(gaps['suggested_baselines_to_establish'])}")
    
    return gaps


def categorize_claims(metrics: Dict):
    """Categorize claims by their verifiability"""
    
    verified_claims = []
    unverified_claims = []
    
    # Security claims
    security = metrics['security_analysis']
    if security['verification_status'] == 'VERIFIED':
        verified_claims.append(f"Security coverage: {security['actual_coverage_percentage']}%")
    else:
        unverified_claims.append(f"Security coverage claim: {security['verification_status']}")
    
    # Performance claims
    performance = metrics['performance_analysis']
    unverified_claims.append("16.76x performance improvement - No baseline measurements")
    
    # Test infrastructure claims
    test_infra = metrics['test_infrastructure_analysis']
    verified_claims.append(f"Current test files: {test_infra['actual_test_files']}")
    unverified_claims.append("29.3% file reduction - No historical baseline")
    
    # Architecture claims
    arch = metrics['architecture_analysis']
    verified_claims.append(f"Mixin implementation: {arch['actual_mixins_found']} files")
    verified_claims.append(f"Service layer: {arch['actual_service_files']} files")
    
    metrics['verified_claims'] = {
        'count': len(verified_claims),
        'claims': verified_claims
    }
    
    metrics['unverified_claims'] = {
        'count': len(unverified_claims),
        'claims': unverified_claims
    }


def count_sql_patterns() -> int:
    """Count direct SQL usage patterns"""
    sql_count = 0
    
    for root, dirs, files in os.walk('/home/frappe/frappe-bench/apps/verenigingen'):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        sql_count += content.count('frappe.db.sql')
                except:
                    continue
    
    return sql_count


def count_event_handlers() -> int:
    """Count event handler implementations"""
    handler_count = 0
    
    # Check hooks.py for event handlers
    hooks_path = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py'
    if os.path.exists(hooks_path):
        try:
            with open(hooks_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Count various event handlers
                patterns = ['doc_events', 'on_update', 'before_save', 'after_insert', 'validate']
                for pattern in patterns:
                    handler_count += content.count(pattern)
        except:
            pass
    
    return handler_count


def generate_validation_report(metrics: Dict):
    """Generate comprehensive validation report"""
    
    report = []
    report.append("# 4-Phase Architectural Refactoring Metrics Validation Report")
    report.append(f"Generated: {metrics['timestamp']}")
    report.append("")
    
    # Executive Summary
    report.append("## Executive Summary")
    
    total_claims = metrics['verified_claims']['count'] + metrics['unverified_claims']['count']
    verified_percentage = (metrics['verified_claims']['count'] / total_claims) * 100 if total_claims > 0 else 0
    
    report.append(f"- **Total Claims Analyzed**: {total_claims}")
    report.append(f"- **Verified Claims**: {metrics['verified_claims']['count']} ({verified_percentage:.1f}%)")
    report.append(f"- **Unverified Claims**: {metrics['unverified_claims']['count']}")
    report.append("")
    
    # Security Analysis
    security = metrics['security_analysis']
    report.append("## Security Coverage Analysis")
    report.append(f"- **Claimed Coverage**: {security['claimed_coverage_percentage']}%")
    report.append(f"- **Actual Coverage**: {security['actual_coverage_percentage']}%")
    report.append(f"- **Verification Status**: {security['verification_status']}")
    report.append(f"- **Financial APIs Secured**: {security['critical_api_decorated']}/{security['financial_api_files']}")
    report.append("")
    
    # Performance Analysis
    performance = metrics['performance_analysis']
    report.append("## Performance Claims Analysis")
    report.append(f"- **Claimed Improvement**: {performance['claimed_improvement']}")
    report.append(f"- **Verification Status**: {performance['verification_status']}")
    report.append(f"- **Baseline Measurements Available**: {performance['baseline_measurements_exist']}")
    report.append("")
    
    # Test Infrastructure
    test_infra = metrics['test_infrastructure_analysis']
    report.append("## Test Infrastructure Analysis")
    report.append(f"- **Current Test Files**: {test_infra['actual_test_files']}")
    report.append(f"- **Test Coverage Ratio**: {test_infra['test_ratio_percentage']}%")
    report.append(f"- **Coverage Infrastructure Files**: {test_infra['test_coverage_files']}")
    report.append("")
    
    # Architecture Changes
    arch = metrics['architecture_analysis']
    report.append("## Architecture Changes Analysis")
    report.append(f"- **Mixin Files**: {arch['actual_mixins_found']}")
    report.append(f"- **Service Layer Files**: {arch['actual_service_files']}")
    report.append(f"- **Direct SQL Usage**: {arch['actual_sql_usage']} occurrences")
    report.append("")
    
    # Baseline Gaps
    gaps = metrics['baseline_gaps']
    report.append("## Missing Baseline Measurements")
    report.append("### Pre-Implementation Measurements (Missing)")
    for gap in gaps['missing_pre_measurements']:
        report.append(f"- {gap}")
    report.append("")
    
    report.append("### Post-Implementation Measurements (Missing)")
    for gap in gaps['missing_post_measurements']:
        report.append(f"- {gap}")
    report.append("")
    
    # Recommendations
    report.append("## Recommendations")
    report.append("### Immediate Actions Required")
    report.append("1. **Establish Current Baselines**: Run performance measurement tools to establish post-implementation baselines")
    report.append("2. **Security Audit**: Verify actual @critical_api coverage matches claims")
    report.append("3. **Performance Validation**: Create reproducible performance benchmarks")
    report.append("4. **Test Metrics**: Implement test execution time tracking")
    report.append("")
    
    report.append("### Future Baseline Requirements")
    for baseline in gaps['suggested_baselines_to_establish']:
        report.append(f"- {baseline}")
    report.append("")
    
    # Verified vs Unverified Claims
    report.append("## Claim Verification Summary")
    report.append("### Verified Claims ✅")
    for claim in metrics['verified_claims']['claims']:
        report.append(f"- {claim}")
    report.append("")
    
    report.append("### Unverified Claims ❌")
    for claim in metrics['unverified_claims']['claims']:
        report.append(f"- {claim}")
    report.append("")
    
    # Conclusion
    report.append("## Conclusion")
    
    if verified_percentage >= 70:
        report.append("**Status: ACCEPTABLE** - Most claims can be verified with available data.")
    elif verified_percentage >= 50:
        report.append("**Status: NEEDS IMPROVEMENT** - Significant gaps in measurement and verification.")
    else:
        report.append("**Status: CRITICAL GAPS** - Major issues with claim verification and baseline measurements.")
    
    report.append("")
    report.append("The analysis reveals that while some architectural improvements are measurable and verifiable, ")
    report.append("critical performance and reduction claims lack proper baseline measurements for validation.")
    
    # Save report
    report_text = "\n".join(report)
    
    with open('/home/frappe/frappe-bench/apps/verenigingen/refactoring_metrics_validation_report.md', 'w') as f:
        f.write(report_text)
    
    with open('/home/frappe/frappe-bench/apps/verenigingen/refactoring_metrics_validation.json', 'w') as f:
        json.dump(metrics, f, indent=2, default=str)
    
    print("\n" + "=" * 70)
    print("📊 VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Verified Claims: {metrics['verified_claims']['count']}/{total_claims} ({verified_percentage:.1f}%)")
    print(f"Security Coverage: {security['actual_coverage_percentage']}% (Claimed: {security['claimed_coverage_percentage']}%)")
    print(f"Performance Claims: UNVERIFIABLE - No baseline measurements")
    print(f"Test Infrastructure: {test_infra['actual_test_files']} test files found")
    print(f"Architecture: {arch['actual_mixins_found']} mixins, {arch['actual_service_files']} services")
    print("=" * 70)
    print("📄 Full report saved to: refactoring_metrics_validation_report.md")
    print("📊 Raw data saved to: refactoring_metrics_validation.json")


if __name__ == "__main__":
    validate_refactoring_metrics()