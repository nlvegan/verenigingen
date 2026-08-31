#!/usr/bin/env python3
"""
Debug script for checking chapter membership issues
Run this from the bench directory: python apps/verenigingen/debug_chapter_membership.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath("."))


def debug_chapter_membership():
    print("🔍 Debugging Noord-Limburg chapter membership...")

    try:
        import frappe

        frappe.init(site="dev.veganisme.net")
        frappe.connect()

        # Check if Noord-Limburg chapter exists
        chapter_name = "Noord-Limburg"

        if not frappe.db.exists("Chapter", chapter_name):
            print(f"❌ Chapter '{chapter_name}' does not exist")
            # List available chapters
            chapters = frappe.get_all("Chapter", fields=["name", "region"])
            print("\n📋 Available chapters:")
            for ch in chapters:
                print(f"  - {ch.name} ({ch.region})")
            return

        print(f"✅ Chapter '{chapter_name}' found")

        # Get chapter document
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Check board members
        print(f"\n👥 Board Members in {chapter_name}:")
        board_members = chapter_doc.board_members or []
        parko_on_board = False

        for i, bm in enumerate(board_members):
            print(
                f"  {i+1}. {bm.volunteer_name} ({bm.volunteer}) - Role: {bm.chapter_role} - Active: {bm.is_active}"
            )
            if "Parko" in bm.volunteer_name or "Janssen" in bm.volunteer_name:
                parko_on_board = True
                print(f"    ⭐ Found Parko Janssen on board!")

                # Check if volunteer exists
                if frappe.db.exists("Volunteer", bm.volunteer):
                    vol_doc = frappe.get_doc("Volunteer", bm.volunteer)
                    print(f"    📋 Volunteer details: {vol_doc.volunteer_name}, Member: {vol_doc.member}")
                else:
                    print(f"    ❌ Volunteer {bm.volunteer} does not exist!")

        if not parko_on_board:
            print("  ❌ Parko Janssen not found on board")

        # Check regular members
        print(f"\n📋 Regular Members in {chapter_name}:")
        members = chapter_doc.members or []
        parko_in_members = False

        for i, member in enumerate(members):
            print(f"  {i+1}. {member.member_name} ({member.member}) - Enabled: {member.enabled}")
            if "Parko" in member.member_name or "Janssen" in member.member_name:
                parko_in_members = True
                print(f"    ⭐ Found Parko Janssen in member list!")

        if not parko_in_members:
            print("  ❌ Parko Janssen not found in member list")

        # Search for Parko Janssen across all members and volunteers
        print("\n🔍 Searching for Parko Janssen in database...")

        # Search members
        members_found = frappe.get_all(
            "Member",
            filters=[["full_name", "like", "%Parko%"], ["full_name", "like", "%Janssen%"]],
            fields=["name", "full_name", "email", "status"],
        )

        if members_found:
            print("📋 Found in Members:")
            for member in members_found:
                print(
                    f"  - {member.full_name} ({member.name}) - Status: {member.status} - Email: {member.email}"
                )
        else:
            print("❌ No members found with Parko Janssen")

        # Search volunteers
        volunteers_found = frappe.get_all(
            "Volunteer",
            filters=[["volunteer_name", "like", "%Parko%"]],
            fields=["name", "volunteer_name", "member", "email", "status"],
        )

        if volunteers_found:
            print("👥 Found in Volunteers:")
            for volunteer in volunteers_found:
                print(
                    f"  - {volunteer.volunteer_name} ({volunteer.name}) - Member: {volunteer.member} - Status: {volunteer.status}"
                )
        else:
            print("❌ No volunteers found with Parko")

        # Check recent Comments for this chapter (audit trail)
        print(f"\n📝 Recent Comments for {chapter_name}:")
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Chapter", "reference_name": chapter_name, "comment_type": "Info"},
            fields=["content", "creation", "owner"],
            order_by="creation desc",
            limit=10,
        )

        for comment in comments:
            print(f"  {comment.creation}: {comment.content} (by {comment.owner})")

        # Check if there are any Error Logs related to this
        print(f"\n⚠️  Recent Error Logs (last 24 hours):")
        error_logs = frappe.get_all(
            "Error Log",
            filters=[["creation", ">=", frappe.utils.add_days(frappe.utils.today(), -1)]],
            fields=["error", "creation"],
            order_by="creation desc",
            limit=5,
        )

        for log in error_logs:
            if "Parko" in log.error or "Noord-Limburg" in log.error or "board" in log.error.lower():
                print(f"  {log.creation}: {log.error[:200]}...")

        print("\n🎯 Summary:")
        print(f"  Board Member: {'✅' if parko_on_board else '❌'}")
        print(f"  Regular Member: {'✅' if parko_in_members else '❌'}")
        print(f"  Exists in DB: {'✅' if (members_found or volunteers_found) else '❌'}")

        frappe.destroy()

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_chapter_membership()
