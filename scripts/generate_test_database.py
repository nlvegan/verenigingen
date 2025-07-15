#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate Test Database for Performance Testing
Creates a persistent test database with a large volume of data for DocType version tracking performance tests

This script:
1. Creates test data WITHOUT automatic rollback (persists in database)
2. Generates realistic volumes of data for performance testing
3. Tracks created records for optional cleanup
4. Provides options for different test scenarios
"""

import sys
import os
import time
import argparse
from datetime import datetime

# Add frappe bench to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import frappe
from frappe.utils import now_datetime, add_days, getdate

# Import the test data factory
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from verenigingen.tests.fixtures.test_data_factory import TestDataFactory
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory


class PersistentTestDataGenerator:
    """Generate persistent test data for performance testing"""
    
    def __init__(self, site_name, cleanup_on_exit=False):
        self.site_name = site_name
        self.cleanup_on_exit = cleanup_on_exit
        self.created_records = []
        self.start_time = None
        self.stats = {
            'members': 0,
            'memberships': 0,
            'volunteers': 0,
            'chapters': 0,
            'expenses': 0,
            'updates': 0,
            'total_time': 0
        }
        
    def connect(self):
        """Connect to Frappe site"""
        frappe.init(site=self.site_name)
        frappe.connect()
        frappe.db.begin()  # Start explicit transaction
        
    def disconnect(self):
        """Disconnect from Frappe site"""
        if not self.cleanup_on_exit:
            frappe.db.commit()  # Commit changes to persist data
            print("✅ Data committed to database")
        else:
            frappe.db.rollback()  # Rollback if cleanup requested
            print("🧹 Data rolled back (cleanup mode)")
        frappe.destroy()
        
    def generate_version_tracking_test_data(self, member_count=10000, update_cycles=5):
        """
        Generate test data specifically for version tracking performance tests
        
        Args:
            member_count: Number of members to create
            update_cycles: Number of update cycles to simulate version history
        """
        print(f"🚀 Generating test data for version tracking performance testing...")
        print(f"   - Target members: {member_count}")
        print(f"   - Update cycles: {update_cycles}")
        print(f"   - Site: {self.site_name}")
        print(f"   - Persistence: {'ENABLED' if not self.cleanup_on_exit else 'DISABLED (cleanup mode)'}")
        print()
        
        self.start_time = time.time()
        
        try:
            # Use regular test factory for bulk creation
            factory = TestDataFactory(cleanup_on_exit=False)
            
            # Create base data
            print("📦 Creating base data...")
            chapters = factory.create_test_chapters(count=20)
            self.stats['chapters'] = len(chapters)
            
            membership_types = factory.create_test_membership_types(count=5)
            
            # Create members in batches for better performance
            print(f"👥 Creating {member_count} members...")
            batch_size = 1000
            all_members = []
            
            for i in range(0, member_count, batch_size):
                current_batch = min(batch_size, member_count - i)
                print(f"   Batch {i//batch_size + 1}: Creating {current_batch} members...")
                
                members = factory.create_test_members(
                    chapters, 
                    count=current_batch,
                    status_distribution={"Active": 0.8, "Suspended": 0.1, "Terminated": 0.1}
                )
                all_members.extend(members)
                self.stats['members'] += len(members)
                
                # Commit periodically to avoid large transactions
                if i % 5000 == 0 and i > 0:
                    frappe.db.commit()
                    print(f"   💾 Intermediate commit at {i} members")
            
            # Create memberships
            print("📋 Creating memberships...")
            memberships = factory.create_test_memberships(
                all_members, 
                membership_types, 
                coverage_ratio=0.9,
                with_subscriptions=False  # Skip subscriptions for faster generation
            )
            self.stats['memberships'] = len(memberships)
            
            # Create volunteers
            print("🤝 Creating volunteers...")
            volunteers = factory.create_test_volunteers(all_members, volunteer_ratio=0.3)
            self.stats['volunteers'] = len(volunteers)
            
            # Create expenses for version tracking
            print("💸 Creating volunteer expenses...")
            expenses = factory.create_test_expenses(volunteers, expense_count_per_volunteer=3)
            self.stats['expenses'] = len(expenses)
            
            # Commit base data
            frappe.db.commit()
            print("✅ Base data created and committed")
            
            # Simulate version history through updates
            print(f"\n🔄 Simulating {update_cycles} update cycles for version history...")
            
            for cycle in range(update_cycles):
                print(f"\n   Cycle {cycle + 1}/{update_cycles}:")
                
                # Update member data
                update_count = min(1000, len(all_members) // 10)  # Update 10% per cycle, max 1000
                print(f"   - Updating {update_count} members...")
                
                for i in range(update_count):
                    member = all_members[i + (cycle * update_count) % len(all_members)]
                    
                    # Simulate various updates
                    updates = []
                    
                    if cycle % 2 == 0:
                        # Update contact info
                        member.reload()
                        member.contact_number = f"+31 6 {99000000 + i + cycle}"
                        updates.append("contact")
                    
                    if cycle % 3 == 0:
                        # Update address
                        member.reload()
                        member.city = f"Updated City {cycle}"
                        member.postal_code = f"{5000 + i:04d}XY"
                        updates.append("address")
                    
                    if cycle == update_cycles - 1 and i < 100:
                        # Status changes in last cycle
                        member.reload()
                        if member.status == "Active":
                            member.status = "Suspended"
                            member.suspension_reason = f"Test suspension cycle {cycle}"
                            updates.append("status")
                    
                    if updates:
                        member.save()
                        self.stats['updates'] += 1
                
                # Update some volunteer expenses
                expense_update_count = min(500, len(expenses) // 5)
                print(f"   - Updating {expense_update_count} expenses...")
                
                for i in range(expense_update_count):
                    expense = expenses[i + (cycle * expense_update_count) % len(expenses)]
                    expense.reload()
                    
                    # Update amount and status
                    expense.amount = expense.amount * 1.1  # 10% increase
                    if expense.status == "Draft":
                        expense.status = "Submitted"
                    elif expense.status == "Submitted":
                        expense.status = "Approved"
                    
                    expense.save()
                    self.stats['updates'] += 1
                
                # Commit after each cycle
                frappe.db.commit()
                print(f"   ✅ Cycle {cycle + 1} completed and committed")
            
            # Calculate and display statistics
            self.stats['total_time'] = time.time() - self.start_time
            self.display_statistics()
            
            # Save metadata about the test database
            self.save_test_metadata()
            
        except Exception as e:
            print(f"\n❌ Error during data generation: {e}")
            frappe.db.rollback()
            raise
            
    def display_statistics(self):
        """Display generation statistics"""
        print("\n📊 Test Data Generation Statistics:")
        print("=" * 50)
        print(f"Members created:     {self.stats['members']:,}")
        print(f"Memberships created: {self.stats['memberships']:,}")
        print(f"Volunteers created:  {self.stats['volunteers']:,}")
        print(f"Chapters created:    {self.stats['chapters']:,}")
        print(f"Expenses created:    {self.stats['expenses']:,}")
        print(f"Updates performed:   {self.stats['updates']:,}")
        print(f"Total time:          {self.stats['total_time']:.2f} seconds")
        print(f"Records/second:      {(sum(self.stats.values()) - self.stats['total_time']) / self.stats['total_time']:.2f}")
        
    def save_test_metadata(self):
        """Save metadata about the test database"""
        metadata = {
            'generated_at': now_datetime().isoformat(),
            'site': self.site_name,
            'stats': self.stats,
            'purpose': 'DocType version tracking performance testing',
            'generator': 'generate_test_database.py'
        }
        
        # Save to a custom doctype or file
        metadata_path = os.path.join(
            os.path.dirname(__file__), 
            f'test_database_metadata_{self.site_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )
        
        import json
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        print(f"\n📄 Metadata saved to: {metadata_path}")
        
    def cleanup_test_data(self):
        """Clean up all test data created by this script"""
        print("\n🧹 Cleaning up test data...")
        
        # Delete in reverse order of creation to respect dependencies
        cleanup_queries = [
            "DELETE FROM `tabVolunteer Expense` WHERE description LIKE 'Test expense%'",
            "DELETE FROM `tabSEPA Mandate` WHERE mandate_reference LIKE 'MANDT%'",
            "DELETE FROM `tabVolunteer` WHERE volunteer_name LIKE 'TestMember%'",
            "DELETE FROM `tabMembership` WHERE member IN (SELECT name FROM `tabMember` WHERE first_name LIKE 'TestMember%')",
            "DELETE FROM `tabMember` WHERE first_name LIKE 'TestMember%'",
            "DELETE FROM `tabChapter` WHERE introduction LIKE 'Automated test chapter%'",
        ]
        
        for query in cleanup_queries:
            try:
                result = frappe.db.sql(query)
                frappe.db.commit()
                print(f"✅ Executed: {query[:50]}...")
            except Exception as e:
                print(f"⚠️  Error executing cleanup query: {e}")
                
        print("✅ Cleanup completed")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Generate persistent test database for performance testing'
    )
    
    parser.add_argument(
        '--site',
        default='dev.veganisme.net',
        help='Frappe site name (default: dev.veganisme.net)'
    )
    
    parser.add_argument(
        '--members',
        type=int,
        default=10000,
        help='Number of members to create (default: 10000)'
    )
    
    parser.add_argument(
        '--update-cycles',
        type=int,
        default=5,
        help='Number of update cycles for version history (default: 5)'
    )
    
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Clean up existing test data instead of generating new data'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Rollback changes after generation (for testing)'
    )
    
    args = parser.parse_args()
    
    # Create generator
    generator = PersistentTestDataGenerator(
        site_name=args.site,
        cleanup_on_exit=args.dry_run
    )
    
    try:
        # Connect to site
        generator.connect()
        
        if args.cleanup:
            # Cleanup mode
            generator.cleanup_test_data()
        else:
            # Generation mode
            generator.generate_version_tracking_test_data(
                member_count=args.members,
                update_cycles=args.update_cycles
            )
            
    finally:
        # Disconnect (commits or rolls back based on settings)
        generator.disconnect()
        
    print("\n✅ Script completed successfully!")


if __name__ == "__main__":
    main()