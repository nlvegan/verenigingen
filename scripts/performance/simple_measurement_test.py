#!/usr/bin/env python3
"""
Simple measurement test using direct API calls
"""

import frappe

def test_measurement_api():
    """Test basic measurement functionality"""
    
    print("Testing Performance Measurement API...")
    
    try:
        # Get a test member
        members = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "full_name"],
            limit=1
        )
        
        if not members:
            print("No members with customers found")
            return
            
        test_member = members[0]
        print(f"Testing with member: {test_member.name}")
        
        # Test API import
        from verenigingen.api.performance_measurement_api import measure_member_performance
        
        # Run measurement
        result = measure_member_performance(test_member.name)
        
        if result.get('success'):
            data = result['data']
            qp = data.get('query_performance', {})
            
            print(f"✓ Measurement successful:")
            print(f"  - Member: {test_member.full_name}")
            print(f"  - Queries: {qp.get('total_queries', 0)}")
            print(f"  - Time: {qp.get('total_execution_time', 0):.3f}s")
            print(f"  - Bottlenecks: {len(data.get('bottlenecks', []))}")
            print(f"  - Priority: {data.get('optimization_priority', 'unknown')}")
            
            return True
        else:
            print(f"✗ Measurement failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        print(traceback.format_exc())
        return False