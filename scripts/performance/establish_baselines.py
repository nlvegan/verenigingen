#!/usr/bin/env python3
"""
Performance Baseline Establishment Script

This script establishes baseline performance measurements before implementing
any changes. These baselines will be used to validate performance improvements.
"""

import time
import cProfile
import pstats
import json
import os
from datetime import datetime
from typing import Dict, Any, List
import frappe
from frappe.utils import cint


def establish_performance_baselines():
    """Create baseline performance measurements for all critical operations"""
    print("Establishing Performance Baselines")
    print("=" * 60)
    
    baselines = {
        'timestamp': datetime.now().isoformat(),
        'environment': get_environment_info(),
        'measurements': {}
    }
    
    # 1. Payment History Loading Performance
    print("\n1. Measuring Payment History Loading Performance...")
    baselines['measurements']['payment_history_load'] = profile_payment_history_loading()
    
    # 2. Member Search Performance
    print("\n2. Measuring Member Search Performance...")
    baselines['measurements']['member_search'] = profile_member_search()
    
    # 3. API Response Times
    print("\n3. Measuring API Response Times...")
    baselines['measurements']['api_response_times'] = profile_api_endpoints()
    
    # 4. Database Query Performance
    print("\n4. Measuring Database Query Performance...")
    baselines['measurements']['database_queries'] = profile_database_queries()
    
    # 5. Background Job Performance
    print("\n5. Measuring Background Job Performance...")
    baselines['measurements']['background_jobs'] = profile_background_jobs()
    
    # 6. Memory Usage
    print("\n6. Measuring Memory Usage...")
    baselines['measurements']['memory_usage'] = profile_memory_usage()
    
    # Save baselines
    save_baselines(baselines)
    
    # Generate summary report
    generate_baseline_report(baselines)
    
    return baselines


def get_environment_info() -> Dict[str, Any]:
    """Get current environment information"""
    return {
        'frappe_version': frappe.__version__,
        'site': frappe.local.site,
        'python_version': os.sys.version,
        'database': frappe.conf.db_type or 'mariadb',
        'workers': frappe.conf.workers or 1
    }


def profile_payment_history_loading() -> Dict[str, Any]:
    """Profile payment history loading performance"""
    start_time = time.time()
    query_count_start = get_query_count()
    
    results = {
        'total_members_tested': 0,
        'total_time': 0,
        'time_per_member': 0,
        'query_count': 0,
        'queries_per_member': 0,
        'profile_data': []
    }
    
    try:
        # Get sample of active members with payment history
        members = frappe.get_all(
            "Member",
            filters={
                "status": "Active",
                "payment_method": ["in", ["SEPA Direct Debit", "Bank Transfer"]]
            },
            fields=["name"],
            limit=50
        )
        
        results['total_members_tested'] = len(members)
        
        with cProfile.Profile() as profiler:
            for member in members:
                member_start = time.time()
                
                # Load member document
                member_doc = frappe.get_doc("Member", member.name)
                
                # Trigger payment history loading if method exists
                if hasattr(member_doc, 'load_payment_history'):
                    member_doc.load_payment_history()
                elif hasattr(member_doc, 'get_payment_history'):
                    member_doc.get_payment_history()
                elif hasattr(member_doc, 'payment_history'):
                    # Access payment history property
                    _ = member_doc.payment_history
                
                member_time = time.time() - member_start
                results['profile_data'].append({
                    'member': member.name,
                    'time': member_time
                })
        
        # Calculate metrics
        end_time = time.time()
        query_count_end = get_query_count()
        
        results['total_time'] = end_time - start_time
        results['time_per_member'] = results['total_time'] / max(results['total_members_tested'], 1)
        results['query_count'] = query_count_end - query_count_start
        results['queries_per_member'] = results['query_count'] / max(results['total_members_tested'], 1)
        
        # Get profiler stats
        stats = pstats.Stats(profiler)
        stats.sort_stats('tottime')
        
        # Extract top functions
        results['top_functions'] = extract_top_functions(stats, 10)
        
    except Exception as e:
        results['error'] = str(e)
        print(f"  Error profiling payment history: {e}")
    
    print(f"  Tested {results['total_members_tested']} members")
    print(f"  Total time: {results['total_time']:.2f}s")
    print(f"  Time per member: {results['time_per_member']:.3f}s")
    print(f"  Queries per member: {results['queries_per_member']:.1f}")
    
    return results


def profile_member_search() -> Dict[str, Any]:
    """Profile member search performance"""
    results = {
        'search_queries': [],
        'average_time': 0,
        'total_queries': 0
    }
    
    search_terms = [
        "john",
        "amsterdam",
        "test@example.com",
        "active",
        "2025"
    ]
    
    total_time = 0
    
    for term in search_terms:
        start_time = time.time()
        query_count_start = get_query_count()
        
        try:
            # Simulate member search
            search_results = frappe.get_all(
                "Member",
                filters=[
                    ["Member", "full_name", "like", f"%{term}%"],
                ],
                fields=["name", "full_name", "email", "member_id", "status"],
                limit=20
            )
            
            end_time = time.time()
            query_count_end = get_query_count()
            
            search_time = end_time - start_time
            total_time += search_time
            
            results['search_queries'].append({
                'term': term,
                'time': search_time,
                'result_count': len(search_results),
                'query_count': query_count_end - query_count_start
            })
            
        except Exception as e:
            results['search_queries'].append({
                'term': term,
                'error': str(e)
            })
    
    results['total_queries'] = len(search_terms)
    results['average_time'] = total_time / max(len(search_terms), 1)
    
    print(f"  Tested {len(search_terms)} search queries")
    print(f"  Average search time: {results['average_time']:.3f}s")
    
    return results


def profile_api_endpoints() -> Dict[str, Any]:
    """Profile critical API endpoint response times"""
    results = {
        'endpoints': [],
        'average_response_time': 0
    }
    
    # Define critical endpoints to test
    critical_endpoints = [
        {
            'name': 'get_member_list',
            'module': 'verenigingen.api.member_management',
            'method': 'get_member_list',
            'args': {'limit': 20}
        },
        {
            'name': 'get_payment_dashboard_data',
            'module': 'verenigingen.api.payment_dashboard',
            'method': 'get_payment_dashboard_data',
            'args': {}
        }
    ]
    
    total_time = 0
    successful_tests = 0
    
    for endpoint in critical_endpoints:
        start_time = time.time()
        
        try:
            # Try to call the API endpoint
            if frappe.get_attr(f"{endpoint['module']}.{endpoint['method']}"):
                result = frappe.call(
                    f"{endpoint['module']}.{endpoint['method']}",
                    **endpoint.get('args', {})
                )
                
                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # Convert to ms
                total_time += response_time
                successful_tests += 1
                
                results['endpoints'].append({
                    'name': endpoint['name'],
                    'response_time_ms': response_time,
                    'status': 'success'
                })
            else:
                results['endpoints'].append({
                    'name': endpoint['name'],
                    'status': 'not_found',
                    'error': 'Endpoint not found'
                })
                
        except Exception as e:
            results['endpoints'].append({
                'name': endpoint['name'],
                'status': 'error',
                'error': str(e)
            })
    
    if successful_tests > 0:
        results['average_response_time'] = total_time / successful_tests
    
    print(f"  Tested {len(critical_endpoints)} endpoints")
    print(f"  Average response time: {results['average_response_time']:.1f}ms")
    
    return results


def profile_database_queries() -> Dict[str, Any]:
    """Profile database query performance"""
    results = {
        'query_patterns': [],
        'slow_queries': []
    }
    
    # Common query patterns to test
    query_patterns = [
        {
            'name': 'active_members_count',
            'query': """
                SELECT COUNT(*) as count 
                FROM `tabMember` 
                WHERE status = 'Active'
            """
        },
        {
            'name': 'unpaid_invoices',
            'query': """
                SELECT COUNT(*) as count
                FROM `tabSales Invoice`
                WHERE status = 'Unpaid'
                AND docstatus = 1
            """
        },
        {
            'name': 'member_with_mandates',
            'query': """
                SELECT m.name, m.full_name, sm.iban
                FROM `tabMember` m
                LEFT JOIN `tabSEPA Mandate` sm ON sm.member = m.name
                WHERE m.status = 'Active'
                AND sm.status = 'Active'
                LIMIT 10
            """
        }
    ]
    
    for pattern in query_patterns:
        start_time = time.time()
        
        try:
            result = frappe.db.sql(pattern['query'], as_dict=True)
            end_time = time.time()
            
            query_time = (end_time - start_time) * 1000  # Convert to ms
            
            results['query_patterns'].append({
                'name': pattern['name'],
                'time_ms': query_time,
                'row_count': len(result) if isinstance(result, list) else 1
            })
            
            # Mark as slow query if > 100ms
            if query_time > 100:
                results['slow_queries'].append(pattern['name'])
                
        except Exception as e:
            results['query_patterns'].append({
                'name': pattern['name'],
                'error': str(e)
            })
    
    print(f"  Tested {len(query_patterns)} query patterns")
    print(f"  Slow queries (>100ms): {len(results['slow_queries'])}")
    
    return results


def profile_background_jobs() -> Dict[str, Any]:
    """Profile background job performance"""
    results = {
        'job_types': [],
        'queue_length': 0
    }
    
    # Check current queue lengths
    try:
        from frappe.utils.background_jobs import get_jobs
        
        queues = ['default', 'short', 'long']
        total_jobs = 0
        
        for queue in queues:
            jobs = len(get_jobs(queue=queue))
            total_jobs += jobs
            results[f'{queue}_queue_length'] = jobs
        
        results['queue_length'] = total_jobs
        
    except Exception as e:
        results['error'] = str(e)
    
    print(f"  Total jobs in queue: {results['queue_length']}")
    
    return results


def profile_memory_usage() -> Dict[str, Any]:
    """Profile current memory usage"""
    import psutil
    
    results = {}
    
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        
        results['rss_mb'] = memory_info.rss / 1024 / 1024  # Resident Set Size in MB
        results['vms_mb'] = memory_info.vms / 1024 / 1024  # Virtual Memory Size in MB
        results['percent'] = process.memory_percent()
        
        # System memory
        system_memory = psutil.virtual_memory()
        results['system_total_mb'] = system_memory.total / 1024 / 1024
        results['system_available_mb'] = system_memory.available / 1024 / 1024
        results['system_percent'] = system_memory.percent
        
    except Exception as e:
        results['error'] = str(e)
    
    print(f"  Process memory: {results.get('rss_mb', 0):.1f}MB")
    print(f"  System memory usage: {results.get('system_percent', 0):.1f}%")
    
    return results


def get_query_count() -> int:
    """Get current database query count from frappe"""
    try:
        return len(frappe.db.last_query) if hasattr(frappe.db, 'last_query') else 0
    except:
        return 0


def extract_top_functions(stats: pstats.Stats, limit: int = 10) -> List[Dict[str, Any]]:
    """Extract top functions from profiler stats"""
    top_functions = []
    
    try:
        stats_list = stats.get_stats_profile().func_profiles
        sorted_stats = sorted(stats_list.items(), key=lambda x: x[1].tottime, reverse=True)
        
        for i, (func, profile) in enumerate(sorted_stats[:limit]):
            top_functions.append({
                'function': f"{func[0]}:{func[1]}:{func[2]}",
                'total_time': profile.tottime,
                'calls': profile.ncalls
            })
    except:
        # Fallback if stats structure is different
        pass
    
    return top_functions


def save_baselines(baselines: Dict[str, Any]):
    """Save baselines to JSON file"""
    filename = 'performance_baselines.json'
    
    # Backup existing baselines if they exist
    if os.path.exists(filename):
        backup_name = f'performance_baselines_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        os.rename(filename, backup_name)
        print(f"\nExisting baselines backed up to: {backup_name}")
    
    with open(filename, 'w') as f:
        json.dump(baselines, f, indent=2, default=str)
    
    print(f"\nBaselines saved to: {filename}")


def generate_baseline_report(baselines: Dict[str, Any]):
    """Generate human-readable baseline report"""
    report = []
    report.append("\nPerformance Baseline Report")
    report.append("=" * 60)
    report.append(f"Generated: {baselines['timestamp']}")
    report.append(f"Environment: {baselines['environment']['frappe_version']}")
    report.append("")
    
    measurements = baselines['measurements']
    
    # Payment History Performance
    if 'payment_history_load' in measurements:
        ph = measurements['payment_history_load']
        report.append("Payment History Loading:")
        report.append(f"  - Time per member: {ph.get('time_per_member', 0):.3f}s")
        report.append(f"  - Queries per member: {ph.get('queries_per_member', 0):.1f}")
        report.append("")
    
    # API Performance
    if 'api_response_times' in measurements:
        api = measurements['api_response_times']
        report.append("API Response Times:")
        report.append(f"  - Average: {api.get('average_response_time', 0):.1f}ms")
        for endpoint in api.get('endpoints', []):
            if 'response_time_ms' in endpoint:
                report.append(f"  - {endpoint['name']}: {endpoint['response_time_ms']:.1f}ms")
        report.append("")
    
    # Database Performance
    if 'database_queries' in measurements:
        db = measurements['database_queries']
        report.append("Database Query Performance:")
        for query in db.get('query_patterns', []):
            if 'time_ms' in query:
                report.append(f"  - {query['name']}: {query['time_ms']:.1f}ms")
        if db.get('slow_queries'):
            report.append(f"  - Slow queries: {', '.join(db['slow_queries'])}")
        report.append("")
    
    # Memory Usage
    if 'memory_usage' in measurements:
        mem = measurements['memory_usage']
        report.append("Memory Usage:")
        report.append(f"  - Process: {mem.get('rss_mb', 0):.1f}MB")
        report.append(f"  - System: {mem.get('system_percent', 0):.1f}%")
    
    report_text = "\n".join(report)
    print(report_text)
    
    # Save report
    with open('performance_baseline_report.txt', 'w') as f:
        f.write(report_text)


if __name__ == "__main__":
    print("Performance Baseline Establishment Script")
    print("This will measure current performance metrics")
    print("")
    
    # Initialize frappe if needed
    if not frappe.db:
        import sys
        sys.path.insert(0, '/home/frappe/frappe-bench/sites')
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
    
    try:
        establish_performance_baselines()
    finally:
        if frappe.db:
            frappe.db.close()