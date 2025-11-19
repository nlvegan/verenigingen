#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extended Test Data Factory
Provides comprehensive test data generation utilities for all app components
"""

import random
import string
from datetime import datetime, timedelta
from decimal import Decimal
import frappe
from frappe.utils import now_datetime, add_days, add_months, getdate
from verenigingen.tests.test_data_factory import TestDataFactory


class ExtendedTestDataFactory(TestDataFactory):
    """Extended test data factory with additional utilities"""
    
    def __init__(self, cleanup_on_exit=True):
        super().__init__(cleanup_on_exit=cleanup_on_exit)
        self.test_data_patterns = self._load_test_patterns()
        
    def _load_test_patterns(self):
        """Load common test data patterns"""
        return {
            "member_statuses": ["Active", "Inactive", "Pending", "Suspended", "Terminated"],
            "volunteer_skills": ["Event Planning", "Marketing", "Finance", "IT Support", 
                                "Communication", "Fundraising", "Teaching", "Cooking"],
            "expense_categories": ["Travel", "Materials", "Food", "Equipment", 
                                  "Printing", "Communication", "Other"],
            "donation_reasons": ["General Support", "Special Project", "Emergency Fund", 
                               "Annual Campaign", "Memorial", "Equipment Purchase"],
            "event_types": ["Meeting", "Workshop", "Conference", "Social", 
                           "Fundraiser", "Training", "Community Service"],
            "termination_reasons": ["Personal", "Relocation", "Financial", "Dissatisfaction", 
                                   "Health", "Time Constraints", "Other"]
        }
        
    # Enhanced Member Generation
    def create_member_lifecycle(self, stages=None):
        """Create members at different lifecycle stages"""
        if stages is None:
            stages = ["prospect", "applicant", "new_member", "active", "lapsed", "terminated"]
            
        members = {}
        base_date = add_months(getdate(), -24)  # Start 2 years ago
        
        for stage in stages:
            member_data = self._get_lifecycle_member_data(stage, base_date)
            members[stage] = self.create_member(**member_data)
            base_date = add_months(base_date, 3)
            
        return members
        
    def _get_lifecycle_member_data(self, stage, base_date):
        """Get member data for specific lifecycle stage"""
        data = {
            "full_name": f"Test {stage.title()} Member {self.random_string(4)}",
            "email": f"{stage}_{self.random_string(6)}@test.com"
        }
        
        stage_config = {
            "prospect": {"status": "Pending", "membership_type": None},
            "applicant": {"status": "Pending", "has_application": True},
            "new_member": {"status": "Active", "join_date": base_date},
            "active": {"status": "Active", "join_date": add_months(base_date, -12)},
            "lapsed": {"status": "Inactive", "last_payment": add_months(base_date, -6)},
            "terminated": {"status": "Terminated", "termination_date": base_date}
        }
        
        data.update(stage_config.get(stage, {}))
        return data
        
    # Enhanced Volunteer Generation
    def create_volunteer_team(self, team_name, size=5, with_leader=True):
        """Create a complete volunteer team with assignments"""
        volunteers = []
        
        # Create team
        team = frappe.new_doc("Volunteer Team")
        team.team_name = team_name
        team.description = f"Test team for {team_name}"
        team.is_active = 1
        team.insert()
        self.created_docs.append(team)
        
        # Create volunteers
        for i in range(size):
            is_leader = with_leader and i == 0
            volunteer = self.create_volunteer_with_assignments(
                team=team.name,
                is_leader=is_leader,
                skills=random.sample(self.test_data_patterns["volunteer_skills"], 3)
            )
            volunteers.append(volunteer)
            
        return {"team": team, "volunteers": volunteers}
        
    def create_volunteer_with_assignments(self, team=None, is_leader=False, skills=None):
        """Create volunteer with full assignment history"""
        volunteer = self.create_volunteer()
        
        # Add skills
        if skills:
            for skill in skills:
                skill_doc = frappe.new_doc("Volunteer Skill")
                skill_doc.volunteer = volunteer.name
                skill_doc.skill = skill
                skill_doc.proficiency = random.choice(["Beginner", "Intermediate", "Expert"])
                skill_doc.insert()
                self.created_docs.append(skill_doc)
                
        # Create assignments
        if team:
            assignment = frappe.new_doc("Volunteer Assignment")
            assignment.volunteer = volunteer.name
            assignment.team = team
            assignment.role = "Team Leader" if is_leader else "Team Member"
            assignment.start_date = add_months(getdate(), -6)
            assignment.is_active = 1
            assignment.insert()
            self.created_docs.append(assignment)
            
        return volunteer
        
    # Enhanced Financial Generation
    def create_donation_campaign(self, goal=10000, duration_days=30):
        """Create a donation campaign with multiple donations"""
        campaign = {
            "name": f"Test Campaign {self.random_string(6)}",
            "goal": goal,
            "start_date": getdate(),
            "end_date": add_days(getdate(), duration_days),
            "donations": []
        }
        
        # Create random donations
        num_donations = random.randint(10, 30)
        total_raised = 0
        
        for _ in range(num_donations):
            amount = random.uniform(10, 500)
            donation = self.create_donation(
                amount=amount,
                reason=f"{campaign['name']} - {random.choice(self.test_data_patterns['donation_reasons'])}"
            )
            campaign["donations"].append(donation)
            total_raised += amount
            
        campaign["total_raised"] = total_raised
        campaign["completion_percentage"] = (total_raised / goal) * 100
        
        return campaign
        
    def create_invoice_batch(self, count=10, date_range_days=30):
        """Create batch of invoices with various states"""
        invoices = []
        
        for i in range(count):
            posting_date = add_days(getdate(), -random.randint(0, date_range_days))
            
            # Vary invoice states
            if i % 4 == 0:
                status = "Overdue"
                due_date = add_days(posting_date, -random.randint(1, 30))
            elif i % 4 == 1:
                status = "Paid"
                due_date = add_days(posting_date, 30)
            elif i % 4 == 2:
                status = "Unpaid"
                due_date = add_days(getdate(), random.randint(1, 30))
            else:
                status = "Cancelled"
                due_date = add_days(posting_date, 30)
                
            invoice = self.create_sales_invoice(
                posting_date=posting_date,
                due_date=due_date,
                amount=random.uniform(25, 500)
            )
            
            invoices.append({
                "invoice": invoice,
                "status": status,
                "aging_days": (getdate() - posting_date).days
            })
            
        return invoices
        
    # Enhanced Chapter Generation
    def create_chapter_hierarchy(self, region_count=3, chapters_per_region=3):
        """Create complete chapter hierarchy with regions"""
        hierarchy = {"regions": {}}
        
        for r in range(region_count):
            region = self.create_region(name=f"Test Region {r+1}")
            hierarchy["regions"][region.name] = {
                "region": region,
                "chapters": []
            }
            
            for c in range(chapters_per_region):
                chapter = self.create_chapter(
                    region=region.name,
                    chapter_name=f"Chapter {r+1}-{c+1}"
                )
                
                # Add board members
                board = self.create_chapter_board(chapter)
                
                hierarchy["regions"][region.name]["chapters"].append({
                    "chapter": chapter,
                    "board": board
                })
                
        return hierarchy
        
    def create_chapter_board(self, chapter):
        """Create complete board for a chapter"""
        board_roles = [
            ("Voorzitter", True),
            ("Secretaris", False),
            ("Penningmeester", False),
            ("Algemeen Bestuurslid", False),
            ("Algemeen Bestuurslid", False)
        ]
        
        board_members = []
        
        for role, is_primary in board_roles:
            member = self.create_member(chapter=chapter.name)
            
            board_member = frappe.new_doc("Chapter Board Member")
            board_member.chapter = chapter.name
            board_member.member = member.name
            board_member.role = role
            board_member.start_date = add_months(getdate(), -12)
            board_member.is_active = 1
            
            if is_primary:
                board_member.is_primary_contact = 1
                
            board_member.insert()
            self.created_docs.append(board_member)
            board_members.append(board_member)
            
        return board_members
        
    # Enhanced Event Generation
    def create_event_series(self, event_type, count=5, frequency_days=7):
        """Create series of related events"""
        events = []
        base_date = getdate()
        
        for i in range(count):
            event_date = add_days(base_date, i * frequency_days)
            
            event = frappe.new_doc("Event")
            event.subject = f"{event_type} - Session {i+1}"
            event.event_type = event_type
            event.starts_on = datetime.combine(event_date, datetime.min.time()) + timedelta(hours=19)
            event.ends_on = event.starts_on + timedelta(hours=2)
            event.status = "Open"
            event.insert()
            self.created_docs.append(event)
            
            # Add random attendees
            attendees = []
            for _ in range(random.randint(5, 20)):
                member = self.create_member()
                attendees.append(member)
                
            events.append({
                "event": event,
                "attendees": attendees,
                "attendance_rate": random.uniform(0.6, 0.95)
            })
            
        return events
        
    # Enhanced Termination Scenarios
    def create_termination_scenarios(self):
        """Create various termination test scenarios"""
        scenarios = {}
        
        # Simple termination
        scenarios["simple"] = self._create_simple_termination()
        
        # Termination with appeal
        scenarios["with_appeal"] = self._create_termination_with_appeal()
        
        # Bulk termination
        scenarios["bulk"] = self._create_bulk_termination(count=5)
        
        # Termination with financial implications
        scenarios["financial"] = self._create_financial_termination()
        
        return scenarios
        
    def _create_simple_termination(self):
        """Create simple termination scenario"""
        member = self.create_member()
        
        termination = frappe.new_doc("Membership Termination Request")
        termination.member = member.name
        termination.reason = "Personal reasons"
        termination.termination_date = add_days(getdate(), 30)
        termination.insert()
        self.created_docs.append(termination)
        
        return {"member": member, "termination": termination}
        
    def _create_termination_with_appeal(self):
        """Create termination with appeal process"""
        scenario = self._create_simple_termination()
        
        # Create appeal
        appeal = frappe.new_doc("Termination Appeal")
        appeal.termination_request = scenario["termination"].name
        appeal.appeal_reason = "Circumstances have changed"
        appeal.submitted_date = getdate()
        appeal.insert()
        self.created_docs.append(appeal)
        
        scenario["appeal"] = appeal
        return scenario
        
    def _create_bulk_termination(self, count=5):
        """Create bulk termination scenario"""
        terminations = []
        
        for i in range(count):
            member = self.create_member(
                full_name=f"Bulk Termination Member {i+1}"
            )
            
            termination = frappe.new_doc("Membership Termination Request")
            termination.member = member.name
            termination.reason = "Non-payment"
            termination.termination_date = add_days(getdate(), 30)
            termination.is_bulk = 1
            termination.insert()
            self.created_docs.append(termination)
            
            terminations.append({
                "member": member,
                "termination": termination
            })
            
        return terminations
        
    def _create_financial_termination(self):
        """Create termination with outstanding finances"""
        member = self.create_member()
        
        # Create outstanding invoice
        invoice = self.create_sales_invoice(
            customer=member.name,
            amount=150,
            due_date=add_days(getdate(), -30)
        )
        
        termination = frappe.new_doc("Membership Termination Request")
        termination.member = member.name
        termination.reason = "Non-payment"
        termination.termination_date = add_days(getdate(), 30)
        termination.outstanding_amount = 150
        termination.insert()
        self.created_docs.append(termination)
        
        return {
            "member": member,
            "termination": termination,
            "outstanding_invoice": invoice
        }
        
    # Data Validation Utilities
    def create_edge_case_data(self):
        """Create data for edge case testing"""
        edge_cases = {}
        
        # Unicode and special characters
        edge_cases["unicode_member"] = self.create_member(
            full_name="Tëst Üñíçødé Member 测试",
            email="unicode_test@example.com"
        )
        
        # Very long names
        edge_cases["long_name_member"] = self.create_member(
            full_name="A" * 140,  # Near field limit
            email="longname@test.com"
        )
        
        # Minimal data
        edge_cases["minimal_member"] = frappe.new_doc("Member")
        edge_cases["minimal_member"].full_name = "Minimal"
        edge_cases["minimal_member"].email = f"minimal_{self.random_string(6)}@test.com"
        edge_cases["minimal_member"].insert()
        self.created_docs.append(edge_cases["minimal_member"])
        
        # Maximum relationships
        max_member = self.create_member()
        edge_cases["max_relationships"] = {
            "member": max_member,
            "teams": [self.create_volunteer_team(f"Team {i}", size=1)[0] 
                     for i in range(10)],
            "donations": [self.create_donation(donor=max_member.name) 
                         for _ in range(20)]
        }
        
        return edge_cases
        
    # Performance Test Data
    def create_performance_test_data(self, scale="small"):
        """Create data for performance testing"""
        scales = {
            "small": {"members": 100, "volunteers": 50, "transactions": 200},
            "medium": {"members": 1000, "volunteers": 500, "transactions": 2000},
            "large": {"members": 10000, "volunteers": 5000, "transactions": 20000}
        }
        
        config = scales.get(scale, scales["small"])
        
        print(f"Creating {scale} performance test dataset...")
        
        # Create members in batches
        members = []
        batch_size = 100
        
        for i in range(0, config["members"], batch_size):
            batch = []
            for j in range(min(batch_size, config["members"] - i)):
                member = self.create_member(
                    full_name=f"Perf Member {i+j}",
                    email=f"perf_{i+j}@test.com"
                )
                batch.append(member)
            members.extend(batch)
            frappe.db.commit()  # Commit each batch
            
        print(f"Created {len(members)} members")
        
        # Create volunteers
        volunteers = []
        for i in range(config["volunteers"]):
            if i < len(members):
                volunteer = self.create_volunteer(member=members[i].name)
                volunteers.append(volunteer)
                
        print(f"Created {len(volunteers)} volunteers")
        
        # Create transactions
        transactions = []
        for i in range(config["transactions"]):
            member_idx = i % len(members)
            transaction = self.create_sales_invoice(
                customer=members[member_idx].name,
                amount=random.uniform(10, 500)
            )
            transactions.append(transaction)
            
            if i % 100 == 0:
                frappe.db.commit()  # Periodic commits
                
        print(f"Created {len(transactions)} transactions")
        
        return {
            "members": members,
            "volunteers": volunteers,
            "transactions": transactions,
            "summary": {
                "total_members": len(members),
                "total_volunteers": len(volunteers),
                "total_transactions": len(transactions),
                "total_revenue": sum(t.grand_total for t in transactions)
            }
        }
        
    # Utility Methods
    def reset_test_environment(self):
        """Reset test environment to clean state"""
        print("Resetting test environment...")
        
        # Clean up in reverse dependency order
        cleanup_order = [
            "Volunteer Expense",
            "Volunteer Assignment",
            "Verenigingen Volunteer",
            "Membership Termination Request",
            "Sales Invoice",
            "Verenigingen Chapter Board Member",
            "Chapter Member",
            "Member",
            "Chapter",
            "Region"
        ]
        
        for doctype in cleanup_order:
            # Delete test records
            test_records = frappe.get_all(
                doctype,
                filters=[
                    ["name", "like", "TEST-%"],
                    ["name", "like", "Test %"]
                ],
                pluck="name"
            )
            
            for record in test_records:
                frappe.delete_doc(doctype, record, force=True, )
                
        frappe.db.commit()
        print("Test environment reset complete")
        
    def generate_test_report_data(self):
        """Generate comprehensive data for report testing"""
        print("Generating test report data...")
        
        # Create diverse member population
        members = self.create_member_lifecycle()
        
        # Create financial data
        campaign = self.create_donation_campaign()
        invoices = self.create_invoice_batch(count=20)
        
        # Create volunteer activities
        teams = []
        for i in range(3):
            team = self.create_volunteer_team(f"Report Test Team {i+1}")
            teams.append(team)
            
        # Create events
        events = self.create_event_series("Monthly Meeting", count=6)
        
        # Create terminations
        terminations = self.create_termination_scenarios()
        
        return {
            "members": members,
            "financial": {
                "campaign": campaign,
                "invoices": invoices
            },
            "volunteers": teams,
            "events": events,
            "terminations": terminations
        }

    
def create_test_factory():
    """Factory function to create extended test data factory"""
    return ExtendedTestDataFactory(cleanup_on_exit=True)


if __name__ == "__main__":
    # Example usage
    factory = create_test_factory()
    
    # Create comprehensive test data
    print("Creating comprehensive test data...")
    
    # Member lifecycle
    lifecycle = factory.create_member_lifecycle()
    print(f"Created lifecycle members: {list(lifecycle.keys())}")
    
    # Volunteer teams
    team_data = factory.create_volunteer_team("Demo Team", size=5)
    print(f"Created team with {len(team_data['volunteers'])} volunteers")
    
    # Financial data
    campaign = factory.create_donation_campaign(goal=5000)
    print(f"Created campaign with {len(campaign['donations'])} donations")
    
    # Performance data
    perf_data = factory.create_performance_test_data("small")
    print(f"Created performance test data: {perf_data['summary']}")
    
    # Clean up
    factory.cleanup()
    print("Test data cleaned up")