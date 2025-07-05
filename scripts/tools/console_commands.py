# Console commands to run in bench console
# Run: bench --site dev.veganisme.net console
# Then copy and paste these commands one by one:

import frappe

print("=== Checking Noord-Limburg Chapter ===")

# Check if chapter exists
chapter_name = "Noord-Limburg"
if frappe.db.exists("Chapter", chapter_name):
    print(f"✅ Chapter {chapter_name} exists")

    # Get chapter document
    chapter_doc = frappe.get_doc("Chapter", chapter_name)

    # Show board members
    print(f"\n👥 Board Members ({len(chapter_doc.board_members or [])} total):")
    for i, bm in enumerate(chapter_doc.board_members or []):
        print(f"  {i+1}. {bm.volunteer_name} - Role: {bm.chapter_role} - Active: {bm.is_active}")

    # Show regular members
    print(f"\n📋 Chapter Members ({len(chapter_doc.members or [])} total):")
    for i, m in enumerate(chapter_doc.members or []):
        print(f"  {i+1}. {m.member_name} - Enabled: {m.enabled}")

else:
    print(f"❌ Chapter {chapter_name} not found")

print("\n=== Searching for Parko Janssen ===")

# Search for Parko in members
parko_members = frappe.get_all(
    "Member", filters=[["full_name", "like", "%Parko%"]], fields=["name", "full_name", "status"]
)

if parko_members:
    print("📋 Found Parko in Members:")
    for m in parko_members:
        print(f"  - {m.full_name} ({m.name}) - Status: {m.status}")
else:
    print("❌ No Parko found in Members")

# Search for Parko in volunteers
parko_volunteers = frappe.get_all(
    "Volunteer",
    filters=[["volunteer_name", "like", "%Parko%"]],
    fields=["name", "volunteer_name", "member", "status"],
)

if parko_volunteers:
    print("👥 Found Parko in Volunteers:")
    for v in parko_volunteers:
        print(f"  - {v.volunteer_name} ({v.name}) - Member: {v.member} - Status: {v.status}")
else:
    print("❌ No Parko found in Volunteers")

print("\n=== Manual Fix (if needed) ===")
print("# If Parko is on board but not in members, run:")
print("# chapter_doc.board_manager._add_to_chapter_members('MEMBER_ID_HERE')")
print("# chapter_doc.save()")
