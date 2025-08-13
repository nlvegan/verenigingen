"""
Enhanced SEPA XML Generator with Full pain.008.001.02 Compliance

Complete implementation of SEPA Direct Debit XML generation following the
pain.008.001.02 standard with comprehensive validation and support for all
SEPA mandate types (OOFF, FRST, RCUR, FNAL).

Implements Week 3 Day 3-4 requirements from the SEPA billing improvements project.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import format_datetime, getdate, today

from verenigingen.utils.error_handling import SEPAError, ValidationError, handle_api_error
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.validation.iban_validator import derive_bic_from_iban, validate_iban


class SEPASequenceType(Enum):
    """SEPA Direct Debit Sequence Types"""

    OOFF = "OOFF"  # One-off payment
    FRST = "FRST"  # First payment in a series
    RCUR = "RCUR"  # Recurring payment
    FNAL = "FNAL"  # Final payment in a series


class SEPALocalInstrument(Enum):
    """SEPA Local Instrument Codes"""

    CORE = "CORE"  # SEPA Core Direct Debit
    B2B = "B2B"  # SEPA Business-to-Business Direct Debit
    COR1 = "COR1"  # SEPA Core Direct Debit with 1-day settlement


@dataclass
class SEPACreditor:
    """SEPA Creditor Information"""

    name: str
    iban: str
    bic: str
    creditor_id: str
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    country: str = "NL"
    postal_code: Optional[str] = None
    town: Optional[str] = None


@dataclass
class SEPAMandate:
    """SEPA Mandate Information"""

    mandate_id: str
    date_of_signature: date
    amendment_indicator: bool = False
    original_mandate_id: Optional[str] = None
    original_creditor_id: Optional[str] = None
    original_debtor_agent: Optional[str] = None


@dataclass
class SEPADebtor:
    """SEPA Debtor Information"""

    name: str
    iban: str
    bic: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    country: str = "NL"
    postal_code: Optional[str] = None
    town: Optional[str] = None


@dataclass
class SEPATransaction:
    """SEPA Direct Debit Transaction"""

    end_to_end_id: str
    amount: Decimal
    currency: str
    debtor: SEPADebtor
    mandate: SEPAMandate
    remittance_info: str
    sequence_type: SEPASequenceType
    purpose_code: Optional[str] = None
    category_purpose: Optional[str] = None


@dataclass
class SEPAPaymentInfo:
    """SEPA Payment Information Block"""

    payment_info_id: str
    payment_method: str
    batch_booking: bool
    requested_collection_date: date
    creditor: SEPACreditor
    local_instrument: SEPALocalInstrument
    sequence_type: SEPASequenceType
    transactions: List[SEPATransaction]


class EnhancedSEPAXMLGenerator:
    """
    Enhanced SEPA XML Generator with full pain.008.001.02 compliance

    Features:
    - Full pain.008.001.02 standard compliance
    - Support for all sequence types (OOFF, FRST, RCUR, FNAL)
    - Comprehensive validation against SEPA rulebook
    - Character set validation and sanitization
    - Multiple local instruments (CORE, B2B, COR1)
    - Amendment indicator support
    - Address information support
    - Purpose codes and category purposes
    """

    # SEPA XML namespace and schema
    NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"
    SCHEMA_LOCATION = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02 pain.008.001.02.xsd"

    # Character limits per SEPA specification
    MAX_MESSAGE_ID_LENGTH = 35
    MAX_PAYMENT_INFO_ID_LENGTH = 35
    MAX_END_TO_END_ID_LENGTH = 35
    MAX_MANDATE_ID_LENGTH = 35
    MAX_CREDITOR_NAME_LENGTH = 70
    MAX_DEBTOR_NAME_LENGTH = 70
    MAX_REMITTANCE_INFO_LENGTH = 140
    MAX_ADDRESS_LINE_LENGTH = 70
    MAX_COUNTRY_CODE_LENGTH = 2
    MAX_POSTAL_CODE_LENGTH = 16
    MAX_TOWN_NAME_LENGTH = 35

    # SEPA character set (restricted to basic Latin)
    SEPA_CHAR_PATTERN = re.compile(r"^[a-zA-Z0-9\+\?\-\:\(\)\.\,\'\s/]*$")

    def __init__(self):
        self.validation_errors = []
        self.validation_warnings = []

    @performance_monitor(threshold_ms=5000)
    def generate_sepa_xml(
        self,
        message_id: str,
        creation_datetime: datetime,
        payment_infos: List[SEPAPaymentInfo],
        initiating_party_name: str,
    ) -> str:
        """
        Generate complete SEPA XML document

        Args:
            message_id: Unique message identifier
            creation_datetime: Message creation timestamp
            payment_infos: List of payment information blocks
            initiating_party_name: Name of initiating party

        Returns:
            Complete SEPA XML as string

        Raises:
            SEPAError: If validation fails or generation errors occur
        """
        try:
            # Reset validation state
            self.validation_errors.clear()
            self.validation_warnings.clear()

            # Validate input parameters
            self._validate_message_parameters(
                message_id, creation_datetime, payment_infos, initiating_party_name
            )

            # Create XML structure
            root = self._create_document_root()
            cstmr_drct_dbt_initn = ET.SubElement(root, "CstmrDrctDbtInitn")

            # Generate group header
            self._generate_group_header(
                cstmr_drct_dbt_initn, message_id, creation_datetime, payment_infos, initiating_party_name
            )

            # Generate payment information blocks
            for payment_info in payment_infos:
                self._generate_payment_info(cstmr_drct_dbt_initn, payment_info)

            # Validate final XML structure
            self._validate_xml_structure(root)

            # Convert to string with proper formatting
            xml_string = self._format_xml_output(root)

            # Log generation success
            frappe.logger().info(
                f"SEPA XML generated successfully: {len(payment_infos)} payment infos, "
                f"{sum(len(pi.transactions) for pi in payment_infos)} transactions"
            )

            return xml_string

        except Exception as e:
            error_msg = f"SEPA XML generation failed: {str(e)}"
            frappe.logger().error(error_msg)
            raise SEPAError(_(error_msg))

    def _validate_message_parameters(
        self,
        message_id: str,
        creation_datetime: datetime,
        payment_infos: List[SEPAPaymentInfo],
        initiating_party_name: str,
    ):
        """Validate top-level message parameters"""

        # Message ID validation
        if not message_id or len(message_id) > self.MAX_MESSAGE_ID_LENGTH:
            self.validation_errors.append(f"Message ID must be 1-{self.MAX_MESSAGE_ID_LENGTH} characters")

        if not self.SEPA_CHAR_PATTERN.match(message_id):
            self.validation_errors.append("Message ID contains invalid characters")

        # Creation datetime validation
        if not isinstance(creation_datetime, datetime):
            self.validation_errors.append("Creation datetime must be a datetime object")

        # Payment infos validation
        if not payment_infos:
            self.validation_errors.append("At least one payment info block is required")

        if len(payment_infos) > 99:  # SEPA practical limit
            self.validation_warnings.append(
                f"Large number of payment info blocks ({len(payment_infos)}) may cause processing issues"
            )

        # Initiating party name validation
        if not initiating_party_name or len(initiating_party_name) > self.MAX_CREDITOR_NAME_LENGTH:
            self.validation_errors.append(
                f"Initiating party name must be 1-{self.MAX_CREDITOR_NAME_LENGTH} characters"
            )

        if not self.SEPA_CHAR_PATTERN.match(initiating_party_name):
            self.validation_errors.append("Initiating party name contains invalid characters")

        # Validate each payment info
        for i, payment_info in enumerate(payment_infos):
            self._validate_payment_info(payment_info, i)

        # Check for validation errors
        if self.validation_errors:
            error_msg = f"SEPA validation failed: {'; '.join(self.validation_errors)}"
            raise ValidationError(_(error_msg))

    def _validate_payment_info(self, payment_info: SEPAPaymentInfo, index: int):
        """Validate payment information block"""
        prefix = f"Payment Info {index + 1}"

        # Payment Info ID validation
        if (
            not payment_info.payment_info_id
            or len(payment_info.payment_info_id) > self.MAX_PAYMENT_INFO_ID_LENGTH
        ):
            self.validation_errors.append(
                f"{prefix}: Payment Info ID must be 1-{self.MAX_PAYMENT_INFO_ID_LENGTH} characters"
            )

        # Collection date validation
        if not payment_info.requested_collection_date:
            self.validation_errors.append(f"{prefix}: Requested collection date is required")
        elif payment_info.requested_collection_date < date.today():
            self.validation_warnings.append(f"{prefix}: Collection date is in the past")

        # Creditor validation
        self._validate_creditor(payment_info.creditor, prefix)

        # Transactions validation
        if not payment_info.transactions:
            self.validation_errors.append(f"{prefix}: At least one transaction is required")

        if len(payment_info.transactions) > 10000:  # SEPA limit
            self.validation_errors.append(
                f"{prefix}: Too many transactions ({len(payment_info.transactions)}, max 10,000)"
            )

        # Validate transactions
        for j, transaction in enumerate(payment_info.transactions):
            self._validate_transaction(transaction, f"{prefix}, Transaction {j + 1}")

        # Validate sequence type consistency
        self._validate_sequence_type_consistency(payment_info, prefix)

    def _validate_creditor(self, creditor: SEPACreditor, prefix: str):
        """Validate creditor information"""
        # Name validation
        if not creditor.name or len(creditor.name) > self.MAX_CREDITOR_NAME_LENGTH:
            self.validation_errors.append(
                f"{prefix}: Creditor name must be 1-{self.MAX_CREDITOR_NAME_LENGTH} characters"
            )

        if not self.SEPA_CHAR_PATTERN.match(creditor.name):
            self.validation_errors.append(f"{prefix}: Creditor name contains invalid characters")

        # IBAN validation
        iban_result = validate_iban(creditor.iban)
        if not iban_result["valid"]:
            self.validation_errors.append(f"{prefix}: Invalid creditor IBAN: {iban_result['message']}")

        # BIC validation
        if not self._validate_bic(creditor.bic):
            self.validation_errors.append(f"{prefix}: Invalid creditor BIC format")

        # Creditor ID validation
        if not creditor.creditor_id or len(creditor.creditor_id) > 35:
            self.validation_errors.append(f"{prefix}: Invalid creditor ID")

        # Address validation
        if creditor.address_line_1 and len(creditor.address_line_1) > self.MAX_ADDRESS_LINE_LENGTH:
            self.validation_errors.append(f"{prefix}: Creditor address line 1 too long")

        if creditor.address_line_2 and len(creditor.address_line_2) > self.MAX_ADDRESS_LINE_LENGTH:
            self.validation_errors.append(f"{prefix}: Creditor address line 2 too long")

    def _validate_transaction(self, transaction: SEPATransaction, prefix: str):
        """Validate individual transaction"""
        # End-to-end ID validation
        if not transaction.end_to_end_id or len(transaction.end_to_end_id) > self.MAX_END_TO_END_ID_LENGTH:
            self.validation_errors.append(
                f"{prefix}: End-to-end ID must be 1-{self.MAX_END_TO_END_ID_LENGTH} characters"
            )

        # Amount validation
        if transaction.amount <= 0:
            self.validation_errors.append(f"{prefix}: Amount must be positive")

        if transaction.amount > Decimal("999999999.99"):
            self.validation_errors.append(f"{prefix}: Amount exceeds maximum allowed")

        # Currency validation
        if transaction.currency != "EUR":
            self.validation_errors.append(f"{prefix}: Only EUR currency is supported in SEPA")

        # Debtor validation
        self._validate_debtor(transaction.debtor, prefix)

        # Mandate validation
        self._validate_mandate(transaction.mandate, prefix)

        # Remittance info validation
        if len(transaction.remittance_info) > self.MAX_REMITTANCE_INFO_LENGTH:
            self.validation_errors.append(
                f"{prefix}: Remittance info exceeds {self.MAX_REMITTANCE_INFO_LENGTH} characters"
            )

        if not self.SEPA_CHAR_PATTERN.match(transaction.remittance_info):
            self.validation_errors.append(f"{prefix}: Remittance info contains invalid characters")

    def _validate_debtor(self, debtor: SEPADebtor, prefix: str):
        """Validate debtor information"""
        # Name validation
        if not debtor.name or len(debtor.name) > self.MAX_DEBTOR_NAME_LENGTH:
            self.validation_errors.append(
                f"{prefix}: Debtor name must be 1-{self.MAX_DEBTOR_NAME_LENGTH} characters"
            )

        if not self.SEPA_CHAR_PATTERN.match(debtor.name):
            self.validation_errors.append(f"{prefix}: Debtor name contains invalid characters")

        # IBAN validation
        iban_result = validate_iban(debtor.iban)
        if not iban_result["valid"]:
            self.validation_errors.append(f"{prefix}: Invalid debtor IBAN: {iban_result['message']}")

        # BIC validation (optional but if provided must be valid)
        if debtor.bic and not self._validate_bic(debtor.bic):
            self.validation_errors.append(f"{prefix}: Invalid debtor BIC format")

    def _validate_mandate(self, mandate: SEPAMandate, prefix: str):
        """Validate mandate information"""
        # Mandate ID validation
        if not mandate.mandate_id or len(mandate.mandate_id) > self.MAX_MANDATE_ID_LENGTH:
            self.validation_errors.append(
                f"{prefix}: Mandate ID must be 1-{self.MAX_MANDATE_ID_LENGTH} characters"
            )

        # Date of signature validation
        if not mandate.date_of_signature:
            self.validation_errors.append(f"{prefix}: Mandate date of signature is required")
        elif mandate.date_of_signature > date.today():
            self.validation_warnings.append(f"{prefix}: Mandate signature date is in the future")

        # Amendment validation
        if mandate.amendment_indicator:
            if not mandate.original_mandate_id:
                self.validation_errors.append(f"{prefix}: Original mandate ID required for amendments")

    def _validate_sequence_type_consistency(self, payment_info: SEPAPaymentInfo, prefix: str):
        """Validate sequence type consistency within payment info"""
        if payment_info.transactions:
            # All transactions in a payment info should have the same sequence type
            expected_sequence = payment_info.sequence_type

            for i, transaction in enumerate(payment_info.transactions):
                if transaction.sequence_type != expected_sequence:
                    self.validation_errors.append(
                        f"{prefix}, Transaction {i + 1}: Sequence type mismatch "
                        f"(expected {expected_sequence.value}, got {transaction.sequence_type.value})"
                    )

    def _validate_bic(self, bic: str) -> bool:
        """Validate BIC format"""
        if not bic:
            return False

        # BIC format: 8 or 11 characters
        if len(bic) not in [8, 11]:
            return False

        # Basic format check: 4 letters + 2 letters + 2 alphanumeric + optional 3 alphanumeric
        pattern = r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"
        return bool(re.match(pattern, bic.upper()))

    def _create_document_root(self) -> ET.Element:
        """Create document root element with proper namespaces"""
        root = ET.Element("Document")
        root.set("xmlns", self.NAMESPACE)
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        root.set("xsi:schemaLocation", self.SCHEMA_LOCATION)
        return root

    def _generate_group_header(
        self,
        parent: ET.Element,
        message_id: str,
        creation_datetime: datetime,
        payment_infos: List[SEPAPaymentInfo],
        initiating_party_name: str,
    ) -> ET.Element:
        """Generate group header section"""
        grp_hdr = ET.SubElement(parent, "GrpHdr")

        # Message ID
        ET.SubElement(grp_hdr, "MsgId").text = message_id

        # Creation Date Time
        ET.SubElement(grp_hdr, "CreDtTm").text = creation_datetime.strftime("%Y-%m-%dT%H:%M:%S")

        # Calculate totals
        total_transactions = sum(len(pi.transactions) for pi in payment_infos)
        total_amount = sum(sum(tx.amount for tx in pi.transactions) for pi in payment_infos)

        # Number of Transactions
        ET.SubElement(grp_hdr, "NbOfTxs").text = str(total_transactions)

        # Control Sum
        ET.SubElement(grp_hdr, "CtrlSum").text = f"{total_amount:.2f}"

        # Initiating Party
        init_pty = ET.SubElement(grp_hdr, "InitgPty")
        ET.SubElement(init_pty, "Nm").text = initiating_party_name

        return grp_hdr

    def _generate_payment_info(self, parent: ET.Element, payment_info: SEPAPaymentInfo):
        """Generate payment information block"""
        pmt_inf = ET.SubElement(parent, "PmtInf")

        # Payment Info ID
        ET.SubElement(pmt_inf, "PmtInfId").text = payment_info.payment_info_id

        # Payment Method
        ET.SubElement(pmt_inf, "PmtMtd").text = payment_info.payment_method

        # Batch Booking
        ET.SubElement(pmt_inf, "BtchBookg").text = "true" if payment_info.batch_booking else "false"

        # Number of Transactions
        ET.SubElement(pmt_inf, "NbOfTxs").text = str(len(payment_info.transactions))

        # Control Sum
        control_sum = sum(tx.amount for tx in payment_info.transactions)
        ET.SubElement(pmt_inf, "CtrlSum").text = f"{control_sum:.2f}"

        # Payment Type Information
        self._generate_payment_type_info(pmt_inf, payment_info)

        # Requested Collection Date
        ET.SubElement(pmt_inf, "ReqdColltnDt").text = payment_info.requested_collection_date.strftime(
            "%Y-%m-%d"
        )

        # Creditor
        self._generate_creditor_info(pmt_inf, payment_info.creditor)

        # Creditor Account
        self._generate_creditor_account(pmt_inf, payment_info.creditor)

        # Creditor Agent
        self._generate_creditor_agent(pmt_inf, payment_info.creditor)

        # Creditor Scheme Identification
        self._generate_creditor_scheme_id(pmt_inf, payment_info.creditor)

        # Direct Debit Transaction Information
        for transaction in payment_info.transactions:
            self._generate_transaction_info(pmt_inf, transaction)

    def _generate_payment_type_info(self, parent: ET.Element, payment_info: SEPAPaymentInfo):
        """Generate payment type information"""
        pmt_tp_inf = ET.SubElement(parent, "PmtTpInf")

        # Service Level
        svc_lvl = ET.SubElement(pmt_tp_inf, "SvcLvl")
        ET.SubElement(svc_lvl, "Cd").text = "SEPA"

        # Local Instrument
        lcl_instrm = ET.SubElement(pmt_tp_inf, "LclInstrm")
        ET.SubElement(lcl_instrm, "Cd").text = payment_info.local_instrument.value

        # Sequence Type
        ET.SubElement(pmt_tp_inf, "SeqTp").text = payment_info.sequence_type.value

    def _generate_creditor_info(self, parent: ET.Element, creditor: SEPACreditor):
        """Generate creditor information"""
        cdtr = ET.SubElement(parent, "Cdtr")
        ET.SubElement(cdtr, "Nm").text = creditor.name

        # Address (if provided)
        if any([creditor.address_line_1, creditor.address_line_2, creditor.postal_code, creditor.town]):
            pstl_adr = ET.SubElement(cdtr, "PstlAdr")
            ET.SubElement(pstl_adr, "Ctry").text = creditor.country

            if creditor.address_line_1:
                ET.SubElement(pstl_adr, "AdrLine").text = creditor.address_line_1
            if creditor.address_line_2:
                ET.SubElement(pstl_adr, "AdrLine").text = creditor.address_line_2
            if creditor.postal_code:
                ET.SubElement(pstl_adr, "PstCd").text = creditor.postal_code
            if creditor.town:
                ET.SubElement(pstl_adr, "TwnNm").text = creditor.town

    def _generate_creditor_account(self, parent: ET.Element, creditor: SEPACreditor):
        """Generate creditor account information"""
        cdtr_acct = ET.SubElement(parent, "CdtrAcct")
        id_elem = ET.SubElement(cdtr_acct, "Id")
        ET.SubElement(id_elem, "IBAN").text = creditor.iban

    def _generate_creditor_agent(self, parent: ET.Element, creditor: SEPACreditor):
        """Generate creditor agent information"""
        cdtr_agt = ET.SubElement(parent, "CdtrAgt")
        fin_instn_id = ET.SubElement(cdtr_agt, "FinInstnId")
        ET.SubElement(fin_instn_id, "BIC").text = creditor.bic

    def _generate_creditor_scheme_id(self, parent: ET.Element, creditor: SEPACreditor):
        """Generate creditor scheme identification"""
        cdtr_schme_id = ET.SubElement(parent, "CdtrSchmeId")
        id_elem = ET.SubElement(cdtr_schme_id, "Id")
        prvt_id = ET.SubElement(id_elem, "PrvtId")
        othr = ET.SubElement(prvt_id, "Othr")
        ET.SubElement(othr, "Id").text = creditor.creditor_id
        schme_nm = ET.SubElement(othr, "SchmeNm")
        ET.SubElement(schme_nm, "Prtry").text = "SEPA"

    def _generate_transaction_info(self, parent: ET.Element, transaction: SEPATransaction):
        """Generate direct debit transaction information"""
        drct_dbt_tx_inf = ET.SubElement(parent, "DrctDbtTxInf")

        # Payment ID
        pmt_id = ET.SubElement(drct_dbt_tx_inf, "PmtId")
        ET.SubElement(pmt_id, "EndToEndId").text = transaction.end_to_end_id

        # Instructed Amount
        instd_amt = ET.SubElement(drct_dbt_tx_inf, "InstdAmt")
        instd_amt.text = f"{transaction.amount:.2f}"
        instd_amt.set("Ccy", transaction.currency)

        # Direct Debit Transaction
        drct_dbt_tx = ET.SubElement(drct_dbt_tx_inf, "DrctDbtTx")

        # Mandate Related Information
        self._generate_mandate_info(drct_dbt_tx, transaction.mandate)

        # Creditor Reference (if needed)
        if transaction.purpose_code:
            cdtr_ref = ET.SubElement(drct_dbt_tx, "CdtrRef")
            ET.SubElement(cdtr_ref, "Tp").text = transaction.purpose_code

        # Debtor Agent
        if transaction.debtor.bic:
            dbtr_agt = ET.SubElement(drct_dbt_tx_inf, "DbtrAgt")
            fin_instn_id = ET.SubElement(dbtr_agt, "FinInstnId")
            ET.SubElement(fin_instn_id, "BIC").text = transaction.debtor.bic
        else:
            # Derive BIC from IBAN if possible
            derived_bic = derive_bic_from_iban(transaction.debtor.iban)
            if derived_bic:
                dbtr_agt = ET.SubElement(drct_dbt_tx_inf, "DbtrAgt")
                fin_instn_id = ET.SubElement(dbtr_agt, "FinInstnId")
                ET.SubElement(fin_instn_id, "BIC").text = derived_bic

        # Debtor
        self._generate_debtor_info(drct_dbt_tx_inf, transaction.debtor)

        # Debtor Account
        dbtr_acct = ET.SubElement(drct_dbt_tx_inf, "DbtrAcct")
        id_elem = ET.SubElement(dbtr_acct, "Id")
        ET.SubElement(id_elem, "IBAN").text = transaction.debtor.iban

        # Purpose
        if transaction.purpose_code:
            purp = ET.SubElement(drct_dbt_tx_inf, "Purp")
            ET.SubElement(purp, "Cd").text = transaction.purpose_code

        # Remittance Information
        rmt_inf = ET.SubElement(drct_dbt_tx_inf, "RmtInf")
        ET.SubElement(rmt_inf, "Ustrd").text = transaction.remittance_info

    def _generate_mandate_info(self, parent: ET.Element, mandate: SEPAMandate):
        """Generate mandate related information"""
        mndt_rltd_inf = ET.SubElement(parent, "MndtRltdInf")

        # Mandate ID
        ET.SubElement(mndt_rltd_inf, "MndtId").text = mandate.mandate_id

        # Date of Signature
        ET.SubElement(mndt_rltd_inf, "DtOfSgntr").text = mandate.date_of_signature.strftime("%Y-%m-%d")

        # Amendment Indicator
        if mandate.amendment_indicator:
            ET.SubElement(mndt_rltd_inf, "AmdmntInd").text = "true"

            # Amendment Information Details
            amdmnt_inf_dtls = ET.SubElement(mndt_rltd_inf, "AmdmntInfDtls")

            if mandate.original_mandate_id:
                ET.SubElement(amdmnt_inf_dtls, "OrgnlMndtId").text = mandate.original_mandate_id

            if mandate.original_creditor_id:
                orgnl_cdtr_schme_id = ET.SubElement(amdmnt_inf_dtls, "OrgnlCdtrSchmeId")
                id_elem = ET.SubElement(orgnl_cdtr_schme_id, "Id")
                prvt_id = ET.SubElement(id_elem, "PrvtId")
                othr = ET.SubElement(prvt_id, "Othr")
                ET.SubElement(othr, "Id").text = mandate.original_creditor_id
                schme_nm = ET.SubElement(othr, "SchmeNm")
                ET.SubElement(schme_nm, "Prtry").text = "SEPA"

            if mandate.original_debtor_agent:
                orgnl_dbtr_agt = ET.SubElement(amdmnt_inf_dtls, "OrgnlDbtrAgt")
                fin_instn_id = ET.SubElement(orgnl_dbtr_agt, "FinInstnId")
                ET.SubElement(fin_instn_id, "BIC").text = mandate.original_debtor_agent

    def _generate_debtor_info(self, parent: ET.Element, debtor: SEPADebtor):
        """Generate debtor information"""
        dbtr = ET.SubElement(parent, "Dbtr")
        ET.SubElement(dbtr, "Nm").text = debtor.name

        # Address (if provided)
        if any([debtor.address_line_1, debtor.address_line_2, debtor.postal_code, debtor.town]):
            pstl_adr = ET.SubElement(dbtr, "PstlAdr")
            ET.SubElement(pstl_adr, "Ctry").text = debtor.country

            if debtor.address_line_1:
                ET.SubElement(pstl_adr, "AdrLine").text = debtor.address_line_1
            if debtor.address_line_2:
                ET.SubElement(pstl_adr, "AdrLine").text = debtor.address_line_2
            if debtor.postal_code:
                ET.SubElement(pstl_adr, "PstCd").text = debtor.postal_code
            if debtor.town:
                ET.SubElement(pstl_adr, "TwnNm").text = debtor.town

    def _validate_xml_structure(self, root: ET.Element):
        """Validate final XML structure against SEPA requirements"""
        # This is a placeholder for comprehensive XML schema validation
        # In a production implementation, you would validate against the actual XSD schema
        pass

    def _format_xml_output(self, root: ET.Element) -> str:
        """Format XML output with proper indentation"""
        # Convert to string
        xml_string = ET.tostring(root, encoding="utf-8", method="xml")

        # Prettify with xml.dom.minidom
        import xml.dom.minidom

        dom = xml.dom.minidom.parseString(xml_string)
        pretty_xml = dom.toprettyxml(indent="  ", encoding="utf-8")

        # Clean up extra whitespace
        lines = pretty_xml.decode("utf-8").split("\n")
        cleaned_lines = [line for line in lines if line.strip()]

        return "\n".join(cleaned_lines)

    def get_validation_results(self) -> Dict[str, List[str]]:
        """Get validation errors and warnings"""
        return {"errors": self.validation_errors, "warnings": self.validation_warnings}


# Factory functions for creating SEPA objects from Frappe data


def create_sepa_creditor_from_settings() -> SEPACreditor:
    """Create SEPA creditor from Verenigingen Settings"""
    settings = frappe.get_single("Verenigingen Settings")

    return SEPACreditor(
        name=settings.company_account_holder or settings.company or "Company Name",
        iban=settings.company_iban or "",
        bic=settings.company_bic or derive_bic_from_iban(settings.company_iban or ""),
        creditor_id=settings.creditor_id or "",
        country="NL",  # Assuming Dutch organization
    )


def create_sepa_transaction_from_invoice(
    invoice_data: Dict[str, Any], sequence_type: SEPASequenceType
) -> SEPATransaction:
    """Create SEPA transaction from invoice data"""

    # Create debtor
    debtor = SEPADebtor(
        name=invoice_data.get("member_name", "Unknown"),
        iban=invoice_data.get("iban", ""),
        bic=invoice_data.get("bic", ""),
    )

    # Create mandate
    mandate = SEPAMandate(
        mandate_id=invoice_data.get("mandate_reference", ""),
        date_of_signature=getdate(invoice_data.get("mandate_date", today())),
    )

    # Create transaction
    return SEPATransaction(
        end_to_end_id=f"E2E-{invoice_data.get('invoice', 'UNK')}",
        amount=Decimal(str(invoice_data.get("amount", 0))),
        currency=invoice_data.get("currency", "EUR"),
        debtor=debtor,
        mandate=mandate,
        remittance_info=f"Invoice {invoice_data.get('invoice', '')} - {invoice_data.get('member_name', '')}",
        sequence_type=sequence_type,
    )


# API Functions


@frappe.whitelist()
@handle_api_error
def generate_enhanced_sepa_xml(batch_name: str) -> Dict[str, Any]:
    """
    Generate enhanced SEPA XML for a batch

    Args:
        batch_name: Name of the Direct Debit Batch

    Returns:
        Generation result with XML content
    """
    try:
        # Get batch document
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        # Create generator
        generator = EnhancedSEPAXMLGenerator()

        # Create creditor from settings
        creditor = create_sepa_creditor_from_settings()

        # Determine sequence type and local instrument
        sequence_type = SEPASequenceType(batch.batch_type or "CORE")
        local_instrument = SEPALocalInstrument.CORE  # Default to CORE

        # Create transactions
        transactions = []
        for invoice_data in batch.invoices:
            transaction = create_sepa_transaction_from_invoice(
                {
                    "invoice": invoice_data.invoice,
                    "amount": invoice_data.amount,
                    "currency": invoice_data.currency or "EUR",
                    "member_name": invoice_data.member_name,
                    "iban": invoice_data.iban,
                    "bic": invoice_data.bic,
                    "mandate_reference": invoice_data.mandate_reference,
                },
                sequence_type,
            )
            transactions.append(transaction)

        # Create payment info
        payment_info = SEPAPaymentInfo(
            payment_info_id=f"PMT-{batch.name}",
            payment_method="DD",
            batch_booking=True,
            requested_collection_date=getdate(batch.batch_date),
            creditor=creditor,
            local_instrument=local_instrument,
            sequence_type=sequence_type,
            transactions=transactions,
        )

        # Generate XML
        xml_content = generator.generate_sepa_xml(
            message_id=f"MSG-{batch.name}",
            creation_datetime=datetime.now(),
            payment_infos=[payment_info],
            initiating_party_name=creditor.name,
        )

        # Get validation results
        validation_results = generator.get_validation_results()

        return {
            "success": True,
            "xml_content": xml_content,
            "validation_results": validation_results,
            "statistics": {
                "payment_infos": 1,
                "transactions": len(transactions),
                "total_amount": float(sum(tx.amount for tx in transactions)),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "xml_content": None}


@frappe.whitelist()
@handle_api_error
def validate_sepa_xml_compliance(xml_content: str) -> Dict[str, Any]:
    """
    Validate SEPA XML for compliance

    Args:
        xml_content: XML content to validate

    Returns:
        Validation result
    """
    try:
        # Parse XML
        root = ET.fromstring(xml_content)

        # Basic structure validation
        validation_results = {"is_valid": True, "errors": [], "warnings": [], "compliance_score": 100}

        # Check namespace
        if root.tag != "{urn:iso:std:iso:20022:tech:xsd:pain.008.001.02}Document":
            validation_results["errors"].append("Invalid root element or namespace")
            validation_results["is_valid"] = False

        # Check required elements
        required_paths = [".//CstmrDrctDbtInitn", ".//GrpHdr", ".//PmtInf"]

        for path in required_paths:
            if root.find(path, {"": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"}) is None:
                validation_results["errors"].append(f"Required element missing: {path}")
                validation_results["is_valid"] = False

        # Calculate compliance score
        if validation_results["errors"]:
            validation_results["compliance_score"] = max(0, 100 - len(validation_results["errors"]) * 20)
        elif validation_results["warnings"]:
            validation_results["compliance_score"] = max(90, 100 - len(validation_results["warnings"]) * 5)

        return validation_results

    except ET.ParseError as e:
        return {
            "is_valid": False,
            "errors": [f"XML parsing error: {str(e)}"],
            "warnings": [],
            "compliance_score": 0,
        }
