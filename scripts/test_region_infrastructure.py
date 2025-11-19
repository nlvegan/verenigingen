import frappe

def test_region_infrastructure():
    """Test Region DocType infrastructure"""
    
    test_region_name = "Infrastructure Test Region"
    
    # Clean up any existing region first  
    existing_regions = frappe.get_all("Region", filters={"region_name": test_region_name}, fields=["name"])
    for region in existing_regions:
        print(f"Cleaning up existing region: {region.name}")
        frappe.delete_doc("Region", region.name)
    
    # Create region with proper validation
    region = frappe.get_doc({
        "doctype": "Region",
        "region_name": test_region_name,
        "region_code": "ITR1"  # 2-5 char validation requirement
    })
    
    region.insert()
    
    print(f"✓ Region created successfully")
    print(f"  region_name: {region.region_name}")
    print(f"  document name: {region.name}")  # This is the auto-generated name
    print(f"  region_code: {region.region_code}")
    
    # Test lookup patterns that Enhanced Test Factory needs
    lookup_by_region_name = frappe.db.exists("Region", {"region_name": test_region_name})
    lookup_by_doc_name = frappe.db.exists("Region", region.name)
    lookup_by_string = frappe.db.exists("Region", test_region_name)  # This is what fails
    
    print(f"  Lookup by region_name field: {lookup_by_region_name}")
    print(f"  Lookup by doc name: {lookup_by_doc_name}")
    print(f"  Lookup by string (what tests try): {lookup_by_string}")
    
    # Confirm the autoname issue
    if region.name != test_region_name:
        print(f"⚠️  CONFIRMED: region.name ({region.name}) != original region_name ({test_region_name})")
        print(f"   This confirms autoname converts the name - Enhanced Test Factory fix is needed")
        print(f"   Tests must use region.name ({region.name}) not original name ({test_region_name})")
    
    # Clean up
    frappe.delete_doc("Region", region.name)
    print(f"✓ Test region cleaned up")
    
    return region.name  # Return the actual name for reference