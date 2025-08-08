#!/usr/bin/env python3
"""
Basic Email System Test
Simple test to verify core functionality works
"""

import frappe

from verenigingen.email.advanced_segmentation import AdvancedSegmentationManager
from verenigingen.email.analytics_tracker import EmailAnalyticsTracker
from verenigingen.email.automated_campaigns import AutomatedCampaignManager
from verenigingen.email.newsletter_templates import NewsletterTemplateManager
from verenigingen.email.validation_utils import validate_email_system_components


def test_basic_functionality():
    """Test basic email system functionality"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("🧪 Testing Basic Email System Functionality")
    print("=" * 50)

    # Test 1: Component validation
    print("\n1. Component Validation Test")
    try:
        result = validate_email_system_components()
        print(f"✅ Component validation: {result['passed']}/{result['total']} passed")
    except Exception as e:
        print(f"❌ Component validation failed: {str(e)}")

    # Test 2: Template manager
    print("\n2. Newsletter Template Test")
    try:
        template_manager = NewsletterTemplateManager()
        templates = template_manager.list_templates()
        print(f"✅ Found {len(templates)} newsletter templates")

        # Test template rendering
        variables = {
            "chapter_name": "Test Chapter",
            "month_year": "January 2025",
            "highlights": "Test highlights",
            "upcoming_events": "Test events",
            "volunteer_spotlight": "Test volunteer",
        }
        result = template_manager.render_template("monthly_update", variables)
        if result and result.get("subject"):
            print(f"✅ Template rendering works: {result['subject'][:50]}...")
        else:
            print("❌ Template rendering failed")
    except Exception as e:
        print(f"❌ Template test failed: {str(e)}")

    # Test 3: Segmentation manager
    print("\n3. Segmentation Manager Test")
    try:
        seg_manager = AdvancedSegmentationManager()
        segments = seg_manager.built_in_segments
        print(f"✅ Found {len(segments)} built-in segments")

        # List some segment names
        sample_segments = list(segments.keys())[:3]
        print(f"✅ Sample segments: {', '.join(sample_segments)}")
    except Exception as e:
        print(f"❌ Segmentation test failed: {str(e)}")

    # Test 4: Analytics tracker
    print("\n4. Analytics Tracker Test")
    try:
        analytics = EmailAnalyticsTracker()
        print("✅ Analytics tracker initialized successfully")
    except Exception as e:
        print(f"❌ Analytics test failed: {str(e)}")

    # Test 5: Campaign manager
    print("\n5. Campaign Manager Test")
    try:
        campaign_manager = AutomatedCampaignManager()
        campaign_types = campaign_manager.campaign_types
        print(f"✅ Found {len(campaign_types)} campaign types")

        # List some campaign types
        sample_campaigns = list(campaign_types.keys())[:3]
        print(f"✅ Sample campaigns: {', '.join(sample_campaigns)}")
    except Exception as e:
        print(f"❌ Campaign manager test failed: {str(e)}")

    print("\n" + "=" * 50)
    print("🎯 Basic functionality test completed!")

    return True


if __name__ == "__main__":
    try:
        test_basic_functionality()
        exit(0)
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        exit(1)
