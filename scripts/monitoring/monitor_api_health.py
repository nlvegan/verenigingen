#!/usr/bin/env python3
"""
API Health Monitoring Script

This script monitors API health during and after implementation phases.
It tracks response times, error rates, and security violations.
"""

import time
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import frappe
from frappe.utils import cint


class APIHealthMonitor:
    """Monitor API health and performance"""
    
    def __init__(self, duration_hours: int = 24):
        self.duration_hours = duration_hours
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(hours=duration_hours)
        self.metrics = {
            'start_time': self.start_time.isoformat(),
            'duration_hours': duration_hours,
            'api_calls': [],
            'summary': {
                'total_calls': 0,
                'successful_calls': 0,
                'failed_calls': 0,
                'error_rate': 0,
                'average_response_time': 0,
                'security_violations': 0
            }
        }
        
    def monitor_apis(self, api_list: List[str], check_interval: int = 300) -> Dict[str, Any]:
        """Monitor specified APIs for the duration"""
        print(f"Starting API health monitoring for {self.duration_hours} hours")
        print(f"Monitoring {len(api_list)} APIs with {check_interval}s intervals")
        print("=" * 60)
        
        while datetime.now() < self.end_time:
            current_time = datetime.now()
            print(f"\n[{current_time.strftime('%H:%M:%S')}] Running health check...")
            
            # Check each API
            for api_endpoint in api_list:
                self.check_api_health(api_endpoint)
            
            # Update summary
            self.update_summary()
            
            # Print current status
            self.print_current_status()
            
            # Save metrics
            self.save_metrics()
            
            # Wait for next check
            if datetime.now() < self.end_time:
                time.sleep(check_interval)
        
        # Generate final report
        final_report = self.generate_final_report()
        return final_report
    
    def check_api_health(self, api_endpoint: str):
        """Check health of a specific API endpoint"""
        start_time = time.time()
        
        try:
            # Make API call
            response = self.call_api(api_endpoint)
            end_time = time.time()
            
            response_time = (end_time - start_time) * 1000  # Convert to ms
            
            # Record metrics
            api_call = {
                'timestamp': datetime.now().isoformat(),
                'endpoint': api_endpoint,
                'response_time_ms': response_time,
                'status': 'success' if response.get('success', True) else 'error',
                'error': response.get('error'),
                'security_violation': self.check_security_violation(response)
            }
            
            self.metrics['api_calls'].append(api_call)
            
        except Exception as e:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000
            
            api_call = {
                'timestamp': datetime.now().isoformat(),
                'endpoint': api_endpoint,
                'response_time_ms': response_time,
                'status': 'error',
                'error': str(e),
                'security_violation': False
            }
            
            self.metrics['api_calls'].append(api_call)
    
    def call_api(self, api_endpoint: str) -> Dict[str, Any]:
        """Make API call with proper authentication"""
        try:
            # Map endpoint names to actual API calls
            endpoint_mapping = {
                'sepa_mandate_management': {
                    'module': 'verenigingen.api.sepa_mandate_management',
                    'method': 'create_missing_sepa_mandates',
                    'args': {'dry_run': True}
                },
                'payment_processing': {
                    'module': 'verenigingen.api.payment_processing', 
                    'method': 'send_overdue_payment_reminders',
                    'args': {'dry_run': True}
                },
                'member_management': {
                    'module': 'verenigingen.api.member_management',
                    'method': 'assign_member_to_chapter',
                    'args': {'member_name': 'TEST', 'chapter_name': 'TEST'}
                }
            }
            
            if api_endpoint not in endpoint_mapping:
                return {'success': False, 'error': f'Unknown endpoint: {api_endpoint}'}
            
            endpoint_info = endpoint_mapping[api_endpoint]
            
            # Call the API through Frappe
            result = frappe.call(
                f"{endpoint_info['module']}.{endpoint_info['method']}",
                **endpoint_info.get('args', {})
            )
            
            return {
                'success': True,
                'result': result
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def check_security_violation(self, response: Dict[str, Any]) -> bool:
        """Check if response indicates a security violation"""
        if not response.get('success', True):
            error = response.get('error', '').lower()
            security_keywords = [
                'unauthorized',
                'access denied',
                'permission denied',
                'invalid token',
                'authentication failed',
                'security violation'
            ]
            
            return any(keyword in error for keyword in security_keywords)
        
        return False
    
    def update_summary(self):
        """Update summary metrics"""
        if not self.metrics['api_calls']:
            return
        
        total_calls = len(self.metrics['api_calls'])
        successful_calls = len([c for c in self.metrics['api_calls'] if c['status'] == 'success'])
        failed_calls = total_calls - successful_calls
        security_violations = len([c for c in self.metrics['api_calls'] if c.get('security_violation', False)])
        
        # Calculate average response time
        response_times = [c['response_time_ms'] for c in self.metrics['api_calls']]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        self.metrics['summary'] = {
            'total_calls': total_calls,
            'successful_calls': successful_calls,
            'failed_calls': failed_calls,
            'error_rate': (failed_calls / total_calls * 100) if total_calls > 0 else 0,
            'average_response_time': avg_response_time,
            'security_violations': security_violations
        }
    
    def print_current_status(self):
        """Print current monitoring status"""
        summary = self.metrics['summary']
        
        print(f"  Total calls: {summary['total_calls']}")
        print(f"  Success rate: {((summary['successful_calls'] / max(summary['total_calls'], 1)) * 100):.1f}%")
        print(f"  Error rate: {summary['error_rate']:.1f}%")
        print(f"  Avg response time: {summary['average_response_time']:.1f}ms")
        print(f"  Security violations: {summary['security_violations']}")
        
        # Check for alerts
        alerts = self.check_alerts()
        if alerts:
            print("  🚨 ALERTS:")
            for alert in alerts:
                print(f"    - {alert}")
    
    def check_alerts(self) -> List[str]:
        """Check for alert conditions"""
        alerts = []
        summary = self.metrics['summary']
        
        # Error rate alert
        if summary['error_rate'] > 5:
            alerts.append(f"High error rate: {summary['error_rate']:.1f}%")
        
        # Response time alert
        if summary['average_response_time'] > 2000:
            alerts.append(f"Slow response time: {summary['average_response_time']:.1f}ms")
        
        # Security violation alert
        if summary['security_violations'] > 0:
            alerts.append(f"Security violations detected: {summary['security_violations']}")
        
        return alerts
    
    def save_metrics(self):
        """Save current metrics to file"""
        filename = f'api_health_metrics_{datetime.now().strftime("%Y%m%d")}.json'
        
        with open(filename, 'w') as f:
            json.dump(self.metrics, f, indent=2)
    
    def generate_final_report(self) -> Dict[str, Any]:
        """Generate final monitoring report"""
        end_time = datetime.now()
        actual_duration = (end_time - self.start_time).total_seconds() / 3600
        
        report = {
            'monitoring_period': {
                'start': self.start_time.isoformat(),
                'end': end_time.isoformat(),
                'planned_hours': self.duration_hours,
                'actual_hours': actual_duration
            },
            'summary': self.metrics['summary'],
            'alerts': self.check_alerts(),
            'recommendations': self.generate_recommendations()
        }
        
        # Save final report
        filename = f'api_health_final_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Print final report
        self.print_final_report(report)
        
        return report
    
    def generate_recommendations(self) -> List[str]:
        """Generate recommendations based on monitoring results"""
        recommendations = []
        summary = self.metrics['summary']
        
        if summary['error_rate'] > 10:
            recommendations.append("High error rate detected. Consider rolling back changes.")
        elif summary['error_rate'] > 5:
            recommendations.append("Elevated error rate. Monitor closely and investigate errors.")
        
        if summary['average_response_time'] > 3000:
            recommendations.append("Very slow response times. Performance optimization needed.")
        elif summary['average_response_time'] > 1000:
            recommendations.append("Slower than expected response times. Consider performance review.")
        
        if summary['security_violations'] > 0:
            recommendations.append("Security violations detected. Review security implementation immediately.")
        
        if summary['total_calls'] < 10:
            recommendations.append("Low call volume. Consider extending monitoring period.")
        
        if not recommendations:
            recommendations.append("API health looks good. Continue monitoring.")
        
        return recommendations
    
    def print_final_report(self, report: Dict[str, Any]):
        """Print final monitoring report"""
        print("\n" + "=" * 60)
        print("API HEALTH MONITORING FINAL REPORT")
        print("=" * 60)
        
        period = report['monitoring_period']
        print(f"Monitoring Period: {period['actual_hours']:.1f} hours")
        print(f"Start: {period['start']}")
        print(f"End: {period['end']}")
        
        print("\nSummary:")
        summary = report['summary']
        print(f"  Total API calls: {summary['total_calls']}")
        print(f"  Success rate: {((summary['successful_calls'] / max(summary['total_calls'], 1)) * 100):.1f}%")
        print(f"  Error rate: {summary['error_rate']:.1f}%")
        print(f"  Average response time: {summary['average_response_time']:.1f}ms")
        print(f"  Security violations: {summary['security_violations']}")
        
        if report['alerts']:
            print("\nAlerts:")
            for alert in report['alerts']:
                print(f"  🚨 {alert}")
        
        print("\nRecommendations:")
        for rec in report['recommendations']:
            print(f"  - {rec}")


def monitor_single_api(api_name: str, duration_hours: int = 24) -> Dict[str, Any]:
    """Monitor a single API for specified duration"""
    monitor = APIHealthMonitor(duration_hours)
    return monitor.monitor_apis([api_name], check_interval=300)


def monitor_all_critical_apis(duration_hours: int = 24) -> Dict[str, Any]:
    """Monitor all critical APIs"""
    critical_apis = [
        'sepa_mandate_management',
        'payment_processing',
        'member_management'
    ]
    
    monitor = APIHealthMonitor(duration_hours)
    return monitor.monitor_apis(critical_apis, check_interval=300)


if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    duration = 1  # Default 1 hour for testing
    api_name = None
    
    if len(sys.argv) > 1:
        if '--duration' in sys.argv:
            duration_idx = sys.argv.index('--duration') + 1
            if duration_idx < len(sys.argv):
                duration = int(sys.argv[duration_idx])
        
        if '--api' in sys.argv:
            api_idx = sys.argv.index('--api') + 1
            if api_idx < len(sys.argv):
                api_name = sys.argv[api_idx]
    
    # Initialize frappe if needed
    if not frappe.db:
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
    
    try:
        if api_name:
            print(f"Monitoring single API: {api_name}")
            results = monitor_single_api(api_name, duration)
        else:
            print("Monitoring all critical APIs")
            results = monitor_all_critical_apis(duration)
        
        # Check if monitoring detected issues
        if results['summary']['error_rate'] > 10 or results['summary']['security_violations'] > 0:
            print("\n⚠️  Critical issues detected during monitoring!")
            sys.exit(1)
        
    finally:
        if frappe.db:
            frappe.db.close()