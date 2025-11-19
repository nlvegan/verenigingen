#!/usr/bin/env python3
"""
Verenigingen Security Toolkit
Consolidated security management tool for ongoing API security monitoring and maintenance
"""

import os
import sys
import argparse
import json
from pathlib import Path
from typing import Dict, Any

# Import our security tools
from automated_security_scanner import APISecurityScanner
from security_validation_suite import SecurityValidationSuite
from security_monitoring_dashboard import SecurityMonitoringDashboard

class SecurityToolkit:
    """Consolidated security management toolkit"""
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.scanner = APISecurityScanner(str(base_path))
        self.validator = SecurityValidationSuite(str(base_path))
        self.dashboard = SecurityMonitoringDashboard(str(base_path))
        
    def run_full_security_audit(self) -> Dict[str, Any]:
        """Run complete security audit with all tools"""
        print("🔍 RUNNING COMPREHENSIVE SECURITY AUDIT")
        print("=" * 60)
        
        audit_results = {
            'audit_timestamp': None,
            'scan_results': None,
            'validation_results': None,
            'dashboard_data': None,
            'summary': {}
        }
        
        try:
            # Step 1: Security Scan
            print("\n📡 Step 1: Running Security Scanner...")
            scan_results = self.scanner.scan_all_files()
            scan_report = self.scanner.generate_report()
            self.scanner.save_report()
            audit_results['scan_results'] = scan_report
            print("✅ Security scan completed")
            
            # Step 2: Validation Suite
            print("\n🔍 Step 2: Running Validation Suite...")
            secured_files = scan_report.get('secured_files', [])
            validation_results = self.validator.validate_all_secured_files(secured_files)
            validation_report = self.validator.generate_security_report(validation_results)
            audit_results['validation_results'] = validation_report
            print("✅ Security validation completed")
            
            # Step 3: Dashboard Generation
            print("\n📊 Step 3: Generating Security Dashboard...")
            dashboard_data = self.dashboard.generate_comprehensive_dashboard()
            audit_results['dashboard_data'] = dashboard_data
            print("✅ Security dashboard generated")
            
            # Step 4: Generate Summary
            audit_results['summary'] = self._generate_audit_summary(
                scan_report, validation_report, dashboard_data
            )
            
            print("\n🎯 SECURITY AUDIT COMPLETED SUCCESSFULLY")
            return audit_results
            
        except Exception as e:
            print(f"❌ Security audit failed: {str(e)}")
            audit_results['error'] = str(e)
            return audit_results
    
    def run_quick_security_check(self) -> Dict[str, Any]:
        """Run quick security status check"""
        print("⚡ RUNNING QUICK SECURITY CHECK")
        print("=" * 40)
        
        try:
            # Generate dashboard for current status
            dashboard_data = self.dashboard.generate_comprehensive_dashboard()
            
            # Extract key metrics
            overview = dashboard_data.get('security_overview', {})
            alerts = dashboard_data.get('security_alerts', [])
            
            quick_results = {
                'status': overview.get('status', 'Unknown'),
                'compliance_score': overview.get('compliance_score', 0),
                'security_grade': overview.get('security_grade', 'Unknown'),
                'critical_alerts': len([a for a in alerts if a.get('level') == 'CRITICAL']),
                'total_secured_files': overview.get('secured_files', 0),
                'recommendations_count': len(dashboard_data.get('recommendations', []))
            }
            
            # Print quick summary
            print(f"\n📊 QUICK STATUS SUMMARY")
            print("-" * 25)
            print(f"Overall Status: {quick_results['status']}")
            print(f"Compliance: {quick_results['compliance_score']}/100 (Grade {quick_results['security_grade']})")
            print(f"Secured Files: {quick_results['total_secured_files']}")
            print(f"Critical Alerts: {quick_results['critical_alerts']}")
            print(f"Recommendations: {quick_results['recommendations_count']}")
            
            if quick_results['critical_alerts'] == 0 and quick_results['compliance_score'] >= 95:
                print("✅ Security status: EXCELLENT")
            elif quick_results['critical_alerts'] == 0 and quick_results['compliance_score'] >= 90:
                print("✅ Security status: GOOD")
            else:
                print("⚠️  Security status: NEEDS ATTENTION")
                
            return quick_results
            
        except Exception as e:
            print(f"❌ Quick security check failed: {str(e)}")
            return {'error': str(e)}
    
    def generate_security_report(self, output_format: str = 'console') -> str:
        """Generate formatted security report"""
        dashboard_data = self.dashboard.generate_comprehensive_dashboard()
        
        if output_format == 'json':
            report_path = self.dashboard.save_dashboard_report(dashboard_data)
            print(f"📄 JSON report saved to: {report_path}")
            return report_path
        elif output_format == 'console':
            self.dashboard.print_dashboard(dashboard_data)
            return "console"
        else:
            print(f"❌ Unknown output format: {output_format}")
            return ""
    
    def _generate_audit_summary(self, scan_report: Dict, validation_report: Dict, dashboard_data: Dict) -> Dict[str, Any]:
        """Generate comprehensive audit summary"""
        scan_summary = scan_report.get('scan_summary', {})
        validation_summary = validation_report.get('validation_summary', {})
        compliance = validation_report.get('security_compliance_score', {})
        overview = dashboard_data.get('security_overview', {})
        
        summary = {
            'overall_status': overview.get('status', 'Unknown'),
            'compliance_grade': compliance.get('grade', 'Unknown'),
            'compliance_score': compliance.get('score', 0),
            'total_files_scanned': len(scan_report.get('secured_files', [])),
            'validation_success_rate': validation_summary.get('success_rate', '0%'),
            'critical_issues_count': validation_summary.get('files_failed', 0),
            'security_alerts_count': len(dashboard_data.get('security_alerts', [])),
            'recommendations_count': len(dashboard_data.get('recommendations', [])),
            'audit_status': 'PASS' if compliance.get('score', 0) >= 95 and validation_summary.get('files_failed', 0) == 0 else 'ATTENTION_NEEDED'
        }
        
        return summary

def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description="Verenigingen Security Toolkit - Comprehensive API Security Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python security_toolkit.py --scan                    # Run security scanner only
  python security_toolkit.py --validate               # Run validation suite only
  python security_toolkit.py --dashboard              # Generate dashboard only
  python security_toolkit.py --quick                  # Quick security check
  python security_toolkit.py --audit                  # Full security audit
  python security_toolkit.py --report json           # Generate JSON report
  python security_toolkit.py --help                   # Show this help message
        """
    )
    
    # Command options
    parser.add_argument('--scan', action='store_true', 
                       help='Run automated security scanner')
    parser.add_argument('--validate', action='store_true',
                       help='Run security validation suite') 
    parser.add_argument('--dashboard', action='store_true',
                       help='Generate security monitoring dashboard')
    parser.add_argument('--quick', action='store_true',
                       help='Run quick security status check')
    parser.add_argument('--audit', action='store_true',
                       help='Run comprehensive security audit')
    parser.add_argument('--report', choices=['console', 'json'],
                       help='Generate security report in specified format')
    parser.add_argument('--base-path', default="/home/frappe/frappe-bench/apps/verenigingen",
                       help='Base path to verenigingen app (default: current path)')
    
    args = parser.parse_args()
    
    # Initialize toolkit
    toolkit = SecurityToolkit(args.base_path)
    
    try:
        # Execute requested operations
        if args.audit:
            results = toolkit.run_full_security_audit()
            summary = results.get('summary', {})
            print(f"\n🎯 AUDIT SUMMARY")
            print("-" * 20)
            print(f"Status: {summary.get('overall_status', 'Unknown')}")
            print(f"Grade: {summary.get('compliance_grade', 'Unknown')} ({summary.get('compliance_score', 0)}/100)")
            print(f"Files Scanned: {summary.get('total_files_scanned', 0)}")
            print(f"Success Rate: {summary.get('validation_success_rate', '0%')}")
            print(f"Critical Issues: {summary.get('critical_issues_count', 0)}")
            
        elif args.quick:
            toolkit.run_quick_security_check()
            
        elif args.scan:
            scanner = APISecurityScanner(args.base_path)
            scanner.scan_all_files()
            report = scanner.generate_report()
            scanner.save_report()
            print(f"📊 Scan completed - {len(report['secured_files'])} secured files found")
            
        elif args.validate:
            # Load secured files from previous scan
            scan_report_path = Path(args.base_path) / "security_scan_report.json"
            if scan_report_path.exists():
                with open(scan_report_path, 'r') as f:
                    scan_data = json.load(f)
                secured_files = scan_data.get('secured_files', [])
                
                validator = SecurityValidationSuite(args.base_path)
                results = validator.validate_all_secured_files(secured_files)
                report = validator.generate_security_report(results)
                
                compliance = report.get('security_compliance_score', {})
                print(f"🔍 Validation completed - Grade: {compliance.get('grade', 'Unknown')} ({compliance.get('score', 0)}/100)")
            else:
                print("❌ No security scan report found. Run --scan first.")
                
        elif args.dashboard:
            dashboard = SecurityMonitoringDashboard(args.base_path)
            dashboard_data = dashboard.generate_comprehensive_dashboard()
            dashboard.print_dashboard(dashboard_data)
            
        elif args.report:
            report_path = toolkit.generate_security_report(args.report)
            if args.report == 'json':
                print(f"✅ Report generated: {report_path}")
                
        else:
            # Default: show help and run quick check
            parser.print_help()
            print("\n" + "="*60)
            toolkit.run_quick_security_check()
            
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()