#!/usr/bin/env python3
"""
Setup script to configure member portal as home page for all members
Run this after installing the authentication hooks
"""

import frappe


def setup_member_portal_home():
    """Setup member portal as home page for all existing members"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        from verenigingen.utils.member_portal_utils import get_member_portal_stats, set_all_members_home_page

        print("🏠 Setting up Member Portal as home page for members...")
        print("=" * 60)

        # Get current stats
        stats = get_member_portal_stats()
        print(f"📊 Current Status:")
        print(f"   Total member users: {stats.get('total_member_users', 0)}")
        print(f"   Members with portal home: {stats.get('members_with_portal_home', 0)}")
        print(f"   Portal adoption rate: {stats.get('portal_adoption_rate', 0)}%")
        print()

        # Update all members to use member portal
        result = set_all_members_home_page("/member_portal")

        if result.get("success"):
            print(
                f"✅ SUCCESS: Updated {result['updated_count']} out of {result['total_members']} member users"
            )
            print(f"   Home page set to: {result['home_page']}")

            if result.get("errors"):
                print(f"⚠️  {len(result['errors'])} errors encountered:")
                for error in result["errors"][:5]:  # Show first 5 errors
                    print(f"   - {error}")
                if len(result["errors"]) > 5:
                    print(f"   ... and {len(result['errors']) - 5} more errors")
        else:
            print(f"❌ FAILED: {result.get('message', 'Unknown error')}")

        print()

        # Get updated stats
        updated_stats = get_member_portal_stats()
        print(f"📊 Updated Status:")
        print(f"   Total member users: {updated_stats.get('total_member_users', 0)}")
        print(f"   Members with portal home: {updated_stats.get('members_with_portal_home', 0)}")
        print(f"   Portal adoption rate: {updated_stats.get('portal_adoption_rate', 0)}%")

        print()
        print("🎉 Member portal home page setup complete!")
        print()
        print("📝 Next steps:")
        print("   1. Members will now be redirected to /member_portal when they log in")
        print("   2. The authentication hooks will handle new user redirects automatically")
        print("   3. Test by logging in as a member user")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        frappe.destroy()


if __name__ == "__main__":
    setup_member_portal_home()
