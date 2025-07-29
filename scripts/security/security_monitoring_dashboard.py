#!/usr/bin/env python3
"""
Security Monitoring Dashboard
Provides real-time security status monitoring for the API security framework
"""

import os
import json
import datetime
from pathlib import Path
from typing import Dict, List, Any
import subprocess

class SecurityMonitoringDashboard:
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.security_reports_dir = self.base_path / "security_reports"
        self.security_reports_dir.mkdir(exist_ok=True)
        
    def generate_comprehensive_dashboard(self) -> Dict[str, Any]:
        """Generate comprehensive security monitoring dashboard"""
        
        print("🔍 Generating Security Monitoring Dashboard...")
        print("=" * 60)
        
        dashboard_data = {
            'generated_at': datetime.datetime.now().isoformat(),
            'security_overview': self._get_security_overview(),
            'recent_scans': self._get_recent_scan_results(),
            'compliance_trends': self._get_compliance_trends(),
            'security_alerts': self._get_security_alerts(),
            'system_health': self._get_system_health(),
            'recommendations': self._get_current_recommendations()
        }
        
        return dashboard_data
    
    def _get_security_overview(self) -> Dict[str, Any]:
        """Get current security overview"""
        # Load latest security scan report
        scan_report_path = self.base_path / "security_scan_report.json"
        validation_report_path = self.base_path / "security_validation_report.json"
        
        overview = {
            'total_api_files': 0,
            'secured_files': 0,
            'compliance_score': 0,
            'security_grade': 'Unknown',
            'last_scan_date': 'Never',
            'critical_issues': 0,
            'status': 'Unknown'
        }
        
        try:
            # Load scan report
            if scan_report_path.exists():
                with open(scan_report_path, 'r') as f:
                    scan_data = json.load(f)
                    
                overview['total_api_files'] = len(scan_data.get('secured_files', []))
                overview['secured_files'] = len(scan_data.get('secured_files', []))
                overview['last_scan_date'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                
            # Load validation report
            if validation_report_path.exists():
                with open(validation_report_path, 'r') as f:
                    validation_data = json.load(f)
                    
                compliance = validation_data.get('security_compliance_score', {})
                overview['compliance_score'] = compliance.get('score', 0)
                overview['security_grade'] = compliance.get('grade', 'Unknown')
                
                summary = validation_data.get('validation_summary', {})
                overview['critical_issues'] = summary.get('files_failed', 0)
                
            # Determine overall status
            if overview['compliance_score'] >= 95:
                overview['status'] = 'Excellent'
            elif overview['compliance_score'] >= 90:
                overview['status'] = 'Good'
            elif overview['compliance_score'] >= 80:
                overview['status'] = 'Acceptable'
            else:
                overview['status'] = 'Needs Attention'
                
        except Exception as e:
            overview['status'] = f'Error: {str(e)}'
            
        return overview
    
    def _get_recent_scan_results(self) -> List[Dict[str, Any]]:
        """Get recent security scan results"""
        results = []
        
        # Look for recent scan reports
        for report_file in self.security_reports_dir.glob("security_scan_*.json"):
            try:
                with open(report_file, 'r') as f:
                    data = json.load(f)
                    
                result = {
                    'date': report_file.stat().st_mtime,
                    'total_files': len(data.get('secured_files', [])),
                    'issues_found': sum(data.get('scan_summary', {}).get('risk_breakdown', {}).values()),
                    'status': 'PASS' if sum(data.get('scan_summary', {}).get('risk_breakdown', {}).values()) == 0 else 'ISSUES_FOUND'
                }
                results.append(result)
                
            except Exception:
                continue
                
        # Sort by date (most recent first)
        results.sort(key=lambda x: x['date'], reverse=True)
        
        # Convert timestamps to readable dates
        for result in results:
            result['date'] = datetime.datetime.fromtimestamp(result['date']).strftime("%Y-%m-%d %H:%M")
            
        return results[:10]  # Return last 10 scans
    
    def _get_compliance_trends(self) -> Dict[str, Any]:
        """Get compliance trend data"""
        trends = {
            'current_compliance': 0,
            'trend_direction': 'stable',
            'last_30_days': [],
            'improvement_areas': []
        }
        
        # Get current compliance score
        validation_report_path = self.base_path / "security_validation_report.json"
        if validation_report_path.exists():
            try:
                with open(validation_report_path, 'r') as f:
                    data = json.load(f)
                    compliance = data.get('security_compliance_score', {})
                    trends['current_compliance'] = compliance.get('score', 0)
                    
                    # Analyze files needing attention
                    files_needing_attention = data.get('files_needing_attention', [])
                    for file_info in files_needing_attention:
                        for suggestion in file_info.get('suggestions', []):
                            if suggestion not in trends['improvement_areas']:
                                trends['improvement_areas'].append(suggestion)
                                
            except Exception:
                pass
                
        return trends
    
    def _get_security_alerts(self) -> List[Dict[str, Any]]:
        """Get current security alerts"""
        alerts = []
        
        # Check for critical security issues
        validation_report_path = self.base_path / "security_validation_report.json"
        if validation_report_path.exists():
            try:
                with open(validation_report_path, 'r') as f:
                    data = json.load(f)
                    
                files_needing_attention = data.get('files_needing_attention', [])
                for file_info in files_needing_attention:
                    if file_info.get('status') == 'FAIL':
                        alerts.append({
                            'level': 'CRITICAL',
                            'message': f"Security validation failed for {Path(file_info['file']).name}",
                            'details': file_info.get('issues', []),
                            'timestamp': datetime.datetime.now().isoformat()
                        })
                    elif file_info.get('status') == 'WARNING':
                        alerts.append({
                            'level': 'WARNING',
                            'message': f"Security warnings for {Path(file_info['file']).name}",
                            'details': file_info.get('issues', []),
                            'timestamp': datetime.datetime.now().isoformat()
                        })
                        
            except Exception:
                pass
                
        # Add system-level alerts
        if not alerts:
            alerts.append({
                'level': 'INFO',
                'message': 'All security validations passing',
                'details': ['No critical security issues detected'],
                'timestamp': datetime.datetime.now().isoformat()
            })
            
        return alerts
    
    def _get_system_health(self) -> Dict[str, Any]:
        """Get system health metrics related to security"""
        health = {
            'security_framework_status': 'Unknown',
            'api_endpoints_secured': 0,
            'recent_security_events': 0,
            'system_uptime': 'Unknown',
            'last_security_update': 'Unknown'
        }
        
        try:
            # Check if security framework files exist
            framework_path = self.base_path / "verenigingen" / "utils" / "security" / "api_security_framework.py"
            if framework_path.exists():
                health['security_framework_status'] = 'Active'
                health['last_security_update'] = datetime.datetime.fromtimestamp(
                    framework_path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M")
            else:
                health['security_framework_status'] = 'Missing'
                
            # Count secured endpoints
            scan_report_path = self.base_path / "security_scan_report.json"
            if scan_report_path.exists():
                with open(scan_report_path, 'r') as f:
                    data = json.load(f)
                    health['api_endpoints_secured'] = len(data.get('secured_files', []))
                    
        except Exception as e:
            health['security_framework_status'] = f'Error: {str(e)}'
            
        return health
    
    def _get_current_recommendations(self) -> List[Dict[str, Any]]:
        """Get current security recommendations"""
        recommendations = []
        
        # Load validation report for recommendations
        validation_report_path = self.base_path / "security_validation_report.json"
        if validation_report_path.exists():
            try:
                with open(validation_report_path, 'r') as f:
                    data = json.load(f)
                    
                files_needing_attention = data.get('files_needing_attention', [])
                for file_info in files_needing_attention:
                    for suggestion in file_info.get('suggestions', []):
                        recommendations.append({
                            'priority': 'HIGH' if file_info.get('status') == 'FAIL' else 'MEDIUM',
                            'action': suggestion,
                            'file': Path(file_info['file']).name,
                            'category': 'Security Implementation'
                        })
                        
            except Exception:
                pass
                
        # Add general recommendations
        if not recommendations:
            recommendations.extend([
                {
                    'priority': 'LOW',
                    'action': 'Run monthly security scan',
                    'file': 'All files',
                    'category': 'Maintenance'
                },
                {
                    'priority': 'LOW', 
                    'action': 'Review security logs',
                    'file': 'Security monitoring',
                    'category': 'Monitoring'
                }
            ])
            
        # Sort by priority
        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        recommendations.sort(key=lambda x: priority_order.get(x['priority'], 9))
        
        return recommendations[:10]  # Return top 10 recommendations
    
    def print_dashboard(self, dashboard_data: Dict[str, Any]):
        """Print formatted dashboard to console"""
        print("\n🛡️  SECURITY MONITORING DASHBOARD")
        print("=" * 60)
        
        # Security Overview
        overview = dashboard_data['security_overview']
        print(f"\n📊 SECURITY OVERVIEW")
        print("-" * 30)
        print(f"Status: {overview['status']}")
        print(f"Compliance Score: {overview['compliance_score']}/100 (Grade {overview['security_grade']})")
        print(f"Secured Files: {overview['secured_files']}/{overview['total_api_files']}")
        print(f"Critical Issues: {overview['critical_issues']}")
        print(f"Last Scan: {overview['last_scan_date']}")
        
        # Security Alerts
        alerts = dashboard_data['security_alerts']
        print(f"\n🚨 SECURITY ALERTS ({len(alerts)})")
        print("-" * 30)
        for alert in alerts[:5]:  # Show first 5 alerts
            level_emoji = {'CRITICAL': '🔴', 'WARNING': '🟡', 'INFO': '🟢'}.get(alert['level'], '🔵')
            print(f"{level_emoji} {alert['level']}: {alert['message']}")
            
        # System Health
        health = dashboard_data['system_health']
        print(f"\n💚 SYSTEM HEALTH")
        print("-" * 30)
        print(f"Security Framework: {health['security_framework_status']}")
        print(f"API Endpoints Secured: {health['api_endpoints_secured']}")
        print(f"Last Security Update: {health['last_security_update']}")
        
        # Current Recommendations
        recommendations = dashboard_data['recommendations']
        print(f"\n💡 RECOMMENDATIONS ({len(recommendations)})")
        print("-" * 30)
        for rec in recommendations[:5]:  # Show first 5 recommendations
            priority_emoji = {'CRITICAL': '🔴', 'HIGH': '🟡', 'MEDIUM': '🟠', 'LOW': '🟢'}.get(rec['priority'], '🔵')
            print(f"{priority_emoji} {rec['priority']}: {rec['action']}")
            print(f"   📁 {rec['file']} ({rec['category']})")
            
        # Compliance Trends
        trends = dashboard_data['compliance_trends']
        print(f"\n📈 COMPLIANCE TRENDS")
        print("-" * 30)
        print(f"Current Compliance: {trends['current_compliance']}/100")
        print(f"Trend: {trends['trend_direction']}")
        if trends['improvement_areas']:
            print(f"Improvement Areas: {', '.join(trends['improvement_areas'][:3])}")
            
        print(f"\n📅 Generated: {dashboard_data['generated_at']}")
        print("=" * 60)
    
    def save_dashboard_report(self, dashboard_data: Dict[str, Any]) -> str:
        """Save dashboard data to timestamped report file"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"security_dashboard_{timestamp}.json"
        report_path = self.security_reports_dir / report_filename
        
        with open(report_path, 'w') as f:
            json.dump(dashboard_data, f, indent=2, default=str)
            
        return str(report_path)

def main():
    """Main execution function"""
    dashboard = SecurityMonitoringDashboard()
    
    print("🚀 Generating Security Monitoring Dashboard")
    print("=" * 50)
    
    # Generate comprehensive dashboard
    dashboard_data = dashboard.generate_comprehensive_dashboard()
    
    # Print dashboard to console
    dashboard.print_dashboard(dashboard_data)
    
    # Save dashboard report
    report_path = dashboard.save_dashboard_report(dashboard_data)
    print(f"\n📋 Dashboard report saved to: {report_path}")
    
    return dashboard, dashboard_data

if __name__ == "__main__":
    dashboard, data = main()