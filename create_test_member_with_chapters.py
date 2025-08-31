import frappe


def create_test_member_with_chapter():
    """Create a test member with chapter relationship to validate API functionality"""

    # Get an existing region
    regions = frappe.get_all("Region", limit=1, pluck="name")
    if not regions:
        print("No regions found - creating one")
        region = frappe.get_doc({"doctype": "Region", "region_name": "API-Test-Region"})
        region.insert()
        region_name = region.name
    else:
        region_name = regions[0]
        print(f"Using existing region: {region_name}")

    # Create test chapter
    chapter_name = f"API-Test-Chapter-{frappe.utils.random_string(5)}"
    chapter = frappe.get_doc(
        {"doctype": "Chapter", "name": chapter_name, "region": region_name, "status": "Active"}
    )
    chapter.insert()
    print(f"Created chapter: {chapter.name}")

    # Create test member
    member_name = f"API-Test-Member-{frappe.utils.random_string(5)}"
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": "API",
            "last_name": "TestMember",
            "email": f"api.test.{frappe.utils.random_string(5)}@test.invalid",
            "birth_date": "1990-01-01",
            "status": "Active",
        }
    )
    member.insert()
    print(f"Created member: {member.name}")

    # Create customer for member if needed
    if not member.customer:
        member.create_customer()
        member.reload()
        print(f"Created customer: {member.customer}")

    # Add member to chapter
    chapter.append(
        "members",
        {"member": member.name, "status": "Active", "enabled": 1, "chapter_join_date": frappe.utils.today()},
    )
    chapter.save()
    print(f"Added member {member.name} to chapter {chapter.name}")

    # Test the API
    from verenigingen.api.member_management import get_members_with_chapter_info

    result = get_members_with_chapter_info(filters={"status": "Active"}, limit=20)

    print(f"\nAPI Test Results:")
    print(f"Success: {result['success']}")
    print(f"Total members returned: {result['total_count']}")
    print(f"Query optimization: {result['query_optimization']}")

    # Find our test member in results
    test_member_found = None
    for member_data in result["members"]:
        if member_data["name"] == member.name:
            test_member_found = member_data
            break

    if test_member_found:
        print(f"\nTest member found: {test_member_found['full_name']}")
        print(f"Chapters: {test_member_found['chapters']}")
        if test_member_found["chapters"]:
            print("✅ Chapter relationship working!")
        else:
            print("❌ No chapter relationship found")
    else:
        print("❌ Test member not found in results")

    return member.name, chapter.name


frappe.init(site="dev.veganisme.net")
frappe.connect()
frappe.set_user("Administrator")

try:
    member_name, chapter_name = create_test_member_with_chapter()
    print(f"\nCreated: {member_name} in {chapter_name}")
except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
finally:
    frappe.destroy()
