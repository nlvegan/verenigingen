#!/usr/bin/env python3
"""
Bench-compatible debug script for chapter membership
Run with: bench --site dev.veganisme.net execute verenigingen.bench_debug_chapter.debug_parko_issue
"""

import frappe


def debug_parko_issue():
    """Debug Parko Janssen membership issue in Noord-Limburg chapter"""

    print("🔍 Debugging Noord-Limburg chapter membership...")

    try:
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
        parko_volunteer_id = None

        for i, bm in enumerate(board_members):
            print(
                f"  {i+1}. {bm.volunteer_name} ({bm.volunteer}) - Role: {bm.chapter_role} - Active: {bm.is_active}"
            )
            if "Parko" in bm.volunteer_name or "Janssen" in bm.volunteer_name:
                parko_on_board = True
                parko_volunteer_id = bm.volunteer
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
            filters=[["full_name", "like", "%Parko%"]],
            fields=["name", "full_name", "email", "status"],
        )

        if members_found:
            print("📋 Found in Members:")
            for member in members_found:
                print(
                    f"  - {member.full_name} ({member.name}) - Status: {member.status} - Email: {member.email}"
                )
        else:
            print("❌ No members found with Parko")

        # Also search for Janssen
        janssen_members = frappe.get_all(
            "Member",
            filters=[["full_name", "like", "%Janssen%"]],
            fields=["name", "full_name", "email", "status"],
        )

        if janssen_members:
            print("📋 Found members with Janssen:")
            for member in janssen_members:
                print(
                    f"  - {member.full_name} ({member.name}) - Status: {member.status} - Email: {member.email}"
                )

        # Search volunteers
        volunteers_found = frappe.get_all(
            "Volunteer",
            filters=[["volunteer_name", "like", "%Parko%"]],
            fields=["name", "volunteer_name", "member", "email", "status"],
        )

        if not volunteers_found:
            volunteers_found = frappe.get_all(
                "Volunteer",
                filters=[["volunteer_name", "like", "%Janssen%"]],
                fields=["name", "volunteer_name", "member", "email", "status"],
            )

        if volunteers_found:
            print("👥 Found in Volunteers:")
            for volunteer in volunteers_found:
                print(
                    f"  - {volunteer.volunteer_name} ({volunteer.name}) - Member: {volunteer.member} - Status: {volunteer.status}"
                )
        else:
            print("❌ No volunteers found with Parko or Janssen")

        # If Parko is on board but not in members, try to fix it
        if parko_on_board and not parko_in_members and parko_volunteer_id:
            print(f"\n🔧 Attempting to fix missing member issue...")
            try:
                volunteer_doc = frappe.get_doc("Volunteer", parko_volunteer_id)
                if volunteer_doc.member:
                    print(f"  Found member ID: {volunteer_doc.member}")

                    # Use the board manager to add to chapter members
                    board_manager = chapter_doc.board_manager
                    board_manager._add_to_chapter_members(volunteer_doc.member)

                    # Save the chapter
                    chapter_doc.save()

                    print(f"  ✅ Added {volunteer_doc.volunteer_name} to chapter members")

                    # Verify it worked
                    chapter_doc.reload()
                    for member in chapter_doc.members or []:
                        if member.member == volunteer_doc.member:
                            print(f"  ✅ Verified: {member.member_name} now in member list")
                            break
                else:
                    print(f"  ❌ Volunteer {parko_volunteer_id} has no associated member")

            except Exception as e:
                print(f"  ❌ Error fixing membership: {e}")
                import traceback

                traceback.print_exc()

        # Check recent Comments for this chapter (audit trail)
        print(f"\n📝 Recent Comments for {chapter_name}:")
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Chapter", "reference_name": chapter_name, "comment_type": "Info"},
            fields=["content", "creation", "owner"],
            order_by="creation desc",
            limit=5,
        )

        for comment in comments:
            print(f"  {comment.creation}: {comment.content} (by {comment.owner})")

        print("\n🎯 Summary:")
        print(f"  Board Member: {'✅' if parko_on_board else '❌'}")
        print(f"  Regular Member: {'✅' if parko_in_members else '❌'}")
        print(f"  Exists in DB: {'✅' if (members_found or volunteers_found) else '❌'}")

        return {
            "parko_on_board": parko_on_board,
            "parko_in_members": parko_in_members,
            "members_found": len(members_found) if members_found else 0,
            "volunteers_found": len(volunteers_found) if volunteers_found else 0,
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e)}
