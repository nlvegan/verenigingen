#!/usr/bin/env python3
"""
Test script for board member addition process
Run this from the bench directory: python apps/verenigingen/test_board_member_addition.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath("."))


def test_board_member_addition():
    print("🧪 Testing board member addition process...")

    try:
        import frappe

        frappe.init(site="dev.veganisme.net")
        frappe.connect()

        # Get Noord-Limburg chapter
        chapter_name = "Noord-Limburg"
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        print(f"📋 Current state of {chapter_name}:")
        print(f"  Board members: {len(chapter_doc.board_members or [])}")
        print(f"  Regular members: {len(chapter_doc.members or [])}")

        # Test the _add_to_chapter_members method directly
        print("\n🔧 Testing _add_to_chapter_members method...")

        # Find Parko Janssen if he exists
        parko_member = None
        parko_volunteer = None

        # Search for Parko
        members = frappe.get_all(
            "Member", filters=[["full_name", "like", "%Parko%"]], fields=["name", "full_name"]
        )

        if members:
            parko_member = members[0]
            print(f"✅ Found member: {parko_member.full_name} ({parko_member.name})")

            # Check if he has a volunteer record
            volunteers = frappe.get_all(
                "Volunteer",
                filters={"member": parko_member.name},
                fields=["name", "volunteer_name", "member"],
            )

            if volunteers:
                parko_volunteer = volunteers[0]
                print(f"✅ Found volunteer: {parko_volunteer.volunteer_name} ({parko_volunteer.name})")
            else:
                print(f"❌ No volunteer record found for member {parko_member.name}")
        else:
            print("❌ No member found with name Parko")

        if parko_member:
            # Test if he's already in chapter members
            is_already_member = False
            for member in chapter_doc.members or []:
                if member.member == parko_member.name:
                    is_already_member = True
                    print(f"📋 Already in chapter members: Enabled={member.enabled}")
                    break

            if not is_already_member:
                print("📋 Not currently in chapter members")

                # Test the board manager's _add_to_chapter_members method
                try:
                    board_manager = chapter_doc.board_manager
                    print("🔧 Testing _add_to_chapter_members manually...")

                    # This should add him to the members list
                    board_manager._add_to_chapter_members(parko_member.name)

                    # Check if it worked
                    added = False
                    for member in chapter_doc.members or []:
                        if member.member == parko_member.name:
                            added = True
                            print(f"✅ Successfully added to chapter members: {member.member_name}")
                            break

                    if not added:
                        print("❌ Failed to add to chapter members")

                    # Save the document to persist changes
                    chapter_doc.save()
                    print("💾 Chapter document saved")

                except Exception as e:
                    print(f"❌ Error testing _add_to_chapter_members: {e}")
                    import traceback

                    traceback.print_exc()

        # Check if there are any board members without corresponding chapter members
        print("\n🔍 Checking board members vs chapter members consistency...")

        board_member_ids = set()
        for bm in chapter_doc.board_members or []:
            if bm.is_active and bm.volunteer:
                # Get member ID from volunteer
                volunteer_doc = frappe.get_doc("Volunteer", bm.volunteer)
                if volunteer_doc.member:
                    board_member_ids.add(volunteer_doc.member)
                    print(f"  Board: {bm.volunteer_name} -> Member: {volunteer_doc.member}")

        chapter_member_ids = set()
        for cm in chapter_doc.members or []:
            if cm.enabled:
                chapter_member_ids.add(cm.member)
                print(f"  Chapter: {cm.member_name} -> Member: {cm.member}")

        missing_from_chapter = board_member_ids - chapter_member_ids
        if missing_from_chapter:
            print(f"⚠️  Board members missing from chapter members: {missing_from_chapter}")
        else:
            print("✅ All board members are in chapter member list")

        frappe.destroy()

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_board_member_addition()
