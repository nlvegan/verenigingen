# Simple console test for board member addition
# Run in bench console: bench --site dev.veganisme.net console

import frappe

print("=== Simple Board Member Addition Test ===")

# Clear any existing state
frappe.db.rollback()
frappe.db.commit()

# Get chapter
chapter_name = "Noord-Limburg"
chapter_doc = frappe.get_doc("Chapter", chapter_name)

print(f"Chapter: {chapter_doc.name}")
print(f"Current board members: {len(chapter_doc.board_members or [])}")
print(f"Current members: {len(chapter_doc.members or [])}")

# Find Parko
parko_volunteer = frappe.db.get_value("Volunteer", {"volunteer_name": "Parko Janssen"}, "name")
parko_member = frappe.db.get_value("Member", {"full_name": "Parko Janssen"}, "name")

print(f"Parko volunteer: {parko_volunteer}")
print(f"Parko member: {parko_member}")

if parko_volunteer and parko_member:
    # Remove him from board first if present
    for bm in chapter_doc.board_members or []:
        if bm.volunteer == parko_volunteer and bm.is_active:
            bm.is_active = 0
            bm.to_date = frappe.utils.today()
            print("Deactivated existing board membership")

    # Remove him from members if present
    for m in chapter_doc.members or []:
        if m.member == parko_member:
            chapter_doc.members.remove(m)
            print("Removed from members list")

    # Save to clear state
    chapter_doc.save()

    print("\n=== Adding to Board ===")

    # Add to board using the manager
    result = chapter_doc.board_manager.add_board_member(
        volunteer=parko_volunteer, role="Algemeen bestuurslid", from_date=frappe.utils.today(), notify=False
    )

    print(f"Addition result: {result}")

    # Check results
    chapter_doc.reload()

    print(f"\nAfter addition:")
    print(f"Board members: {len(chapter_doc.board_members or [])}")
    for bm in chapter_doc.board_members or []:
        if bm.is_active:
            print(f"  - {bm.volunteer_name} (Active)")

    print(f"Members: {len(chapter_doc.members or [])}")
    for m in chapter_doc.members or []:
        if m.enabled:
            print(f"  - {m.member_name} (Enabled)")

    # Check if Parko is in both lists
    parko_on_board = any(
        bm.volunteer == parko_volunteer and bm.is_active for bm in (chapter_doc.board_members or [])
    )
    parko_in_members = any(m.member == parko_member and m.enabled for m in (chapter_doc.members or []))

    print(f"\nResult:")
    print(f"Parko on board: {parko_on_board}")
    print(f"Parko in members: {parko_in_members}")

    if parko_on_board and not parko_in_members:
        print("❌ ISSUE: Board addition worked but member addition failed")
    elif parko_on_board and parko_in_members:
        print("✅ SUCCESS: Both board and member addition worked")
    else:
        print("❌ ISSUE: Board addition failed")

print("\n=== Test Complete ===")
print("Run: frappe.db.commit() to save changes")
