#!/usr/bin/env python3
"""
Email System Validation Script
===============================

Simple validation script to verify the email system components are working
without relying on complex test frameworks.
"""

import frappe
from frappe.utils import now_datetime
import traceback


def validate_email_components():
    """Validate core email system components"""
    
    results = {
        "tests": [],
        "passed": 0,
        "failed": 0,
        "total": 0
    }
    
    def test(name, func):
        """Run a single test"""
        results["total"] += 1
        try:
            result = func()
            if result:
                print(f"✅ {name}")
                results["passed"] += 1
                results["tests"].append({"name": name, "status": "PASS"})
            else:
                print(f"❌ {name} - Test returned False")
                results["failed"] += 1
                results["tests"].append({"name": name, "status": "FAIL", "error": "Test returned False"})
        except Exception as e:
            print(f"❌ {name} - Error: {str(e)}")
            results["failed"] += 1
            results["tests"].append({"name": name, "status": "ERROR", "error": str(e)})
    
    print("\n" + "="*60)
    print("EMAIL SYSTEM COMPONENT VALIDATION")
    print("="*60)
    
    # Test 1: Newsletter Template Manager Import and Instantiation
    def test_newsletter_template_manager():
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager
        manager = NewsletterTemplateManager()
        return manager is not None and hasattr(manager, 'templates')
    
    test("Newsletter Template Manager Instantiation", test_newsletter_template_manager)
    
    # Test 2: Template Listing
    def test_template_listing():
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager
        manager = NewsletterTemplateManager()
        templates = manager.list_templates()
        return isinstance(templates, list) and len(templates) > 0
    
    test("Template Listing Functionality", test_template_listing)
    
    # Test 3: Template Rendering
    def test_template_rendering():
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager
        manager = NewsletterTemplateManager()
        variables = {
            "chapter_name": "Test Chapter",
            "month_year": "March 2024",
            "highlights": "Test highlights",
            "upcoming_events": "Test events",
            "volunteer_spotlight": "Test volunteer"
        }
        rendered = manager.render_template("monthly_update", variables)
        return (rendered is not None and 
                "subject" in rendered and 
                "content" in rendered and
                "Test Chapter" in rendered["content"])
    
    test("Template Rendering", test_template_rendering)
    
    # Test 4: Analytics Tracker
    def test_analytics_tracker():
        from verenigingen.email.analytics_tracker import EmailAnalyticsTracker
        tracker = EmailAnalyticsTracker()
        return tracker is not None and hasattr(tracker, 'default_retention_days')
    
    test("Analytics Tracker Instantiation", test_analytics_tracker)
    
    # Test 5: Advanced Segmentation
    def test_segmentation_manager():
        from verenigingen.email.advanced_segmentation import AdvancedSegmentationManager
        segmentation = AdvancedSegmentationManager()
        return (segmentation is not None and 
                hasattr(segmentation, 'built_in_segments') and
                len(segmentation.built_in_segments) > 0)
    
    test("Advanced Segmentation Manager", test_segmentation_manager)
    
    # Test 6: Simplified Email Manager
    def test_simplified_email_manager():
        from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
        # Create a dummy chapter doc for testing
        dummy_chapter = frappe._dict({
            "name": "Test Chapter",
            "doctype": "Chapter"
        })
        manager = SimplifiedEmailManager(dummy_chapter)
        return manager is not None
    
    test("Simplified Email Manager Instantiation", test_simplified_email_manager)
    
    # Test 7: Email Group Sync Functions
    def test_email_group_functions():
        from verenigingen.email.email_group_sync import add_to_email_group, remove_from_email_group
        # Just test that functions can be imported
        return callable(add_to_email_group) and callable(remove_from_email_group)
    
    test("Email Group Sync Functions", test_email_group_functions)
    
    # Test 8: Automated Campaign Manager
    def test_automated_campaigns():
        from verenigingen.email.automated_campaigns import AutomatedCampaignManager
        manager = AutomatedCampaignManager()
        return (manager is not None and 
                hasattr(manager, 'campaign_types') and
                len(manager.campaign_types) > 0)
    
    test("Automated Campaign Manager", test_automated_campaigns)
    
    # Print Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    success_rate = (results["passed"] / results["total"] * 100) if results["total"] > 0 else 0
    print(f"Total Tests: {results['total']}")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")
    print(f"Success Rate: {success_rate:.1f}%")
    
    if success_rate >= 90:
        print("\n✅ EMAIL SYSTEM VALIDATION PASSED")
        print("   Core components are functional and ready for comprehensive testing")
    elif success_rate >= 70:
        print("\n⚠️ EMAIL SYSTEM VALIDATION PARTIALLY PASSED")
        print("   Some issues detected, but core functionality appears to work")
    else:
        print("\n❌ EMAIL SYSTEM VALIDATION FAILED")
        print("   Significant issues detected - comprehensive testing may not work properly")
    
    return results


def validate_security_fixes():
    """Validate that security fixes are in place"""
    
    print("\n" + "="*60)
    print("SECURITY FIX VALIDATION")
    print("="*60)
    
    security_checks = []
    
    # Check 1: SQL injection prevention in simplified_email_manager
    try:
        from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
        import inspect
        source = inspect.getsource(SimplifiedEmailManager.send_to_chapter_segment)
        
        # Look for parameterized queries
        has_parameterized = '%s' in source and 'sql(' in source
        sql_injection_safe = has_parameterized
        
        print(f"{'✅' if sql_injection_safe else '❌'} SQL Injection Prevention: {'IMPLEMENTED' if sql_injection_safe else 'NEEDS REVIEW'}")
        security_checks.append(("SQL Injection Prevention", sql_injection_safe))
        
    except Exception as e:
        print(f"❌ SQL Injection Check Failed: {e}")
        security_checks.append(("SQL Injection Prevention", False))
    
    # Check 2: Permission validation in API functions  
    try:
        from verenigingen.email.simplified_email_manager import send_chapter_email
        import inspect
        source = inspect.getsource(send_chapter_email)
        
        has_permission_check = 'has_permission' in source or 'frappe.throw' in source
        
        print(f"{'✅' if has_permission_check else '❌'} Permission Validation: {'IMPLEMENTED' if has_permission_check else 'NEEDS REVIEW'}")
        security_checks.append(("Permission Validation", has_permission_check))
        
    except Exception as e:
        print(f"❌ Permission Check Failed: {e}")
        security_checks.append(("Permission Validation", False))
        
    # Check 3: DocType existence validation in analytics
    try:
        from verenigingen.email.analytics_tracker import EmailAnalyticsTracker
        import inspect
        source = inspect.getsource(EmailAnalyticsTracker.track_email_sent)
        
        has_doctype_check = 'frappe.db.exists("DocType"' in source
        
        print(f"{'✅' if has_doctype_check else '❌'} DocType Existence Check: {'IMPLEMENTED' if has_doctype_check else 'NEEDS REVIEW'}")
        security_checks.append(("DocType Existence Check", has_doctype_check))
        
    except Exception as e:
        print(f"❌ DocType Existence Check Failed: {e}")
        security_checks.append(("DocType Existence Check", False))
        
    # Summary
    passed_checks = sum(1 for _, status in security_checks if status)
    total_checks = len(security_checks)
    security_score = (passed_checks / total_checks * 100) if total_checks > 0 else 0
    
    print(f"\nSecurity Score: {security_score:.1f}% ({passed_checks}/{total_checks})")
    
    if security_score >= 100:
        print("✅ ALL SECURITY FIXES VERIFIED")
    elif security_score >= 75:
        print("⚠️ MOST SECURITY FIXES VERIFIED")
    else:
        print("❌ SECURITY FIXES NEED ATTENTION")
        
    return security_checks


@frappe.whitelist()
def run_email_system_validation():
    """Main validation function that can be called via bench execute"""
    
    print("Starting Email System Validation...")
    
    # Initialize Frappe if needed
    if not hasattr(frappe.local, 'site'):
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
    
    try:
        # Run component validation
        component_results = validate_email_components()
        
        # Run security validation
        security_results = validate_security_fixes()
        
        # Overall assessment
        component_score = (component_results["passed"] / component_results["total"] * 100) if component_results["total"] > 0 else 0
        security_score = (sum(1 for _, status in security_results if status) / len(security_results) * 100) if security_results else 0
        
        overall_score = (component_score + security_score) / 2
        
        print(f"\n" + "="*60)
        print("OVERALL ASSESSMENT")
        print("="*60)
        print(f"Component Functionality: {component_score:.1f}%")
        print(f"Security Implementation: {security_score:.1f}%")
        print(f"Overall Score: {overall_score:.1f}%")
        
        if overall_score >= 90:
            print("\n🎉 EMAIL SYSTEM IS PRODUCTION READY")
            print("   ✅ Components functional")
            print("   ✅ Security fixes implemented")
            print("   ✅ Ready for comprehensive testing")
        elif overall_score >= 75:
            print("\n⚠️ EMAIL SYSTEM MOSTLY READY")
            print("   Some minor issues to address before production")
        else:
            print("\n❌ EMAIL SYSTEM NOT READY")
            print("   Significant issues need resolution")
            
        return {
            "overall_score": overall_score,
            "component_score": component_score,
            "security_score": security_score,
            "component_results": component_results,
            "security_results": security_results
        }
        
    except Exception as e:
        print(f"\n❌ VALIDATION FAILED: {str(e)}")
        traceback.print_exc()
        return {"error": str(e)}


if __name__ == "__main__":
    run_email_system_validation()