#!/usr/bin/env python3
"""
Performance Profiler Script
Phase 0 Infrastructure - Comprehensive Architectural Refactoring Plan v2.0

This script profiles actual payment processing bottlenecks and other
performance-critical operations to identify optimization targets.
"""

import cProfile
import pstats
import io
import time
import json
from typing import Dict, List, Any, Tuple
from datetime import datetime
import frappe

def profile_payment_operations() -> Dict[str, Any]:
    """
    Profile actual payment processing bottlenecks
    
    Returns:
        Detailed profiling results for payment operations
    """
    
    profiling_results = {
        'timestamp': datetime.now().isoformat(),
        'operations_profiled': {},
        'bottlenecks_identified': [],
        'optimization_recommendations': []
    }
    
    print("🔍 Profiling payment operations...")
    
    # Profile different payment operation scenarios
    operations = {
        'payment_batch_processing': profile_payment_batch_processing,
        'member_payment_history_generation': profile_member_payment_history_generation,
        'sepa_mandate_processing': profile_sepa_mandate_processing,
        'invoice_generation_batch': profile_invoice_generation_batch,
        'payment_reconciliation': profile_payment_reconciliation
    }
    
    for operation_name, operation_function in operations.items():
        print(f"   📊 Profiling {operation_name.replace('_', ' ')}...")
        try:
            profiling_results['operations_profiled'][operation_name] = operation_function()
        except Exception as e:
            profiling_results['operations_profiled'][operation_name] = {
                'error': f"Profiling failed: {e}"
            }
    
    # Analyze bottlenecks across all operations
    profiling_results['bottlenecks_identified'] = identify_performance_bottlenecks(
        profiling_results['operations_profiled']
    )
    
    # Generate optimization recommendations
    profiling_results['optimization_recommendations'] = generate_optimization_recommendations(
        profiling_results['bottlenecks_identified']
    )
    
    return profiling_results

def profile_payment_batch_processing() -> Dict[str, Any]:
    """Profile payment batch processing operations"""
    
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()
            
            # Simulate payment batch processing
            process_payment_batch_simulation(batch_size=100)
            
            end_time = time.time()
            total_time = end_time - start_time
        
        # Analyze profiler results
        analysis = analyze_profiler_results(profiler, 'payment_batch_processing')
        analysis['total_execution_time'] = round(total_time, 3)
        analysis['operations_per_second'] = round(100 / total_time, 2) if total_time > 0 else 0
        
        return analysis
        
    except Exception as e:
        return {'error': f"Payment batch profiling failed: {e}"}

def profile_member_payment_history_generation() -> Dict[str, Any]:
    """Profile member payment history generation"""
    
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()
            
            # Simulate payment history generation for multiple members
            generate_member_payment_history_simulation(member_count=50)
            
            end_time = time.time()
            total_time = end_time - start_time
        
        analysis = analyze_profiler_results(profiler, 'member_payment_history_generation')
        analysis['total_execution_time'] = round(total_time, 3)
        analysis['members_per_second'] = round(50 / total_time, 2) if total_time > 0 else 0
        
        return analysis
        
    except Exception as e:
        return {'error': f"Payment history profiling failed: {e}"}

def profile_sepa_mandate_processing() -> Dict[str, Any]:
    """Profile SEPA mandate processing operations"""
    
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()
            
            # Simulate SEPA mandate processing
            process_sepa_mandates_simulation(mandate_count=25)
            
            end_time = time.time()
            total_time = end_time - start_time
        
        analysis = analyze_profiler_results(profiler, 'sepa_mandate_processing')
        analysis['total_execution_time'] = round(total_time, 3)
        analysis['mandates_per_second'] = round(25 / total_time, 2) if total_time > 0 else 0
        
        return analysis
        
    except Exception as e:
        return {'error': f"SEPA mandate profiling failed: {e}"}

def profile_invoice_generation_batch() -> Dict[str, Any]:
    """Profile batch invoice generation operations"""
    
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()
            
            # Simulate batch invoice generation
            generate_invoices_batch_simulation(invoice_count=30)
            
            end_time = time.time()
            total_time = end_time - start_time
        
        analysis = analyze_profiler_results(profiler, 'invoice_generation_batch')
        analysis['total_execution_time'] = round(total_time, 3)
        analysis['invoices_per_second'] = round(30 / total_time, 2) if total_time > 0 else 0
        
        return analysis
        
    except Exception as e:
        return {'error': f"Invoice generation profiling failed: {e}"}

def profile_payment_reconciliation() -> Dict[str, Any]:
    """Profile payment reconciliation operations"""
    
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()
            
            # Simulate payment reconciliation
            reconcile_payments_simulation(payment_count=40)
            
            end_time = time.time()
            total_time = end_time - start_time
        
        analysis = analyze_profiler_results(profiler, 'payment_reconciliation')
        analysis['total_execution_time'] = round(total_time, 3)
        analysis['payments_per_second'] = round(40 / total_time, 2) if total_time > 0 else 0
        
        return analysis
        
    except Exception as e:
        return {'error': f"Payment reconciliation profiling failed: {e}"}

def process_payment_batch_simulation(batch_size: int):
    """Simulate payment batch processing"""
    
    # Get sample payment entries
    payments = frappe.get_all("Payment Entry", 
        fields=["name", "party", "paid_amount", "posting_date"],
        limit=batch_size,
        order_by="creation desc"
    )
    
    processed_count = 0
    
    for payment in payments:
        try:
            # Simulate payment processing operations
            payment_doc = frappe.get_doc("Payment Entry", payment.name)
            
            # Simulate related data lookups
            if payment_doc.party:
                # Look up member information
                member = frappe.get_all("Member", 
                    filters={"customer": payment_doc.party},
                    fields=["name", "full_name", "current_chapter_display"],
                    limit=1
                )
                
                # Look up related invoices
                invoices = frappe.get_all("Sales Invoice",
                    filters={"customer": payment_doc.party, "status": ["!=", "Cancelled"]},
                    fields=["name", "grand_total", "outstanding_amount"],
                    limit=10
                )
                
                # Simulate payment entry reference processing
                payment_refs = frappe.get_all("Payment Entry Reference",
                    filters={"parent": payment_doc.name},
                    fields=["reference_name", "allocated_amount"]
                )
            
            processed_count += 1
            
        except Exception:
            continue  # Skip problematic records
    
    return processed_count

def generate_member_payment_history_simulation(member_count: int):
    """Simulate member payment history generation"""
    
    # Get sample members
    members = frappe.get_all("Member",
        fields=["name", "customer", "full_name"],
        limit=member_count,
        filters={"status": "Active"}
    )
    
    histories_generated = 0
    
    for member in members:
        try:
            if not member.customer:
                continue
            
            # Simulate payment history generation
            # 1. Get all invoices for the member
            invoices = frappe.get_all("Sales Invoice",
                filters={"customer": member.customer},
                fields=["name", "grand_total", "outstanding_amount", "posting_date", "due_date"],
                order_by="posting_date desc"
            )
            
            # 2. Get all payment entries
            payments = frappe.get_all("Payment Entry",
                filters={"party": member.customer},
                fields=["name", "paid_amount", "posting_date"],
                order_by="posting_date desc"
            )
            
            # 3. Get SEPA mandates
            sepa_mandates = frappe.get_all("SEPA Mandate",
                filters={"member": member.name},
                fields=["name", "iban", "status", "creation"]
            )
            
            # 4. Simulate history compilation
            payment_history = {
                'member': member.name,
                'invoices': len(invoices),
                'payments': len(payments),
                'mandates': len(sepa_mandates),
                'total_invoiced': sum(inv.grand_total for inv in invoices if inv.grand_total),
                'total_paid': sum(pay.paid_amount for pay in payments if pay.paid_amount)
            }
            
            histories_generated += 1
            
        except Exception:
            continue
    
    return histories_generated

def process_sepa_mandates_simulation(mandate_count: int):
    """Simulate SEPA mandate processing"""
    
    # Get sample SEPA mandates
    mandates = frappe.get_all("SEPA Mandate",
        fields=["name", "member", "iban", "status"],
        limit=mandate_count,
        order_by="creation desc"
    )
    
    processed_mandates = 0
    
    for mandate in mandates:
        try:
            # Simulate mandate processing operations
            mandate_doc = frappe.get_doc("SEPA Mandate", mandate.name)
            
            # Get member information
            if mandate_doc.member:
                member_doc = frappe.get_doc("Member", mandate_doc.member)
                
                # Get related dues schedules
                dues_schedules = frappe.get_all("Membership Dues Schedule",
                    filters={"member": mandate_doc.member},
                    fields=["name", "dues_rate", "billing_frequency", "status"]
                )
                
                # Simulate validation operations
                if mandate_doc.iban:
                    # Validate IBAN format (simulation)
                    iban_validation = len(mandate_doc.iban) >= 15
                    
                # Check for active invoices
                if member_doc.customer:
                    active_invoices = frappe.get_all("Sales Invoice",
                        filters={
                            "customer": member_doc.customer,
                            "status": ["!=", "Paid"],
                            "outstanding_amount": [">", 0]
                        },
                        fields=["name", "outstanding_amount"]
                    )
            
            processed_mandates += 1
            
        except Exception:
            continue
    
    return processed_mandates

def generate_invoices_batch_simulation(invoice_count: int):
    """Simulate batch invoice generation"""
    
    # Get sample membership dues schedules
    schedules = frappe.get_all("Membership Dues Schedule",
        fields=["name", "member", "dues_rate", "billing_frequency"],
        limit=invoice_count,
        filters={"status": "Active"}
    )
    
    invoices_generated = 0
    
    for schedule in schedules:
        try:
            # Simulate invoice generation process
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
            
            # Get member information
            if schedule_doc.member:
                member_doc = frappe.get_doc("Member", schedule_doc.member)
                
                # Check if member has customer
                if not member_doc.customer:
                    continue
                
                # Simulate invoice creation data preparation
                invoice_data = {
                    'customer': member_doc.customer,
                    'posting_date': frappe.utils.today(),
                    'due_date': frappe.utils.add_days(frappe.utils.today(), 30),
                    'items': [{
                        'item_code': 'Membership Fee',  # Assuming this item exists
                        'rate': schedule_doc.dues_rate or 0,
                        'qty': 1
                    }]
                }
                
                # Simulate validation checks
                if invoice_data['items'][0]['rate'] > 0:
                    # Check for existing unpaid invoices
                    existing_invoices = frappe.get_all("Sales Invoice",
                        filters={
                            "customer": invoice_data['customer'],
                            "status": ["!=", "Paid"]
                        },
                        fields=["name"]
                    )
                    
                    invoices_generated += 1
            
        except Exception:
            continue
    
    return invoices_generated

def reconcile_payments_simulation(payment_count: int):
    """Simulate payment reconciliation operations"""
    
    # Get sample payment entries
    payments = frappe.get_all("Payment Entry",
        fields=["name", "party", "paid_amount", "unallocated_amount"],
        limit=payment_count,
        filters={"docstatus": 1}
    )
    
    reconciled_payments = 0
    
    for payment in payments:
        try:
            # Simulate reconciliation process
            payment_doc = frappe.get_doc("Payment Entry", payment.name)
            
            if payment_doc.party:
                # Get outstanding invoices for this party
                outstanding_invoices = frappe.get_all("Sales Invoice",
                    filters={
                        "customer": payment_doc.party,
                        "outstanding_amount": [">", 0],
                        "status": ["!=", "Cancelled"]
                    },
                    fields=["name", "outstanding_amount", "posting_date"],
                    order_by="posting_date asc"
                )
                
                # Get existing payment entry references
                existing_refs = frappe.get_all("Payment Entry Reference",
                    filters={"parent": payment_doc.name},
                    fields=["reference_name", "allocated_amount"]
                )
                
                # Simulate allocation logic
                total_allocated = sum(ref.allocated_amount for ref in existing_refs if ref.allocated_amount)
                remaining_amount = payment_doc.paid_amount - total_allocated
                
                # Simulate matching logic
                if remaining_amount > 0 and outstanding_invoices:
                    for invoice in outstanding_invoices:
                        if remaining_amount <= 0:
                            break
                        
                        allocation_amount = min(remaining_amount, invoice.outstanding_amount)
                        remaining_amount -= allocation_amount
                
                reconciled_payments += 1
            
        except Exception:
            continue
    
    return reconciled_payments

def analyze_profiler_results(profiler: cProfile.Profile, operation_name: str) -> Dict[str, Any]:
    """Analyze cProfile results and extract key metrics"""
    
    # Capture profiler output
    stats_stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stats_stream)
    stats.sort_stats('tottime')
    
    # Get top time-consuming functions
    top_functions = []
    for func_name, (call_count, total_calls, total_time, cumulative_time, callers) in stats.stats.items():
        if total_time > 0.001:  # Only include functions taking more than 1ms
            top_functions.append({
                'function': f"{func_name[0]}:{func_name[1]}({func_name[2]})",
                'total_time_seconds': round(total_time, 4),
                'cumulative_time_seconds': round(cumulative_time, 4),
                'call_count': total_calls,
                'time_per_call_ms': round((total_time / total_calls) * 1000, 2) if total_calls > 0 else 0
            })
    
    # Sort by total time and take top 20
    top_functions.sort(key=lambda x: x['total_time_seconds'], reverse=True)
    top_functions = top_functions[:20]
    
    # Calculate summary statistics
    total_function_time = sum(func['total_time_seconds'] for func in top_functions)
    database_time = sum(func['total_time_seconds'] for func in top_functions 
                       if 'sql' in func['function'].lower() or 'db' in func['function'].lower())
    
    analysis = {
        'operation_name': operation_name,
        'total_functions_analyzed': len(stats.stats),
        'top_time_consuming_functions': top_functions,
        'total_function_time_seconds': round(total_function_time, 3),
        'database_time_seconds': round(database_time, 3),
        'database_time_percentage': round((database_time / total_function_time) * 100, 1) if total_function_time > 0 else 0,
        'hotspots_identified': identify_function_hotspots(top_functions)
    }
    
    return analysis

def identify_function_hotspots(top_functions: List[Dict]) -> List[Dict]:
    """Identify performance hotspots from function analysis"""
    
    hotspots = []
    
    for func in top_functions[:10]:  # Focus on top 10 functions
        hotspot_type = 'UNKNOWN'
        
        func_name = func['function'].lower()
        
        if any(keyword in func_name for keyword in ['sql', 'db', 'query', 'execute']):
            hotspot_type = 'DATABASE'
        elif any(keyword in func_name for keyword in ['get_doc', 'get_all', 'get_value']):
            hotspot_type = 'FRAPPE_ORM'
        elif any(keyword in func_name for keyword in ['load', 'fetch', 'retrieve']):
            hotspot_type = 'DATA_LOADING'
        elif any(keyword in func_name for keyword in ['validate', 'check', 'verify']):
            hotspot_type = 'VALIDATION'
        elif any(keyword in func_name for keyword in ['loop', 'iterate', 'process']):
            hotspot_type = 'ITERATION'
        
        hotspots.append({
            'function': func['function'],
            'hotspot_type': hotspot_type,
            'time_seconds': func['total_time_seconds'],
            'call_count': func['call_count'],
            'severity': 'HIGH' if func['total_time_seconds'] > 0.1 else 'MEDIUM' if func['total_time_seconds'] > 0.05 else 'LOW'
        })
    
    return hotspots

def identify_performance_bottlenecks(operations_profiled: Dict[str, Any]) -> List[Dict]:
    """Identify performance bottlenecks across all profiled operations"""
    
    bottlenecks = []
    
    for operation_name, operation_data in operations_profiled.items():
        if 'error' in operation_data:
            continue
        
        # Check for slow operations
        execution_time = operation_data.get('total_execution_time', 0)
        if execution_time > 5:  # Operations taking more than 5 seconds
            bottlenecks.append({
                'operation': operation_name,
                'bottleneck_type': 'SLOW_EXECUTION',
                'severity': 'HIGH',
                'time_seconds': execution_time,
                'description': f"Operation takes {execution_time}s to complete"
            })
        
        # Check for low throughput
        throughput_metrics = [
            ('operations_per_second', 1),
            ('members_per_second', 2),
            ('mandates_per_second', 1),
            ('invoices_per_second', 2),
            ('payments_per_second', 3)
        ]
        
        for metric_name, threshold in throughput_metrics:
            if metric_name in operation_data:
                throughput = operation_data[metric_name]
                if throughput < threshold:
                    bottlenecks.append({
                        'operation': operation_name,
                        'bottleneck_type': 'LOW_THROUGHPUT',
                        'severity': 'MEDIUM',
                        'throughput': throughput,
                        'threshold': threshold,
                        'description': f"Low throughput: {throughput} {metric_name.replace('_', ' ')}"
                    })
        
        # Check for database-heavy operations
        db_time_percentage = operation_data.get('database_time_percentage', 0)
        if db_time_percentage > 70:  # More than 70% time spent in database operations
            bottlenecks.append({
                'operation': operation_name,
                'bottleneck_type': 'DATABASE_HEAVY',
                'severity': 'MEDIUM',
                'db_time_percentage': db_time_percentage,
                'description': f"Database operations consume {db_time_percentage}% of execution time"
            })
        
        # Check for function hotspots
        hotspots = operation_data.get('hotspots_identified', [])
        high_severity_hotspots = [h for h in hotspots if h.get('severity') == 'HIGH']
        
        if high_severity_hotspots:
            bottlenecks.append({
                'operation': operation_name,
                'bottleneck_type': 'FUNCTION_HOTSPOTS',
                'severity': 'HIGH',
                'hotspot_count': len(high_severity_hotspots),
                'top_hotspot': high_severity_hotspots[0]['function'],
                'description': f"{len(high_severity_hotspots)} high-severity function hotspots identified"
            })
    
    # Sort bottlenecks by severity
    severity_order = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
    bottlenecks.sort(key=lambda x: severity_order.get(x['severity'], 0), reverse=True)
    
    return bottlenecks

def generate_optimization_recommendations(bottlenecks: List[Dict]) -> List[Dict]:
    """Generate specific optimization recommendations based on identified bottlenecks"""
    
    recommendations = []
    
    # Group bottlenecks by type
    bottleneck_types = {}
    for bottleneck in bottlenecks:
        btype = bottleneck['bottleneck_type']
        if btype not in bottleneck_types:
            bottleneck_types[btype] = []
        bottleneck_types[btype].append(bottleneck)
    
    # Generate recommendations for each bottleneck type
    if 'SLOW_EXECUTION' in bottleneck_types:
        slow_operations = bottleneck_types['SLOW_EXECUTION']
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Slow Operations',
            'affected_operations': [op['operation'] for op in slow_operations],
            'recommendation': 'Convert slow synchronous operations to background jobs',
            'implementation': 'Use frappe.enqueue() for operations taking >2 seconds',
            'expected_improvement': '90% reduction in user-perceived response time'
        })
    
    if 'DATABASE_HEAVY' in bottleneck_types:
        db_heavy_operations = bottleneck_types['DATABASE_HEAVY']
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Database Optimization',
            'affected_operations': [op['operation'] for op in db_heavy_operations],
            'recommendation': 'Optimize database queries and add strategic indexes',
            'implementation': 'Add compound indexes on frequently queried fields, batch database operations',
            'expected_improvement': '50-70% reduction in database query time'
        })
    
    if 'LOW_THROUGHPUT' in bottleneck_types:
        low_throughput_operations = bottleneck_types['LOW_THROUGHPUT']
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'Throughput Optimization',
            'affected_operations': [op['operation'] for op in low_throughput_operations],
            'recommendation': 'Implement batch processing and caching strategies',
            'implementation': 'Process records in batches, cache frequently accessed data',
            'expected_improvement': '200-300% increase in processing throughput'
        })
    
    if 'FUNCTION_HOTSPOTS' in bottleneck_types:
        hotspot_operations = bottleneck_types['FUNCTION_HOTSPOTS']
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'Code Optimization',
            'affected_operations': [op['operation'] for op in hotspot_operations],
            'recommendation': 'Optimize high-time-consumption functions',
            'implementation': 'Refactor algorithms, reduce function call overhead, eliminate N+1 queries',
            'expected_improvement': '30-50% reduction in function execution time'
        })
    
    return recommendations

def save_profiling_results(results: Dict[str, Any]) -> str:
    """Save profiling results to file"""
    
    results_file = '/home/frappe/frappe-bench/apps/verenigingen/performance_profiling_results.json'
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    return results_file

def generate_profiling_report(results: Dict[str, Any]) -> str:
    """Generate a formatted profiling report"""
    
    report = []
    report.append("# Performance Profiling Report")
    report.append(f"Generated: {results.get('timestamp', 'Unknown')}")
    report.append("")
    
    # Operations summary
    operations = results.get('operations_profiled', {})
    successful_operations = [op for op in operations.values() if 'error' not in op]
    
    report.append("## Operations Summary")
    report.append(f"- **Total Operations Profiled**: {len(operations)}")
    report.append(f"- **Successful Profiles**: {len(successful_operations)}")
    report.append(f"- **Failed Profiles**: {len(operations) - len(successful_operations)}")
    report.append("")
    
    # Performance metrics
    if successful_operations:
        report.append("## Performance Metrics")
        for op_name, op_data in operations.items():
            if 'error' in op_data:
                continue
            
            report.append(f"### {op_name.replace('_', ' ').title()}")
            report.append(f"- **Execution Time**: {op_data.get('total_execution_time', 0)} seconds")
            
            # Add throughput metrics if available
            throughput_metrics = [
                ('operations_per_second', 'Operations/sec'),
                ('members_per_second', 'Members/sec'),
                ('mandates_per_second', 'Mandates/sec'),
                ('invoices_per_second', 'Invoices/sec'),
                ('payments_per_second', 'Payments/sec')
            ]
            
            for metric_key, metric_display in throughput_metrics:
                if metric_key in op_data:
                    report.append(f"- **Throughput**: {op_data[metric_key]} {metric_display}")
                    break
            
            # Database time percentage
            db_percentage = op_data.get('database_time_percentage', 0)
            if db_percentage > 0:
                report.append(f"- **Database Time**: {db_percentage}% of execution time")
            
            report.append("")
    
    # Bottlenecks
    bottlenecks = results.get('bottlenecks_identified', [])
    if bottlenecks:
        report.append("## Performance Bottlenecks")
        
        for bottleneck in bottlenecks:
            severity_icon = "🔴" if bottleneck['severity'] == 'HIGH' else "🟡" if bottleneck['severity'] == 'MEDIUM' else "🟢"
            report.append(f"### {severity_icon} {bottleneck['bottleneck_type'].replace('_', ' ').title()}")
            report.append(f"- **Operation**: {bottleneck['operation']}")
            report.append(f"- **Severity**: {bottleneck['severity']}")
            report.append(f"- **Description**: {bottleneck['description']}")
            report.append("")
    
    # Recommendations
    recommendations = results.get('optimization_recommendations', [])
    if recommendations:
        report.append("## Optimization Recommendations")
        
        for rec in recommendations:
            priority_icon = "⚡" if rec['priority'] == 'HIGH' else "⚠️" if rec['priority'] == 'MEDIUM' else "💡"
            report.append(f"### {priority_icon} {rec['priority']}: {rec['category']}")
            report.append(f"- **Affected Operations**: {', '.join(rec['affected_operations'])}")
            report.append(f"- **Recommendation**: {rec['recommendation']}")
            report.append(f"- **Implementation**: {rec['implementation']}")
            report.append(f"- **Expected Improvement**: {rec['expected_improvement']}")
            report.append("")
    
    return "\n".join(report)

def main():
    """Main execution function"""
    
    print("🚀 Starting Performance Profiling...")
    print("   This process will profile actual payment operations")
    print("   to identify specific performance bottlenecks.")
    print("")
    
    try:
        # Profile payment operations
        profiling_results = profile_payment_operations()
        
        # Save results
        results_file = save_profiling_results(profiling_results)
        
        # Generate report
        report = generate_profiling_report(profiling_results)
        
        # Save report
        report_file = '/home/frappe/frappe-bench/apps/verenigingen/performance_profiling_report.md'
        with open(report_file, 'w') as f:
            f.write(report)
        
        print("✅ Performance profiling completed successfully!")
        print(f"📊 Results saved to: {results_file}")
        print(f"📄 Report saved to: {report_file}")
        
        # Print summary
        operations_count = len(profiling_results.get('operations_profiled', {}))
        bottlenecks_count = len(profiling_results.get('bottlenecks_identified', []))
        recommendations_count = len(profiling_results.get('optimization_recommendations', []))
        
        print(f"📈 Profiled {operations_count} operations")
        print(f"🎯 Identified {bottlenecks_count} performance bottlenecks")
        print(f"💡 Generated {recommendations_count} optimization recommendations")
        
        # Show top bottleneck
        bottlenecks = profiling_results.get('bottlenecks_identified', [])
        if bottlenecks:
            top_bottleneck = bottlenecks[0]
            print(f"🔴 Top bottleneck: {top_bottleneck['bottleneck_type']} in {top_bottleneck['operation']}")
        
        print("")
        print("🎯 Use these results to prioritize Phase 2 performance optimizations.")
        
    except Exception as e:
        print(f"❌ Error during performance profiling: {e}")
        raise

if __name__ == '__main__':
    main()