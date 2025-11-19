#!/usr/bin/env python3
"""
Debug board member addition process
Run with: bench --site dev.veganisme.net execute verenigingen.debug_board_addition.debug_board_addition_flow
"""

import frappe


def debug_board_addition_flow():
    """Debug why automatic member addition isn't working"""

    print("🔍 Debugging board member addition process...")

    try:
        chapter_name = "Noord-Limburg"
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        print(f"📋 Current Chapter State:")
        print(f"  Board members: {len(chapter_doc.board_members or [])}")
        print(f"  Regular members: {len(chapter_doc.members or [])}")

        # Show current board members
        print(f"\n👥 Current Board Members:")
        for i, bm in enumerate(chapter_doc.board_members or []):
            print(f"  {i+1}. {bm.volunteer_name} - Active: {bm.is_active} - Role: {bm.chapter_role}")

        # Show current regular members
        print(f"\n📋 Current Regular Members:")
        for i, m in enumerate(chapter_doc.members or []):
            print(f"  {i+1}. {m.member_name} - Enabled: {m.enabled}")

        # Find Parko's records
        parko_member = frappe.get_value(
            "Member", {"full_name": "Parko Janssen"}, ["name", "full_name"], as_dict=True
        )
        parko_volunteer = frappe.get_value(
            "Verenigingen Volunteer",
            {"volunteer_name": "Parko Janssen"},
            ["name", "volunteer_name", "member"],
            as_dict=True,
        )

        print(f"\n🔍 Parko's Records:")
        print(f"  Member: {parko_member}")
        print(f"  Volunteer: {parko_volunteer}")

        if not parko_volunteer:
            print("❌ No volunteer record found for Parko Janssen")
            return

        if not parko_member:
            print("❌ No member record found for Parko Janssen")
            return

        # Test the board manager add_board_member method directly
        print(f"\n🧪 Testing board member addition process...")

        # First, remove Parko if he's already on the board
        parko_on_board = False
        for bm in chapter_doc.board_members or []:
            if bm.volunteer == parko_volunteer.name and bm.is_active:
                print(f"  Found active board membership, removing first...")
                chapter_doc.board_manager.remove_board_member(parko_volunteer.name)
                parko_on_board = True
                break

        # Check if he's in members before adding to board
        parko_in_members_before = False
        for m in chapter_doc.members or []:
            if m.member == parko_member.name and m.enabled:
                parko_in_members_before = True
                break

        print(f"  Parko in members before board addition: {parko_in_members_before}")

        # Test adding him to the board using the board manager
        print(f"  Adding {parko_volunteer.volunteer_name} to board as 'Algemeen bestuurslid'...")

        result = chapter_doc.board_manager.add_board_member(
            volunteer=parko_volunteer.name,
            role="Algemeen bestuurslid",
            from_date=frappe.utils.today(),
            notify=False,
        )

        print(f"  Board addition result: {result}")

        # Check if he's now in members after adding to board
        chapter_doc.reload()
        parko_in_members_after = False
        for m in chapter_doc.members or []:
            if m.member == parko_member.name and m.enabled:
                parko_in_members_after = True
                print(f"  ✅ Found in members: {m.member_name}")
                break

        print(f"  Parko in members after board addition: {parko_in_members_after}")

        # If he's still not in members, test the _add_to_chapter_members method directly
        if not parko_in_members_after:
            print(f"\n🔧 Testing _add_to_chapter_members directly...")

            try:
                board_manager = chapter_doc.board_manager
                print(f"  Calling _add_to_chapter_members({parko_member.name})...")
                board_manager._add_to_chapter_members(parko_member.name)

                print(f"  Saving chapter document...")
                chapter_doc.save()

                # Check again
                chapter_doc.reload()
                for m in chapter_doc.members or []:
                    if m.member == parko_member.name and m.enabled:
                        print(f"  ✅ Now found in members: {m.member_name}")
                        break
                else:
                    print(f"  ❌ Still not found in members after manual addition")

            except Exception as e:
                print(f"  ❌ Error in _add_to_chapter_members: {e}")
                import traceback

                traceback.print_exc()

        # Check if there are any validation errors
        print(f"\n🔍 Checking for validation issues...")

        # Test if member record is valid
        try:
            member_doc = frappe.get_doc("Member", parko_member.name)
            print(f"  Member status: {member_doc.status}")
            print(f"  Member enabled: {getattr(member_doc, 'enabled', 'N/A')}")
        except Exception as e:
            print(f"  ❌ Error loading member: {e}")

        # Test if volunteer record is valid
        try:
            volunteer_doc = frappe.get_doc("Volunteer", parko_volunteer.name)
            print(f"  Volunteer status: {volunteer_doc.status}")
            print(f"  Volunteer member link: {volunteer_doc.member}")
        except Exception as e:
            print(f"  ❌ Error loading volunteer: {e}")

        # Check recent error logs
        print(f"\n📝 Recent Error Logs:")
        error_logs = frappe.get_all(
            "Error Log",
            filters=[["creation", ">=", frappe.utils.add_days(frappe.utils.today(), -1)]],
            fields=["error", "creation"],
            order_by="creation desc",
            limit=3,
        )

        for log in error_logs:
            if "board" in log.error.lower() or "member" in log.error.lower() or "parko" in log.error.lower():
                print(f"  {log.creation}: {log.error[:200]}...")

        return {
            "parko_member": parko_member,
            "parko_volunteer": parko_volunteer,
            "in_members_before": parko_in_members_before,
            "in_members_after": parko_in_members_after,
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e)}
