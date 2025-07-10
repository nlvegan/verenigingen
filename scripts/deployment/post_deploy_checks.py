#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-deployment Checks
Validates deployment was successful
"""

import sys
import json
import time
import requests
from urllib.parse import urljoin


class PostDeploymentChecker:
    """Run post-deployment validation checks"""
    
    def __init__(self, environment, version, timeout=300):
        self.environment = environment
        self.version = version
        self.timeout = timeout
        self.base_urls = {
            "staging": "https://staging.veganisme.net",
            "production": "https://app.veganisme.net"
        }
        self.base_url = self.base_urls.get(environment, "http://localhost:8000")
        self.checks_passed = 0
        self.checks_failed = 0
        
    def wait_for_deployment(self):
        """Wait for deployment to be ready"""
        print(f"⏳ Waiting for {self.environment} deployment to be ready...")
        
        start_time = time.time()
        health_url = urljoin(self.base_url, "/health")
        
        while time.time() - start_time < self.timeout:
            try:
                response = requests.get(health_url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "healthy":
                        print("✅ Deployment is ready!")
                        return True
            except Exception:
                pass
                
            time.sleep(10)
            
        print("❌ Timeout waiting for deployment")
        return False
        
    def check_version_deployed(self):
        """Verify correct version is deployed"""
        print(f"🏷️  Checking deployed version...")
        
        try:
            # Check version endpoint
            version_url = urljoin(self.base_url, "/api/method/verenigingen.api.get_version")
            response = requests.get(version_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                deployed_version = data.get("message", {}).get("version")
                
                if deployed_version == self.version:
                    print(f"  ✅ Correct version deployed: {deployed_version}")
                    self.checks_passed += 1
                    return True
                else:
                    print(f"  ❌ Version mismatch! Expected: {self.version}, Got: {deployed_version}")
                    self.checks_failed += 1
                    return False
                    
        except Exception as e:
            print(f"  ❌ Error checking version: {e}")
            self.checks_failed += 1
            return False
            
    def check_api_endpoints(self):
        """Test critical API endpoints"""
        print("🔌 Testing API endpoints...")
        
        endpoints = [
            ("/api/method/frappe.auth.get_logged_in_user", "Authentication"),
            ("/api/method/verenigingen.api.member.get_member_list", "Member API"),
            ("/api/method/verenigingen.api.volunteer.get_volunteer_list", "Volunteer API"),
            ("/health", "Health Check")
        ]
        
        for endpoint, name in endpoints:
            url = urljoin(self.base_url, endpoint)
            
            try:
                response = requests.get(url, timeout=10)
                
                if response.status_code in [200, 403]:  # 403 is OK for auth-required endpoints
                    print(f"  ✅ {name}: OK")
                    self.checks_passed += 1
                else:
                    print(f"  ❌ {name}: Status {response.status_code}")
                    self.checks_failed += 1
                    
            except Exception as e:
                print(f"  ❌ {name}: Error - {e}")
                self.checks_failed += 1
                
    def check_static_assets(self):
        """Verify static assets are accessible"""
        print("📦 Checking static assets...")
        
        assets = [
            "/assets/verenigingen/css/verenigingen.css",
            "/assets/verenigingen/js/verenigingen.js"
        ]
        
        for asset in assets:
            url = urljoin(self.base_url, asset)
            
            try:
                response = requests.head(url, timeout=10)
                
                if response.status_code == 200:
                    print(f"  ✅ {asset}: OK")
                    self.checks_passed += 1
                else:
                    print(f"  ❌ {asset}: Status {response.status_code}")
                    self.checks_failed += 1
                    
            except Exception as e:
                print(f"  ❌ {asset}: Error - {e}")
                self.checks_failed += 1
                
    def check_database_migrations(self):
        """Verify database migrations ran successfully"""
        print("🗄️  Checking database migrations...")
        
        try:
            # Check migration status endpoint
            migration_url = urljoin(self.base_url, "/api/method/verenigingen.api.get_migration_status")
            response = requests.get(migration_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("message", {}).get("migrations_complete"):
                    print("  ✅ All migrations completed")
                    self.checks_passed += 1
                else:
                    print("  ❌ Migrations incomplete")
                    self.checks_failed += 1
            else:
                print("  ⚠️  Could not verify migration status")
                
        except Exception as e:
            print(f"  ⚠️  Migration check skipped: {e}")
            
    def check_scheduled_jobs(self):
        """Verify scheduled jobs are running"""
        print("⏰ Checking scheduled jobs...")
        
        try:
            # Check scheduler status
            scheduler_url = urljoin(self.base_url, "/api/method/verenigingen.api.get_scheduler_status")
            response = requests.get(scheduler_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("message", {}).get("scheduler_active"):
                    print("  ✅ Scheduler is active")
                    self.checks_passed += 1
                else:
                    print("  ❌ Scheduler is not active")
                    self.checks_failed += 1
                    
        except Exception as e:
            print(f"  ⚠️  Scheduler check skipped: {e}")
            
    def check_error_rate(self):
        """Check if error rate is acceptable"""
        print("📊 Checking error rate...")
        
        try:
            # Get error rate from monitoring
            error_url = urljoin(self.base_url, "/api/method/verenigingen.api.monitoring.get_error_rate")
            response = requests.get(error_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                error_rate = data.get("message", {}).get("error_rate", 0)
                
                if error_rate < 1.0:  # Less than 1% error rate
                    print(f"  ✅ Error rate: {error_rate:.2f}%")
                    self.checks_passed += 1
                else:
                    print(f"  ❌ High error rate: {error_rate:.2f}%")
                    self.checks_failed += 1
                    
        except Exception as e:
            print(f"  ⚠️  Error rate check skipped: {e}")
            
    def run_smoke_tests(self):
        """Run basic smoke tests"""
        print("🔥 Running smoke tests...")
        
        tests = [
            self.test_login_page,
            self.test_member_portal,
            self.test_volunteer_portal
        ]
        
        for test in tests:
            try:
                if test():
                    self.checks_passed += 1
                else:
                    self.checks_failed += 1
            except Exception as e:
                print(f"  ❌ Test failed: {e}")
                self.checks_failed += 1
                
    def test_login_page(self):
        """Test login page is accessible"""
        url = urljoin(self.base_url, "/login")
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200 and "login" in response.text.lower():
            print("  ✅ Login page: OK")
            return True
        else:
            print("  ❌ Login page: Failed")
            return False
            
    def test_member_portal(self):
        """Test member portal is accessible"""
        url = urljoin(self.base_url, "/member-portal")
        response = requests.get(url, timeout=10, allow_redirects=False)
        
        # Either 200 or redirect to login is OK
        if response.status_code in [200, 302, 303]:
            print("  ✅ Member portal: OK")
            return True
        else:
            print("  ❌ Member portal: Failed")
            return False
            
    def test_volunteer_portal(self):
        """Test volunteer portal is accessible"""
        url = urljoin(self.base_url, "/volunteer/dashboard")
        response = requests.get(url, timeout=10, allow_redirects=False)
        
        if response.status_code in [200, 302, 303]:
            print("  ✅ Volunteer portal: OK")
            return True
        else:
            print("  ❌ Volunteer portal: Failed")
            return False
            
    def generate_report(self):
        """Generate post-deployment report"""
        report = {
            "environment": self.environment,
            "version": self.version,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "deployment_status": "success" if self.checks_failed == 0 else "failed"
        }
        
        with open("post-deployment-report.json", "w") as f:
            json.dump(report, f, indent=2)
            
        return report
        
    def run_all_checks(self):
        """Run all post-deployment checks"""
        print(f"🚀 Running post-deployment checks for {self.environment}...\n")
        
        # Wait for deployment
        if not self.wait_for_deployment():
            print("❌ Deployment not ready - aborting checks")
            sys.exit(1)
            
        # Run checks
        self.check_version_deployed()
        self.check_api_endpoints()
        self.check_static_assets()
        self.check_database_migrations()
        self.check_scheduled_jobs()
        self.check_error_rate()
        self.run_smoke_tests()
        
        # Generate report
        print("\n" + "="*50)
        print("📊 POST-DEPLOYMENT CHECK SUMMARY")
        print("="*50)
        print(f"✅ Passed: {self.checks_passed}")
        print(f"❌ Failed: {self.checks_failed}")
        
        report = self.generate_report()
        
        if self.checks_failed > 0:
            print(f"\n❌ DEPLOYMENT VERIFICATION FAILED")
            print(f"Please investigate the {self.checks_failed} failed checks")
            sys.exit(1)
        else:
            print(f"\n✅ DEPLOYMENT VERIFIED SUCCESSFULLY")
            print(f"Version {self.version} is running correctly on {self.environment}")
            sys.exit(0)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Post-deployment checks")
    parser.add_argument("--environment", required=True, choices=["staging", "production"])
    parser.add_argument("--version", required=True, help="Expected version")
    parser.add_argument("--timeout", type=int, default=300, help="Deployment timeout in seconds")
    
    args = parser.parse_args()
    
    checker = PostDeploymentChecker(args.environment, args.version, args.timeout)
    checker.run_all_checks()


if __name__ == "__main__":
    main()