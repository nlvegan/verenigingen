#!/usr/bin/env python3
"""
Email System Validation Utilities
==================================

Simple validation utilities for the email system.
"""

import frappe


@frappe.whitelist()
def validate_email_system_components():
    """Validate that email system components can be imported and instantiated"""

    validation_results = {"tests": [], "passed": 0, "failed": 0, "total": 0}

    def test_component(name, test_func):
        """Test a single component"""
        validation_results["total"] += 1
        try:
            result = test_func()
            if result:
                validation_results["passed"] += 1
                validation_results["tests"].append({"name": name, "status": "PASS"})
                print(f"✅ {name}")
            else:
                validation_results["failed"] += 1
                validation_results["tests"].append({"name": name, "status": "FAIL"})
                print(f"❌ {name}")
        except Exception as e:
            validation_results["failed"] += 1
            validation_results["tests"].append({"name": name, "status": "ERROR", "error": str(e)})
            print(f"❌ {name} - Error: {str(e)}")

    print("Email System Component Validation")
    print("=" * 40)

    # Test Newsletter Templates
    def test_newsletter_templates():
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager

        manager = NewsletterTemplateManager()
        return manager is not None and len(manager.templates) > 0

    test_component("Newsletter Templates", test_newsletter_templates)

    # Test Email Analytics
    def test_analytics():
        from verenigingen.email.analytics_tracker import EmailAnalyticsTracker

        tracker = EmailAnalyticsTracker()
        return tracker is not None

    test_component("Analytics Tracker", test_analytics)

    # Test Segmentation
    def test_segmentation():
        from verenigingen.email.advanced_segmentation import AdvancedSegmentationManager

        manager = AdvancedSegmentationManager()
        return manager is not None and len(manager.built_in_segments) > 0

    test_component("Advanced Segmentation", test_segmentation)

    # Test Campaign Manager
    def test_campaigns():
        from verenigingen.email.automated_campaigns import AutomatedCampaignManager

        manager = AutomatedCampaignManager()
        return manager is not None and len(manager.campaign_types) > 0

    test_component("Campaign Manager", test_campaigns)

    # Test Email Group Sync
    def test_email_sync():
        from verenigingen.email.email_group_sync import sync_email_groups_manually

        return callable(sync_email_groups_manually)

    test_component("Email Group Sync", test_email_sync)

    # Summary
    success_rate = (
        (validation_results["passed"] / validation_results["total"] * 100)
        if validation_results["total"] > 0
        else 0
    )

    print("\nValidation Summary:")
    print(f"Tests Run: {validation_results['total']}")
    print(f"Passed: {validation_results['passed']}")
    print(f"Failed: {validation_results['failed']}")
    print(f"Success Rate: {success_rate:.1f}%")

    if success_rate >= 90:
        print("✅ EMAIL SYSTEM COMPONENTS VALIDATED")
    else:
        print("❌ EMAIL SYSTEM HAS ISSUES")

    return validation_results
