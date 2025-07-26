#!/usr/bin/env python3
"""
Cleanup script for dues schedules with invalid member references
Addresses the 47 schedules discovered during invoice generation investigation
"""

import frappe
from frappe.utils import today, now


@frappe.whitelist()
def identify_invalid_schedules():
    """Identify schedules with non-existent member references"""
    
    # Get all active non-template schedules
    schedules = frappe.get_all('Membership Dues Schedule', 
        filters={'status': 'Active', 'is_template': 0},
        fields=['name', 'member', 'schedule_name', 'membership_type', 'dues_rate', 'creation']
    )
    
    invalid_schedules = []
    
    # Optimized: Eliminate N+1 query by batch checking member existence
    if schedules:
        # Collect all unique member IDs (eliminate None values)
        member_ids = list(set([s.member for s in schedules if s.member]))
        
        if member_ids:
            # Single query to get all existing member IDs
            existing_members = set(frappe.get_all('Member', 
                filters={'name': ['in', member_ids]},
                pluck='name'
            ))
            
            # Find schedules with non-existent members
            for schedule in schedules:
                if schedule.member:
                    if schedule.member not in existing_members:
                        invalid_schedules.append(schedule)
                else:
                    # Schedule with no member reference is also invalid
                    invalid_schedules.append(schedule)
        else:
            # All schedules have no member reference
            invalid_schedules = [s for s in schedules if not s.member]
    
    return {
        'total_schedules': len(schedules),
        'invalid_schedules': len(invalid_schedules),
        'details': invalid_schedules
    }


@frappe.whitelist()
def cleanup_invalid_schedules(dry_run=True):
    """
    Clean up schedules with invalid member references
    
    Args:
        dry_run (bool): If True, only report what would be done without making changes
    """
    
    # First identify invalid schedules
    invalid_data = identify_invalid_schedules()
    invalid_schedules = invalid_data['details']
    
    if not invalid_schedules:
        return {
            'success': True,
            'message': 'No invalid schedules found to clean up',
            'processed': 0
        }
    
    cleanup_actions = []
    
    try:
        if not dry_run:
            frappe.db.begin()
        
        for schedule_data in invalid_schedules:
            schedule_name = schedule_data['name']
            member_name = schedule_data['member']
            
            action = {
                'schedule': schedule_name,
                'member': member_name,
                'action': 'cancelled',
                'reason': f'Member {member_name} does not exist'
            }
            
            if not dry_run:
                # Load the schedule document
                schedule = frappe.get_doc('Membership Dues Schedule', schedule_name)
                
                # Cancel the schedule (set status to Cancelled)
                schedule.status = 'Cancelled'
                schedule.add_comment('Comment', f'Automatically cancelled due to invalid member reference: {member_name}')
                schedule.save()
                
                frappe.log_error(
                    f"Cancelled dues schedule {schedule_name} due to invalid member reference: {member_name}",
                    "Schedule Cleanup"
                )
            
            cleanup_actions.append(action)
        
        if not dry_run:
            frappe.db.commit()
            
        return {
            'success': True,
            'message': f'{"Would cancel" if dry_run else "Cancelled"} {len(cleanup_actions)} invalid schedules',
            'processed': len(cleanup_actions),
            'actions': cleanup_actions,
            'dry_run': dry_run
        }
        
    except Exception as e:
        if not dry_run:
            frappe.db.rollback()
        
        frappe.log_error(
            f"Error during schedule cleanup: {str(e)}",
            "Schedule Cleanup Error"
        )
        
        return {
            'success': False,
            'message': f'Error during cleanup: {str(e)}',
            'processed': 0,
            'actions': cleanup_actions
        }


@frappe.whitelist()
def validate_cleanup_results():
    """Validate that cleanup was successful"""
    
    # Check for remaining invalid schedules
    remaining_invalid = identify_invalid_schedules()
    
    # Check for recently cancelled schedules (cleanup evidence)
    recently_cancelled = frappe.get_all('Membership Dues Schedule',
        filters={
            'status': 'Cancelled',
            'modified': ['>=', frappe.utils.add_days(today(), -1)]
        },
        fields=['name', 'member', 'schedule_name', 'modified']
    )
    
    return {
        'remaining_invalid': remaining_invalid['invalid_schedules'],
        'recently_cancelled': len(recently_cancelled),
        'cancelled_details': recently_cancelled,
        'cleanup_effective': remaining_invalid['invalid_schedules'] == 0
    }


if __name__ == "__main__":
    # If run directly, perform dry run identification
    print("Identifying invalid dues schedules...")
    result = identify_invalid_schedules()
    print(f"Total schedules: {result['total_schedules']}")
    print(f"Invalid schedules: {result['invalid_schedules']}")
    
    if result['invalid_schedules'] > 0:
        print("\nFirst 10 invalid schedules:")
        for i, schedule in enumerate(result['details'][:10]):
            print(f"{i+1}. {schedule['name']}: member={schedule['member']}, type={schedule['membership_type']}")
        
        if result['invalid_schedules'] > 10:
            print(f"... and {result['invalid_schedules'] - 10} more")
    
    print("\nTo clean up these schedules, run:")
    print("bench --site dev.veganisme.net execute verenigingen.scripts.cleanup.cleanup_invalid_member_schedules.cleanup_invalid_schedules --kwargs '{\"dry_run\": false}'")