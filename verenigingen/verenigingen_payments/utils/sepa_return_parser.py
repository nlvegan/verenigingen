"""
SEPA Return File Parser (pain.002)

This module provides secure parsing for SEPA pain.002 return files,
which contain status information about direct debit transactions.

The pain.002.001.03 format includes:
- Group header with batch information
- Original message identification
- Transaction status information (accepted, rejected, pending)
- Reason codes for rejections

Security:
- Uses defusedxml for XXE protection
- Enforces file size limits
- Validates namespace and structure

References:
- ISO 20022 pain.002.001.03 specification
- SEPA Direct Debit Core Scheme Rulebook
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from xml.etree.ElementTree import Element

import frappe

from verenigingen.utils.secure_xml import (
    MAX_SEPA_RETURN_SIZE_BYTES,
    XMLSecurityError,
    parse_xml_safely,
)

# SEPA pain.002 namespaces (multiple versions supported)
PAIN002_NAMESPACES = {
    "pain002_03": "urn:iso:std:iso:20022:tech:xsd:pain.002.001.03",
    "pain002_10": "urn:iso:std:iso:20022:tech:xsd:pain.002.001.10",
}

# SEPA return reason codes and descriptions
SEPA_RETURN_REASON_CODES = {
    "AC01": "Incorrect Account Number",
    "AC04": "Closed Account Number",
    "AC06": "Blocked Account",
    "AC13": "Invalid Debtor Account Type",
    "AG01": "Transaction Forbidden",
    "AG02": "Invalid Bank Operation Code",
    "AM01": "Zero Amount",
    "AM02": "Not Allowed Amount",
    "AM04": "Insufficient Funds",
    "AM05": "Duplication",
    "AM09": "Wrong Amount",
    "BE01": "Inconsistent with End Customer",
    "BE04": "Missing Creditor Address",
    "BE05": "Unrecognised Initiating Party",
    "BE06": "Unknown End Customer",
    "BE07": "Missing Debtor Address",
    "CNOR": "Creditor Bank Not Registered",
    "DNOR": "Debtor Bank Not Registered",
    "FF01": "Invalid File Format",
    "MD01": "No Mandate",
    "MD02": "Missing Mandatory Mandate Information",
    "MD06": "Refund Request by End Customer",
    "MD07": "End Customer Deceased",
    "MS02": "Not Specified Reason Customer Generated",
    "MS03": "Not Specified Reason Agent Generated",
    "RC01": "Bank Identifier Incorrect",
    "RR01": "Missing Debtor Account or Identification",
    "RR02": "Missing Debtor Name or Address",
    "RR03": "Missing Creditor Name or Address",
    "RR04": "Regulatory Reason",
    "SL01": "Specific Service Offered by Debtor Agent",
    "TM01": "Cut Off Time",
    "FOCR": "Following Cancellation Request",
    "DUPL": "Duplicate Payment",
    "TECH": "Technical Problem",
}


@dataclass
class SEPAReturnItem:
    """Represents a single returned transaction from a pain.002 file."""

    original_message_id: str
    original_payment_id: str
    original_end_to_end_id: str
    original_instruction_id: Optional[str]
    status: str  # ACCP, ACSC, ACSP, ACTC, PDNG, RJCT
    reason_code: Optional[str]
    reason_description: Optional[str]
    additional_info: Optional[str]
    original_amount: Optional[float]
    original_currency: Optional[str]
    debtor_name: Optional[str]
    debtor_iban: Optional[str]
    mandate_id: Optional[str]

    def is_rejected(self) -> bool:
        """Check if this transaction was rejected."""
        return self.status == "RJCT"

    def is_pending(self) -> bool:
        """Check if this transaction is pending."""
        return self.status == "PDNG"

    def is_accepted(self) -> bool:
        """Check if this transaction was accepted."""
        return self.status in ("ACCP", "ACSC", "ACSP", "ACTC")

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses."""
        return {
            "original_message_id": self.original_message_id,
            "original_payment_id": self.original_payment_id,
            "end_to_end_id": self.original_end_to_end_id,
            "instruction_id": self.original_instruction_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason_description": self.reason_description,
            "additional_info": self.additional_info,
            "amount": self.original_amount,
            "currency": self.original_currency,
            "debtor_name": self.debtor_name,
            "debtor_iban": self.debtor_iban,
            "mandate_id": self.mandate_id,
            "is_rejected": self.is_rejected(),
        }


class SEPAReturnParser:
    """
    Secure parser for SEPA pain.002 return files.

    Supports both pain.002.001.03 and pain.002.001.10 formats.
    Uses defusedxml for XXE protection.
    """

    def __init__(self):
        self.namespace: Optional[str] = None
        self.ns_prefix: str = "pain"

    def parse(self, xml_content: str) -> List[SEPAReturnItem]:
        """
        Parse pain.002 return file securely.

        Args:
            xml_content: XML content as string

        Returns:
            List of SEPAReturnItem objects

        Raises:
            XMLSecurityError: If malicious XML detected
            ValueError: If XML is malformed or not a valid pain.002
        """
        try:
            root = parse_xml_safely(
                xml_content,
                max_size=MAX_SEPA_RETURN_SIZE_BYTES,
                source_description="pain.002 return file",
            )
        except Exception as e:
            frappe.log_error(f"Failed to parse pain.002 XML: {e}", "SEPA Return Parser")
            raise

        # Detect namespace from root element
        self._detect_namespace(root)

        if not self.namespace:
            raise ValueError(
                "Invalid pain.002 file: could not detect SEPA namespace. "
                f"Expected one of: {list(PAIN002_NAMESPACES.values())}"
            )

        # Parse the document
        returns = []

        # Find all transaction information elements
        # Path: Document > CstmrPmtStsRpt > OrgnlPmtInfAndSts > TxInfAndSts
        ns = {self.ns_prefix: self.namespace}

        # OrgnlMsgId lives once per document under
        # CstmrPmtStsRpt > OrgnlGrpInfAndSts > OrgnlMsgId; read it here and
        # propagate to every return item (ElementTree has no parent pointers).
        orig_msg_id = self._get_text(
            root,
            f".//{self.ns_prefix}:OrgnlGrpInfAndSts/{self.ns_prefix}:OrgnlMsgId",
            ns,
        )

        # OrgnlPmtInfId is a child of the OrgnlPmtInfAndSts container, NOT of the
        # individual TxInfAndSts elements it wraps. Iterate per payment-info group
        # so each transaction inherits the correct payment id.
        for pmt_info in root.findall(f".//{self.ns_prefix}:OrgnlPmtInfAndSts", ns):
            orig_payment_id = self._get_text(pmt_info, f"{self.ns_prefix}:OrgnlPmtInfId", ns)
            for tx_info in pmt_info.findall(f"{self.ns_prefix}:TxInfAndSts", ns):
                return_item = self._parse_transaction_status(
                    tx_info, ns, orig_payment_id=orig_payment_id, orig_msg_id=orig_msg_id
                )
                if return_item:
                    returns.append(return_item)

        return returns

    def _detect_namespace(self, root: Element) -> None:
        """Detect the pain.002 namespace from root element."""
        # Check root tag for namespace
        tag = root.tag

        # Tag format: {namespace}localname
        if tag.startswith("{"):
            ns_end = tag.find("}")
            if ns_end > 0:
                detected_ns = tag[1:ns_end]

                # Check if it's a known pain.002 namespace
                for key, known_ns in PAIN002_NAMESPACES.items():
                    if detected_ns == known_ns:
                        self.namespace = known_ns
                        return

                # Accept any pain.002 namespace pattern
                if "pain.002" in detected_ns:
                    self.namespace = detected_ns
                    return

    def _parse_transaction_status(
        self,
        tx_element: Element,
        ns: Dict[str, str],
        orig_payment_id: Optional[str] = None,
        orig_msg_id: Optional[str] = None,
    ) -> Optional[SEPAReturnItem]:
        """
        Extract return information from a TxInfAndSts element.

        Args:
            tx_element: TxInfAndSts XML element
            ns: Namespace dictionary
            orig_payment_id: OrgnlPmtInfId from the enclosing OrgnlPmtInfAndSts
                container (TxInfAndSts has no OrgnlPmtInfId of its own).
            orig_msg_id: OrgnlMsgId from the document-level OrgnlGrpInfAndSts.

        Returns:
            SEPAReturnItem or None if parsing fails
        """
        try:
            # Get status
            status_elem = tx_element.find(f"{self.ns_prefix}:TxSts", ns)
            status = status_elem.text if status_elem is not None else "UNKN"

            # Get original IDs (OrgnlPmtInfId / OrgnlMsgId are provided by the
            # caller from the parent containers; only the transaction-scoped ids
            # live inside TxInfAndSts).
            orig_end_to_end_id = self._get_text(tx_element, f"{self.ns_prefix}:OrgnlEndToEndId", ns)
            orig_instr_id = self._get_text(tx_element, f"{self.ns_prefix}:OrgnlInstrId", ns)

            # Get reason information
            reason_code = None
            reason_description = None
            additional_info = None

            sts_rsn_info = tx_element.find(f"{self.ns_prefix}:StsRsnInf", ns)
            if sts_rsn_info is not None:
                rsn = sts_rsn_info.find(f"{self.ns_prefix}:Rsn", ns)
                if rsn is not None:
                    code_elem = rsn.find(f"{self.ns_prefix}:Cd", ns)
                    if code_elem is not None:
                        reason_code = code_elem.text
                        reason_description = SEPA_RETURN_REASON_CODES.get(reason_code, "Unknown reason")

                addtl_info = sts_rsn_info.find(f"{self.ns_prefix}:AddtlInf", ns)
                if addtl_info is not None:
                    additional_info = addtl_info.text

            # Get original transaction details
            orig_tx_ref = tx_element.find(f"{self.ns_prefix}:OrgnlTxRef", ns)
            amount = None
            currency = None
            debtor_name = None
            debtor_iban = None
            mandate_id = None

            if orig_tx_ref is not None:
                # Amount
                amt_elem = orig_tx_ref.find(f".//{self.ns_prefix}:InstdAmt", ns)
                if amt_elem is not None:
                    try:
                        amount = float(amt_elem.text)
                        currency = amt_elem.get("Ccy", "EUR")
                    except (ValueError, TypeError):
                        pass

                # Debtor information
                dbtr = orig_tx_ref.find(f".//{self.ns_prefix}:Dbtr", ns)
                if dbtr is not None:
                    nm_elem = dbtr.find(f"{self.ns_prefix}:Nm", ns)
                    if nm_elem is not None:
                        debtor_name = nm_elem.text

                dbtr_acct = orig_tx_ref.find(f".//{self.ns_prefix}:DbtrAcct", ns)
                if dbtr_acct is not None:
                    iban_elem = dbtr_acct.find(f".//{self.ns_prefix}:IBAN", ns)
                    if iban_elem is not None:
                        debtor_iban = iban_elem.text

                # Mandate ID
                mndt_rltd_inf = orig_tx_ref.find(f".//{self.ns_prefix}:MndtRltdInf", ns)
                if mndt_rltd_inf is not None:
                    mndt_id_elem = mndt_rltd_inf.find(f"{self.ns_prefix}:MndtId", ns)
                    if mndt_id_elem is not None:
                        mandate_id = mndt_id_elem.text

            return SEPAReturnItem(
                original_message_id=orig_msg_id or "",
                original_payment_id=orig_payment_id or "",
                original_end_to_end_id=orig_end_to_end_id or "",
                original_instruction_id=orig_instr_id,
                status=status,
                reason_code=reason_code,
                reason_description=reason_description,
                additional_info=additional_info,
                original_amount=amount,
                original_currency=currency,
                debtor_name=debtor_name,
                debtor_iban=debtor_iban,
                mandate_id=mandate_id,
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to parse transaction status element: {e}",
                "SEPA Return Parser",
            )
            return None

    def _get_text(self, element: Element, path: str, ns: Dict[str, str]) -> Optional[str]:
        """Get text content of element at path."""
        child = element.find(path, ns)
        return child.text if child is not None else None


def parse_sepa_return_file(xml_content: str) -> List[Dict]:
    """
    Parse a SEPA pain.002 return file and return structured data.

    This is the main entry point for parsing return files.

    Args:
        xml_content: XML content as string

    Returns:
        List of dictionaries with return information

    Raises:
        XMLSecurityError: If malicious XML detected
        ValueError: If XML is malformed or not a valid pain.002
    """
    parser = SEPAReturnParser()
    return_items = parser.parse(xml_content)
    return [item.to_dict() for item in return_items]


def get_rejected_transactions(xml_content: str) -> List[Dict]:
    """
    Get only rejected transactions from a pain.002 file.

    Convenience function for processing return files where only
    rejections need to be handled.

    Args:
        xml_content: XML content as string

    Returns:
        List of rejected transaction dictionaries
    """
    parser = SEPAReturnParser()
    return_items = parser.parse(xml_content)
    return [item.to_dict() for item in return_items if item.is_rejected()]
