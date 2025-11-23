"""
Common type aliases and TypedDicts for Verenigingen.

This module provides type hints for common document types to improve IDE support,
enable static type checking, and serve as living documentation.

Usage:
    from verenigingen.types import MemberDict, VolunteerDict

    def process_member(member: MemberDict) -> bool:
        print(member["first_name"])
        return True
"""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

# Common field types
MemberStatus = Literal["Pending", "Active", "Inactive", "Suspended", "Terminated"]
PaymentMethod = Literal["SEPA Direct Debit", "Bank Transfer", "Credit Card", "Cash"]
MembershipType = Literal["Regular", "Student", "Senior", "Family", "Honorary"]
SubscriptionStatus = Literal["active", "canceled", "suspended", "pending", "past_due"]


class MemberDict(TypedDict, total=False):
    """
    Type definition for Member document.

    Attributes:
        name: Document name (auto-generated: Assoc-Member-YYYY-MM-####)
        first_name: Member's first name
        last_name: Member's last name
        tussenvoegsel: Dutch name particle (van, de, der, etc.)
        full_name: Computed full name with tussenvoegsel
        birth_date: Date of birth
        age: Computed age
        email: Primary email address
        contact_number: Phone number
        status: Member status
        member_id: Unique member identifier
        member_since: Date member joined
        member_end_date: Date membership ended (if terminated)

        # Address fields
        primary_address: Link to Address doctype
        address_display: HTML formatted address

        # Membership fields
        current_membership_type: Current membership type
        current_membership_plan: Link to Membership Plan
        current_dues_schedule: Link to current Membership Dues Schedule
        dues_rate: Current dues amount
        next_invoice_date: Next scheduled invoice date
        cumulative_membership_duration: Total membership duration

        # Payment fields
        payment_method: Preferred payment method
        iban: Bank account IBAN
        bank_account_name: Name on bank account
        bic: Bank Identifier Code
        payment_reference: Payment reference number

        # Mollie subscription fields
        mollie_customer_id: Mollie customer ID
        mollie_mandate_id: Mollie mandate ID
        mollie_subscription_id: Mollie subscription ID
        subscription_status: Subscription status
        next_payment_date: Next payment date

        # Integration fields
        customer: Link to ERPNext Customer
        contact: Link to ERPNext Contact
        user: Link to User account
        volunteer_record: Link to Volunteer record

        # Application fields
        application_id: Original application ID
        application_status: Application status
        application_date: Date of application
        reviewed_by: User who reviewed application
        review_date: Date application was reviewed

        # Chapter fields
        current_chapter_display: Current chapter (read-only display)
        chapter_assigned_by: Who assigned chapter
        previous_chapter: Previous chapter

        # Custom fields
        custom_field_1: Custom field 1
        custom_field_2: Custom field 2
        custom_field_3: Custom field 3
        custom_field_4: Custom field 4

        # Standard Frappe fields
        owner: Document creator
        creation: Creation timestamp
        modified: Last modified timestamp
        modified_by: Last modified by
        doctype: Always "Member"
    """

    # Required fields
    name: str
    doctype: str

    # Personal information
    first_name: str
    last_name: str
    tussenvoegsel: Optional[str]
    full_name: str
    middle_name: Optional[str]
    pronouns: Optional[str]
    aanhef: Optional[str]
    birth_date: date
    age: int
    image: Optional[str]

    # Contact information
    email: str
    contact_number: Optional[str]
    primary_address: Optional[str]
    address_display: Optional[str]
    accepts_optional_communications: bool

    # Membership information
    status: MemberStatus
    member_id: str
    member_since: date
    member_end_date: Optional[date]
    current_membership_type: Optional[MembershipType]
    current_membership_plan: Optional[str]
    current_dues_schedule: Optional[str]
    dues_rate: Optional[float]
    next_invoice_date: Optional[date]
    cumulative_membership_duration: Optional[int]

    # Payment information
    payment_method: Optional[PaymentMethod]
    iban: Optional[str]
    bank_account_name: Optional[str]
    bic: Optional[str]
    payment_reference: Optional[str]
    credit_card_number: Optional[str]

    # Mollie subscription
    mollie_customer_id: Optional[str]
    mollie_mandate_id: Optional[str]
    mollie_subscription_id: Optional[str]
    subscription_status: Optional[SubscriptionStatus]
    next_payment_date: Optional[date]
    mollie_subscription_next_invoice_date: Optional[date]
    subscription_cancelled_date: Optional[date]

    # Integration
    customer: Optional[str]
    contact: Optional[str]
    user: Optional[str]
    employee: Optional[str]
    volunteer_record: Optional[str]

    # Application
    application_id: Optional[str]
    application_status: Optional[str]
    application_date: Optional[date]
    selected_membership_type: Optional[str]
    is_aspirant: bool
    reviewed_by: Optional[str]
    review_date: Optional[date]
    review_notes: Optional[str]
    interested_in_volunteering: bool
    application_custom_fee: Optional[float]

    # Chapter
    current_chapter_display: Optional[str]
    chapter_assigned_by: Optional[str]
    previous_chapter: Optional[str]
    chapter_change_reason: Optional[str]

    # Custom fields
    custom_field_1: Optional[str]
    custom_field_2: Optional[str]
    custom_field_3: Optional[str]
    custom_field_4: Optional[str]

    # Address optimization
    address_fingerprint: Optional[str]
    normalized_address_line: Optional[str]
    normalized_city: Optional[str]
    address_last_updated: Optional[datetime]

    # CSV import
    csv_import_custom_fee: Optional[float]
    csv_import_custom_fee_reason: Optional[str]

    # Standard Frappe fields
    owner: str
    creation: datetime
    modified: datetime
    modified_by: str
    docstatus: int


class VolunteerDict(TypedDict, total=False):
    """
    Type definition for Volunteer document.

    Attributes:
        name: Document name
        member: Link to Member record
        volunteer_id: Unique volunteer identifier
        status: Volunteer status
        skills: List of skills
        availability: Availability description
    """

    name: str
    doctype: str
    member: str
    volunteer_id: str
    status: str
    skills: Optional[str]
    availability: Optional[str]
    creation: datetime
    modified: datetime
    owner: str
    modified_by: str
    docstatus: int


class ChapterDict(TypedDict, total=False):
    """
    Type definition for Chapter document.

    Attributes:
        name: Document name (chapter name)
        chapter_name: Full chapter name
        chapter_code: Unique chapter code
        region: Geographic region
        active: Whether chapter is active
        member_count: Number of members
    """

    name: str
    doctype: str
    chapter_name: str
    chapter_code: str
    region: Optional[str]
    active: bool
    member_count: int
    creation: datetime
    modified: datetime
    owner: str
    modified_by: str
    docstatus: int


class MembershipDict(TypedDict, total=False):
    """
    Type definition for Membership document.

    Attributes:
        name: Document name
        member: Link to Member
        membership_type: Type of membership
        from_date: Membership start date
        to_date: Membership end date
        status: Membership status
    """

    name: str
    doctype: str
    member: str
    membership_type: str
    from_date: date
    to_date: Optional[date]
    status: str
    creation: datetime
    modified: datetime
    owner: str
    modified_by: str
    docstatus: int


class DuesScheduleDict(TypedDict, total=False):
    """
    Type definition for Membership Dues Schedule document.

    Attributes:
        name: Document name
        member: Link to Member
        amount: Dues amount
        billing_frequency: Frequency (Monthly, Yearly, etc.)
        period_start: Coverage period start date
        period_end: Coverage period end date
        next_invoice_date: Next scheduled invoice date
        status: Schedule status
        auto_process: Whether to auto-process invoices
    """

    name: str
    doctype: str
    member: str
    amount: float
    billing_frequency: str
    period_start: date
    period_end: Optional[date]
    next_invoice_date: Optional[date]
    status: str
    auto_process: bool
    creation: datetime
    modified: datetime
    owner: str
    modified_by: str
    docstatus: int


class SalesInvoiceDict(TypedDict, total=False):
    """
    Type definition for Sales Invoice document.

    Attributes:
        name: Document name
        customer: Link to Customer
        posting_date: Invoice date
        due_date: Payment due date
        grand_total: Total amount
        outstanding_amount: Unpaid amount
        status: Invoice status
    """

    name: str
    doctype: str
    customer: str
    posting_date: date
    due_date: date
    grand_total: float
    outstanding_amount: float
    status: str
    creation: datetime
    modified: datetime
    owner: str
    modified_by: str
    docstatus: int


class PaymentEntryDict(TypedDict, total=False):
    """
    Type definition for Payment Entry document.

    Attributes:
        name: Document name
        payment_type: Type (Receive, Pay, etc.)
        party_type: Party type (Customer, Supplier, etc.)
        party: Party name
        paid_amount: Amount paid
        posting_date: Payment date
        reference_no: Payment reference
        status: Payment status
    """

    name: str
    doctype: str
    payment_type: str
    party_type: str
    party: str
    paid_amount: float
    posting_date: date
    reference_no: Optional[str]
    status: str
    creation: datetime
    modified: datetime
    owner: str
    modified_by: str
    docstatus: int


# Type aliases for common use cases
DocumentDict = Union[MemberDict, VolunteerDict, ChapterDict, MembershipDict, DuesScheduleDict]
FinancialDocumentDict = Union[SalesInvoiceDict, PaymentEntryDict]

# Function return types
ValidationResult = Dict[str, Any]
ServiceResult = Dict[str, Any]
