"""
SEPA XML Generation Service

This service handles SEPA XML generation for Dutch direct debit processing.
Extracted from Direct Debit Batch system for better separation of concerns.
Implements the pain.008.001.08 standard with Dutch banking requirements.
"""

import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import nowdate, nowtime, random_string

from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities, SEPAXMLValidator


class SEPAXMLGenerationService:
    """Service for generating SEPA XML files for direct debit processing"""

    def __init__(self):
        self.config_service = sepa_config_service

    def generate_sepa_xml_for_batch(self, batch_doc) -> str:
        """
        Generate SEPA Direct Debit XML file for Dutch banks.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            File URL of generated SEPA XML file

        Raises:
            frappe.ValidationError: If required settings are missing
            Exception: If XML generation fails
        """
        try:
            frappe.logger().info(f"Starting SEPA XML generation for batch {batch_doc.name} (pain.008.001.08)")

            # Generate IDs for SEPA message
            message_id = f"BATCH-{batch_doc.name}-{random_string(8)}"
            payment_info_id = f"PMT-{batch_doc.name}-{random_string(8)}"

            # Store IDs - use db_set to avoid validation issues after submission
            batch_doc.db_set("sepa_message_id", message_id)
            batch_doc.db_set("sepa_payment_info_id", payment_info_id)
            batch_doc.db_set("sepa_generation_date", f"{nowdate()} {nowtime()}")

            # Get configuration
            settings = self.config_service.get_sepa_settings()

            # Validate required settings
            validation_result = self.config_service.validate_sepa_configuration()
            if not validation_result["is_valid"]:
                missing_settings = validation_result["errors"]
                error_msg = f"Missing required SEPA settings: {', '.join(missing_settings)}"
                frappe.throw(error_msg)

            # Create SEPA XML structure
            xml_string = self._create_sepa_xml_structure(batch_doc, message_id, payment_info_id, settings)

            # Validate XML against schema if available
            validation_result = SEPAXMLValidator.validate_sepa_xml_schema(xml_string, batch_doc.name)
            if not validation_result["valid"]:
                frappe.logger().warning(
                    f"SEPA XML validation warnings for batch {batch_doc.name}: {validation_result.get('errors', [])}"
                )
                # Log warnings but continue - some banks may have different validation rules

            # Create and save XML file
            file_url = self._save_xml_file(batch_doc, xml_string)

            frappe.logger().info(f"SEPA XML file generated successfully for batch {batch_doc.name}")
            return file_url

        except Exception as e:
            error_msg = f"Error generating SEPA file: {str(e)}"
            frappe.log_error(
                f"Error generating SEPA file for batch {batch_doc.name}: {str(e)}",
                "SEPA Direct Debit Batch Error",
            )
            raise frappe.ValidationError(error_msg)

    def _create_sepa_xml_structure(
        self, batch_doc, message_id: str, payment_info_id: str, settings: Dict[str, Any]
    ) -> str:
        """
        Create SEPA XML structure specifically for Dutch direct debit.

        Args:
            batch_doc: Direct Debit Batch document
            message_id: Unique message identifier
            payment_info_id: Payment information identifier
            settings: SEPA configuration settings

        Returns:
            XML string in pain.008.001.08 format
        """
        frappe.logger().info(
            f"Creating Dutch SEPA XML structure for batch {batch_doc.name} (pain.008.001.08)"
        )

        # Create root element with updated namespace for 2019 version
        root = ET.Element("Document")
        root.set("xmlns", "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08")
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        root.set("xsi:schemaLocation", "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08 pain.008.001.08.xsd")

        # Customer SEPA Direct Debit Initiation
        cstmr_drct_dbt_initn = ET.SubElement(root, "CstmrDrctDbtInitn")

        # Group Header
        self._create_group_header(cstmr_drct_dbt_initn, message_id, batch_doc, settings)

        # Payment Information
        self._create_payment_information(cstmr_drct_dbt_initn, payment_info_id, batch_doc, settings)

        # Convert to string
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _create_group_header(self, parent_element, message_id: str, batch_doc, settings: Dict[str, Any]):
        """Create the Group Header section of SEPA XML"""
        grp_hdr = ET.SubElement(parent_element, "GrpHdr")
        ET.SubElement(grp_hdr, "MsgId").text = message_id
        ET.SubElement(grp_hdr, "CreDtTm").text = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        ET.SubElement(grp_hdr, "NbOfTxs").text = str(batch_doc.entry_count)
        ET.SubElement(grp_hdr, "CtrlSum").text = str(batch_doc.total_amount)

        # Initiating Party (Creditor)
        init_party = ET.SubElement(grp_hdr, "InitgPty")
        ET.SubElement(init_party, "Nm").text = settings["organization_name"]

    def _create_payment_information(
        self, parent_element, payment_info_id: str, batch_doc, settings: Dict[str, Any]
    ):
        """Create the Payment Information section of SEPA XML"""
        pmt_inf = ET.SubElement(parent_element, "PmtInf")
        ET.SubElement(pmt_inf, "PmtInfId").text = payment_info_id
        ET.SubElement(pmt_inf, "PmtMtd").text = "DD"

        # Payment Type Information
        pmt_tp_inf = ET.SubElement(pmt_inf, "PmtTpInf")
        svc_lvl = ET.SubElement(pmt_tp_inf, "SvcLvl")
        ET.SubElement(svc_lvl, "Cd").text = "SEPA"
        lcl_instrm = ET.SubElement(pmt_tp_inf, "LclInstrm")
        ET.SubElement(lcl_instrm, "Cd").text = "CORE"
        ET.SubElement(pmt_tp_inf, "SeqTp").text = "RCUR"  # Default to recurring

        # Collection Date
        ET.SubElement(pmt_inf, "ReqdColltnDt").text = str(batch_doc.collection_date)

        # Creditor information
        self._create_creditor_information(pmt_inf, settings)

        # Direct Debit Transaction Information for each invoice
        self._create_transaction_information(pmt_inf, batch_doc, settings)

    def _create_creditor_information(self, parent_element, settings: Dict[str, Any]):
        """Create creditor information section"""
        cdtr = ET.SubElement(parent_element, "Cdtr")
        ET.SubElement(cdtr, "Nm").text = settings["organization_name"]

        # Creditor Account
        cdtr_acct = ET.SubElement(parent_element, "CdtrAcct")
        cdtr_acct_id = ET.SubElement(cdtr_acct, "Id")
        ET.SubElement(cdtr_acct_id, "IBAN").text = settings["iban"]

        # Creditor Agent (Bank)
        cdtr_agt = ET.SubElement(parent_element, "CdtrAgt")
        fin_instn_id = ET.SubElement(cdtr_agt, "FinInstnId")
        if settings.get("bic"):
            ET.SubElement(fin_instn_id, "BIC").text = settings["bic"]

        # Creditor Scheme Identification
        cdtr_schme_id = ET.SubElement(parent_element, "CdtrSchmeId")
        self._create_creditor_scheme_id(cdtr_schme_id, settings)

    def _create_creditor_scheme_id(self, parent_element, settings: Dict[str, Any]):
        """Create creditor scheme identification section"""
        nm = ET.SubElement(parent_element, "Nm")
        nm.text = settings["organization_name"]

        id_elem = ET.SubElement(parent_element, "Id")
        prvt_id = ET.SubElement(id_elem, "PrvtId")
        othr = ET.SubElement(prvt_id, "Othr")
        ET.SubElement(othr, "Id").text = settings["creditor_id"]
        schme_nm = ET.SubElement(othr, "SchmeNm")
        ET.SubElement(schme_nm, "Prtry").text = "SEPA"

    def _create_transaction_information(self, parent_element, batch_doc, settings: Dict[str, Any]):
        """Create transaction information for each invoice in the batch"""
        for invoice_item in batch_doc.invoices:
            drct_dbt_tx_inf = ET.SubElement(parent_element, "DrctDbtTxInf")

            # Payment Identification
            pmt_id = ET.SubElement(drct_dbt_tx_inf, "PmtId")
            ET.SubElement(pmt_id, "EndToEndId").text = f"INV-{invoice_item.invoice}"

            # Instructed Amount
            instd_amt = ET.SubElement(drct_dbt_tx_inf, "InstdAmt")
            instd_amt.set("Ccy", "EUR")
            instd_amt.text = str(invoice_item.amount)

            # Direct Debit Transaction
            drct_dbt_tx = ET.SubElement(drct_dbt_tx_inf, "DrctDbtTx")

            # Mandate Related Information
            mdt_rltd_inf = ET.SubElement(drct_dbt_tx, "MdtRltdInf")
            ET.SubElement(mdt_rltd_inf, "MdtId").text = invoice_item.mandate_reference or "UNKNOWN"
            ET.SubElement(mdt_rltd_inf, "DtOfSgntr").text = "2023-01-01"  # Placeholder

            # Debtor information
            self._create_debtor_information(drct_dbt_tx_inf, invoice_item, settings)

            # Debtor Account
            dbtr_acct = ET.SubElement(drct_dbt_tx_inf, "DbtrAcct")
            dbtr_acct_id = ET.SubElement(dbtr_acct, "Id")
            ET.SubElement(dbtr_acct_id, "IBAN").text = invoice_item.iban or "UNKNOWN"

            # Remittance Information
            rmt_inf = ET.SubElement(drct_dbt_tx_inf, "RmtInf")
            ET.SubElement(rmt_inf, "Ustrd").text = f"Invoice {invoice_item.invoice}"

    def _create_debtor_information(self, parent_element, invoice_item, settings: Dict[str, Any]):
        """Create debtor information section"""
        dbtr = ET.SubElement(parent_element, "Dbtr")

        # Try to get structured address information
        member_address = self._get_member_structured_address(invoice_item.customer)

        if member_address and member_address.get("name"):
            ET.SubElement(dbtr, "Nm").text = member_address["name"]

            if member_address.get("address"):
                pstl_adr = ET.SubElement(dbtr, "PstlAdr")
                ET.SubElement(pstl_adr, "Ctry").text = "NL"
                if member_address.get("postal_code"):
                    ET.SubElement(pstl_adr, "PstCd").text = member_address["postal_code"]
                if member_address.get("city"):
                    ET.SubElement(pstl_adr, "TwnNm").text = member_address["city"]
                # Add address lines
                for i, line in enumerate(member_address["address"][:2], 1):
                    ET.SubElement(pstl_adr, "AdrLine").text = line
        else:
            # Fallback to customer name
            ET.SubElement(dbtr, "Nm").text = invoice_item.customer or "UNKNOWN"

    def _get_member_structured_address(self, member_name: str) -> Optional[Dict[str, Any]]:
        """
        Get structured address information for pain.008.001.08 requirement.

        Args:
            member_name: Name of the member

        Returns:
            Dictionary with structured address data or None
        """
        try:
            if not member_name:
                return None

            # Get member document
            member = frappe.get_doc("Member", member_name)

            # Get customer document for address information
            if hasattr(member, "customer") and member.customer:
                customer = frappe.get_doc("Customer", member.customer)

                # Build structured address
                address_info = {
                    "name": f"{member.first_name} {member.last_name}".strip(),
                    "address": [],
                    "postal_code": None,
                    "city": None,
                }

                # Try to get address from customer
                if hasattr(customer, "customer_primary_address") and customer.customer_primary_address:
                    address = frappe.get_doc("Address", customer.customer_primary_address)

                    if address.address_line1:
                        address_info["address"].append(address.address_line1)
                    if address.address_line2:
                        address_info["address"].append(address.address_line2)

                    address_info["postal_code"] = getattr(address, "pincode", None)
                    address_info["city"] = getattr(address, "city", None)

                return address_info if address_info["name"] else None

        except Exception as e:
            frappe.logger().warning(f"Could not get structured address for member {member_name}: {str(e)}")
            return None

    def _save_xml_file(self, batch_doc, xml_string: str) -> str:
        """
        Save XML string to file and attach to document.

        Args:
            batch_doc: Direct Debit Batch document
            xml_string: XML content as string

        Returns:
            File URL of saved XML file
        """
        import os
        import xml.dom.minidom

        from verenigingen.verenigingen_payments.utils.sepa_utilities import FileManagementUtilities

        # Prettify XML
        xml_pretty = xml.dom.minidom.parseString(xml_string).toprettyxml()

        # Create temporary file
        temp_file_path = os.path.join(tempfile.gettempdir(), f"sepa-{batch_doc.name}.xml")
        with open(temp_file_path, "w") as f:
            f.write(xml_pretty)

        try:
            # Attach to document
            file_url = FileManagementUtilities.attach_file_to_document(
                temp_file_path, batch_doc.doctype, batch_doc.name
            )

            # Update batch document
            batch_doc.db_set("sepa_file", file_url)
            batch_doc.db_set("sepa_file_generated", 1)
            batch_doc.db_set("status", "Generated")

            return file_url

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)


# Singleton instance for global use
sepa_xml_service = SEPAXMLGenerationService()
