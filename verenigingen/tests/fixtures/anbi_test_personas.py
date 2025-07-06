"""
ANBI Test Personas
Lifecycle test personas for comprehensive testing of ANBI functionality
"""

import frappe
from frappe.utils import add_years, add_months, today


class ANBITestPersonas:
    """Test personas for ANBI lifecycle testing"""
    
    @staticmethod
    def create_all_personas():
        """Create all test personas"""
        personas = []
        
        # Anna de Vries - Individual monthly donor
        personas.append(ANBITestPersonas.create_anna_de_vries())
        
        # Stichting Groen - Organization donor
        personas.append(ANBITestPersonas.create_stichting_groen())
        
        # Jan Bakker - Elderly donor
        personas.append(ANBITestPersonas.create_jan_bakker())
        
        # Tech Startup BV - Corporate donor
        personas.append(ANBITestPersonas.create_tech_startup())
        
        return personas
    
    @staticmethod
    def create_anna_de_vries():
        """
        Anna de Vries - Regular individual donor
        - Age: 45, Amsterdam
        - Makes monthly €100 donations
        - Has 5-year ANBI agreement
        - Prefers SEPA direct debit
        - Needs annual tax receipts
        """
        # Create donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Anna de Vries"
        donor.donor_email = "anna.devries@example.nl"
        donor.phone = "+31 20 123 4567"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.anbi_consent = 1
        donor.anbi_consent_date = frappe.utils.now()
        donor.identification_verified = 1
        donor.identification_verification_date = today()
        donor.identification_verification_method = "DigiD"
        donor.bsn_citizen_service_number = "123456789"  # Test BSN
        donor.insert()
        
        # Create SEPA mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.donor = donor.name
        mandate.mandate_id = f"ANNA-SEPA-{frappe.utils.now_datetime().strftime('%Y%m%d')}"
        mandate.iban = "NL91ABNA0417164300"
        mandate.bic = "ABNANL2A"
        mandate.account_holder_name = "Anna de Vries"
        mandate.mandate_type = "RCUR"
        mandate.status = "Active"
        mandate.valid_from = today()
        mandate.insert()
        
        # Create periodic agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.anbi_eligible = 1
        agreement.annual_amount = 1200  # €100/month
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "SEPA Direct Debit"
        agreement.sepa_mandate = mandate.name
        agreement.status = "Active"
        agreement.donor_signature_received = 1
        agreement.signed_date = today()
        agreement.insert()
        
        # Create some historical donations
        for i in range(6):  # 6 months of donations
            donation_date = add_months(today(), -i)
            donation = frappe.new_doc("Donation")
            donation.donor = donor.name
            donation.date = donation_date
            donation.amount = 100
            donation.payment_method = "SEPA Direct Debit"
            donation.sepa_mandate = mandate.name
            donation.donation_type = "General"
            donation.periodic_donation_agreement = agreement.name
            donation.donation_status = "Recurring"
            donation.paid = 1
            donation.payment_id = f"SEPA-ANNA-{donation_date.strftime('%Y%m')}"
            donation.belastingdienst_reportable = 1
            donation.insert()
            donation.submit()
            
            # Link to agreement
            agreement.link_donation(donation.name)
        
        return {
            "persona": "Anna de Vries",
            "donor": donor.name,
            "mandate": mandate.name,
            "agreement": agreement.name,
            "donation_count": 6
        }
    
    @staticmethod
    def create_stichting_groen():
        """
        Stichting Groen - Organization donor
        - Environmental foundation
        - Makes quarterly €5000 donations
        - Has RSIN, needs ANBI receipts
        - Multiple contact persons
        - Requires detailed reporting
        """
        # Create donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Stichting Groen"
        donor.donor_email = "info@stichtinggroen.nl"
        donor.phone = "+31 30 987 6543"
        donor.donor_type = "Organization"
        donor.preferred_communication_method = "Email"
        donor.anbi_consent = 1
        donor.anbi_consent_date = frappe.utils.now()
        donor.identification_verified = 1
        donor.identification_verification_date = today()
        donor.identification_verification_method = "Manual"
        donor.rsin_organization_tax_number = "850123456"  # Test RSIN
        donor.contact_person_address = "Groene Laan 123, 3500 AB Utrecht"
        donor.insert()
        
        # Create periodic agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.agreement_type = "Notarial"
        agreement.start_date = add_years(today(), -2)  # Started 2 years ago
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.anbi_eligible = 1
        agreement.annual_amount = 20000  # €5000/quarter
        agreement.payment_frequency = "Quarterly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.donor_signature_received = 1
        agreement.signed_date = add_years(today(), -2)
        agreement.insert()
        
        # Create quarterly donations for past 2 years
        for year in range(2):
            for quarter in range(4):
                months_ago = year * 12 + quarter * 3
                donation_date = add_months(today(), -months_ago)
                
                donation = frappe.new_doc("Donation")
                donation.donor = donor.name
                donation.date = donation_date
                donation.amount = 5000
                donation.payment_method = "Bank Transfer"
                donation.bank_reference = f"GROEN-{donation_date.strftime('%Y-Q%m')}"
                donation.donation_type = "Environmental Projects"
                donation.periodic_donation_agreement = agreement.name
                donation.donation_status = "Recurring"
                donation.donation_purpose_type = "Specific Goal"
                donation.specific_goal_description = "Reforestation projects in Netherlands"
                donation.paid = 1
                donation.belastingdienst_reportable = 1
                donation.insert()
                donation.submit()
                
                agreement.link_donation(donation.name)
        
        return {
            "persona": "Stichting Groen",
            "donor": donor.name,
            "agreement": agreement.name,
            "donation_count": 8
        }
    
    @staticmethod
    def create_jan_bakker():
        """
        Jan Bakker - Elderly donor
        - Age: 72, Rotterdam
        - Makes annual €1000 donations
        - No email, prefers postal mail
        - Notarial agreement type
        - Needs simplified processes
        """
        # Create donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Jan Bakker"
        donor.donor_email = ""  # No email
        donor.phone = "+31 10 456 7890"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Post"
        donor.contact_person_address = "Oude Haven 45, 3011 XH Rotterdam"
        donor.anbi_consent = 1
        donor.anbi_consent_date = frappe.utils.now()
        donor.identification_verified = 1
        donor.identification_verification_date = today()
        donor.identification_verification_method = "Manual"
        donor.bsn_citizen_service_number = "987654321"  # Test BSN
        donor.insert()
        
        # Create periodic agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.agreement_type = "Notarial"
        agreement.start_date = add_years(today(), -3)  # Started 3 years ago
        agreement.agreement_duration_years = "10 Years (ANBI)"  # Longer commitment
        agreement.anbi_eligible = 1
        agreement.annual_amount = 1000
        agreement.payment_frequency = "Annually"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.donor_signature_received = 1
        agreement.signed_date = add_years(today(), -3)
        agreement.insert()
        
        # Create annual donations
        for year in range(3):
            donation_date = add_years(today(), -year)
            
            donation = frappe.new_doc("Donation")
            donation.donor = donor.name
            donation.date = donation_date
            donation.amount = 1000
            donation.payment_method = "Bank Transfer"
            donation.bank_reference = f"JB-{donation_date.year}"
            donation.donation_type = "General"
            donation.periodic_donation_agreement = agreement.name
            donation.donation_status = "Recurring"
            donation.paid = 1
            donation.belastingdienst_reportable = 1
            donation.insert()
            donation.submit()
            
            agreement.link_donation(donation.name)
        
        return {
            "persona": "Jan Bakker",
            "donor": donor.name,
            "agreement": agreement.name,
            "donation_count": 3
        }
    
    @staticmethod
    def create_tech_startup():
        """
        Tech Startup BV - Corporate donor
        - Young company, irregular donations
        - Amounts vary €500-€10000
        - Wants online everything
        - API integration needs
        - Real-time receipts required
        """
        # Create donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = "InnovateTech BV"
        donor.donor_email = "finance@innovatetech.nl"
        donor.phone = "+31 20 555 9876"
        donor.donor_type = "Organization"
        donor.preferred_communication_method = "Email"
        donor.anbi_consent = 1
        donor.anbi_consent_date = frappe.utils.now()
        donor.identification_verified = 1
        donor.identification_verification_date = today()
        donor.identification_verification_method = "Bank Verification"
        donor.rsin_organization_tax_number = "861234567"  # Test RSIN
        donor.contact_person_address = "Tech Park 42, 1098 XG Amsterdam"
        donor.insert()
        
        # Create various one-time donations (no periodic agreement yet)
        amounts = [500, 2500, 1000, 10000, 750, 5000]
        
        for i, amount in enumerate(amounts):
            donation_date = add_months(today(), -i * 2)
            
            donation = frappe.new_doc("Donation")
            donation.donor = donor.name
            donation.date = donation_date
            donation.amount = amount
            donation.payment_method = "Mollie"
            donation.payment_id = f"mol_{frappe.utils.random_string(12)}"
            donation.donation_type = "Innovation Support"
            donation.donation_status = "One-time"
            donation.donation_purpose_type = "Campaign"
            donation.campaign_reference = "Tech4Good Campaign"
            donation.paid = 1
            donation.belastingdienst_reportable = 1 if amount >= 500 else 0
            donation.insert()
            donation.submit()
        
        # Create draft periodic agreement (not yet active)
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = add_months(today(), 1)  # Starting next month
        agreement.agreement_duration_years = "3 Years (Pledge - No ANBI benefits)"  # Shorter non-ANBI agreement
        agreement.anbi_eligible = 0  # Not ANBI eligible (< 5 years)
        agreement.annual_amount = 12000
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "SEPA Direct Debit"
        agreement.status = "Draft"  # Not yet active
        agreement.insert()
        
        return {
            "persona": "InnovateTech BV",
            "donor": donor.name,
            "agreement": agreement.name,
            "donation_count": len(amounts)
        }
    
    @staticmethod
    def cleanup_test_personas():
        """Clean up all test personas"""
        test_donors = [
            "Anna de Vries",
            "Stichting Groen", 
            "Jan Bakker",
            "InnovateTech BV"
        ]
        
        for donor_name in test_donors:
            # Delete donations
            donations = frappe.get_all("Donation", filters={"donor": ["like", f"%{donor_name}%"]})
            for donation in donations:
                doc = frappe.get_doc("Donation", donation.name)
                if doc.docstatus == 1:
                    doc.cancel()
                doc.delete()
            
            # Delete agreements
            agreements = frappe.get_all("Periodic Donation Agreement", 
                                      filters={"donor": ["like", f"%{donor_name}%"]})
            for agreement in agreements:
                frappe.delete_doc("Periodic Donation Agreement", agreement.name)
            
            # Delete SEPA mandates
            mandates = frappe.get_all("SEPA Mandate", 
                                    filters={"donor": ["like", f"%{donor_name}%"]})
            for mandate in mandates:
                frappe.delete_doc("SEPA Mandate", mandate.name)
            
            # Delete donors
            donors = frappe.get_all("Donor", filters={"donor_name": donor_name})
            for donor in donors:
                frappe.delete_doc("Donor", donor.name)
        
        frappe.db.commit()


def create_test_personas():
    """Create all test personas for testing"""
    return ANBITestPersonas.create_all_personas()


def cleanup_test_personas():
    """Clean up all test personas"""
    ANBITestPersonas.cleanup_test_personas()