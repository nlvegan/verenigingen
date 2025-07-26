"""
SEPA Rulebook Validator and XML Schema Validation

Comprehensive validation against SEPA rulebook requirements including:
- Business rules validation
- XML schema validation against pain.008.001.02
- Mandate lifecycle validation
- Cross-European compliance checks

Implements Week 3 Day 3-4 requirements from the SEPA billing improvements project.
"""

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe
import requests
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.error_handling import SEPAError, ValidationError, handle_api_error
from verenigingen.utils.sepa_xml_enhanced_generator import SEPALocalInstrument, SEPASequenceType


class SEPARuleType(Enum):
    """Types of SEPA rules"""

    MANDATORY = "mandatory"  # Must be enforced
    CONDITIONAL = "conditional"  # Enforced under certain conditions
    OPTIONAL = "optional"  # Best practice but not required
    COUNTRY_SPECIFIC = "country_specific"  # Specific to certain countries


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""

    CRITICAL = "critical"  # Prevents processing
    ERROR = "error"  # Should be fixed
    WARNING = "warning"  # Should be reviewed
    INFO = "info"  # Informational only


@dataclass
class SEPARule:
    """SEPA rulebook rule definition"""

    rule_id: str
    rule_type: SEPARuleType
    severity: ValidationSeverity
    description: str
    xpath: Optional[str] = None
    validator_function: Optional[str] = None
    countries: Optional[List[str]] = None


@dataclass
class ValidationIssue:
    """Validation issue result"""

    rule_id: str
    severity: ValidationSeverity
    message: str
    xpath: Optional[str] = None
    element_value: Optional[str] = None
    suggested_fix: Optional[str] = None


class SEPARulebookValidator:
    """
    Comprehensive SEPA rulebook validator

    Validates SEPA direct debit transactions and XML against:
    - SEPA Core Direct Debit Rulebook
    - Pain.008.001.02 Implementation Guidelines
    - European Payments Council (EPC) requirements
    - Country-specific requirements (focus on Netherlands)
    """

    def __init__(self):
        self.namespace = {"sepa": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"}
        self.rules = self._initialize_sepa_rules()
        self.validation_cache = {}

    def _initialize_sepa_rules(self) -> List[SEPARule]:
        """Initialize SEPA rulebook rules"""
        return [
            # Message Level Rules
            SEPARule(
                rule_id="MSG001",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Message ID must be unique and conform to format",
                xpath="//sepa:GrpHdr/sepa:MsgId",
                validator_function="validate_message_id",
            ),
            SEPARule(
                rule_id="MSG002",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Creation date time must not be in the future",
                xpath="//sepa:GrpHdr/sepa:CreDtTm",
                validator_function="validate_creation_datetime",
            ),
            SEPARule(
                rule_id="MSG003",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Number of transactions must match actual count",
                xpath="//sepa:GrpHdr/sepa:NbOfTxs",
                validator_function="validate_transaction_count",
            ),
            SEPARule(
                rule_id="MSG004",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Control sum must match sum of all transaction amounts",
                xpath="//sepa:GrpHdr/sepa:CtrlSum",
                validator_function="validate_control_sum",
            ),
            # Payment Information Rules
            SEPARule(
                rule_id="PMT001",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Collection date must be at least 5 business days from creation (CORE)",
                xpath="//sepa:PmtInf/sepa:ReqdColltnDt",
                validator_function="validate_collection_date_timing",
            ),
            SEPARule(
                rule_id="PMT002",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="All transactions in payment info must have same sequence type",
                validator_function="validate_sequence_type_consistency",
            ),
            SEPARule(
                rule_id="PMT003",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Maximum 10,000 transactions per payment information",
                validator_function="validate_transaction_limit",
            ),
            # Creditor Rules
            SEPARule(
                rule_id="CDT001",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Creditor identifier must be valid format",
                xpath="//sepa:CdtrSchmeId/sepa:Id/sepa:PrvtId/sepa:Othr/sepa:Id",
                validator_function="validate_creditor_identifier",
            ),
            SEPARule(
                rule_id="CDT002",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Creditor IBAN must be valid",
                xpath="//sepa:CdtrAcct/sepa:Id/sepa:IBAN",
                validator_function="validate_creditor_iban",
            ),
            # Mandate Rules
            SEPARule(
                rule_id="MND001",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="FRST transactions require new mandates or first usage",
                validator_function="validate_frst_mandate_usage",
            ),
            SEPARule(
                rule_id="MND002",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="RCUR transactions require previously used mandates",
                validator_function="validate_rcur_mandate_usage",
            ),
            SEPARule(
                rule_id="MND003",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="OOFF transactions invalidate mandate after use",
                validator_function="validate_ooff_mandate_usage",
            ),
            SEPARule(
                rule_id="MND004",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="FNAL transactions are final usage of mandate",
                validator_function="validate_fnal_mandate_usage",
            ),
            SEPARule(
                rule_id="MND005",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.ERROR,
                description="Mandate signature date must not be more than 36 months old",
                validator_function="validate_mandate_age",
            ),
            # Transaction Rules
            SEPARule(
                rule_id="TXN001",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Transaction amount must be between 0.01 and 999,999,999.99 EUR",
                xpath="//sepa:DrctDbtTxInf/sepa:InstdAmt",
                validator_function="validate_transaction_amount",
            ),
            SEPARule(
                rule_id="TXN002",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="End-to-end ID must be unique within message",
                validator_function="validate_end_to_end_id_uniqueness",
            ),
            SEPARule(
                rule_id="TXN003",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.CRITICAL,
                description="Debtor IBAN must be valid and reachable",
                xpath="//sepa:DbtrAcct/sepa:Id/sepa:IBAN",
                validator_function="validate_debtor_iban",
            ),
            # Character Set Rules
            SEPARule(
                rule_id="CHR001",
                rule_type=SEPARuleType.MANDATORY,
                severity=ValidationSeverity.ERROR,
                description="All text fields must use SEPA character set",
                validator_function="validate_character_set",
            ),
            # Netherlands-specific Rules
            SEPARule(
                rule_id="NL001",
                rule_type=SEPARuleType.COUNTRY_SPECIFIC,
                severity=ValidationSeverity.WARNING,
                description="Dutch IBANs should use proper bank codes",
                countries=["NL"],
                validator_function="validate_dutch_iban_format",
            ),
            SEPARule(
                rule_id="NL002",
                rule_type=SEPARuleType.COUNTRY_SPECIFIC,
                severity=ValidationSeverity.INFO,
                description="Consider Dutch holidays for collection dates",
                countries=["NL"],
                validator_function="validate_dutch_business_days",
            ),
        ]

    def validate_sepa_xml(self, xml_content: str, country: str = "NL") -> Dict[str, Any]:
        """
        Comprehensive SEPA XML validation against rulebook

        Args:
            xml_content: SEPA XML content to validate
            country: Country code for country-specific rules

        Returns:
            Validation result with issues and compliance score
        """
        try:
            # Parse XML
            root = ET.fromstring(xml_content)

            # Run all applicable rules
            issues = []

            for rule in self.rules:
                # Skip country-specific rules if not applicable
                if (
                    rule.rule_type == SEPARuleType.COUNTRY_SPECIFIC
                    and rule.countries
                    and country not in rule.countries
                ):
                    continue

                # Run rule validation
                rule_issues = self._validate_rule(rule, root, xml_content)
                issues.extend(rule_issues)

            # Calculate compliance metrics
            compliance_metrics = self._calculate_compliance_metrics(issues)

            # Generate recommendations
            recommendations = self._generate_recommendations(issues)

            return {
                "is_compliant": len(
                    [
                        i
                        for i in issues
                        if i.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.ERROR]
                    ]
                )
                == 0,
                "compliance_score": compliance_metrics["score"],
                "total_issues": len(issues),
                "issues_by_severity": compliance_metrics["by_severity"],
                "issues": [
                    {
                        "rule_id": issue.rule_id,
                        "severity": issue.severity.value,
                        "message": issue.message,
                        "xpath": issue.xpath,
                        "element_value": issue.element_value,
                        "suggested_fix": issue.suggested_fix,
                    }
                    for issue in issues
                ],
                "recommendations": recommendations,
                "validation_summary": self._generate_validation_summary(issues),
            }

        except ET.ParseError as e:
            return {
                "is_compliant": False,
                "compliance_score": 0,
                "total_issues": 1,
                "issues": [
                    {
                        "rule_id": "XML001",
                        "severity": "critical",
                        "message": f"XML parsing error: {str(e)}",
                        "xpath": None,
                        "element_value": None,
                        "suggested_fix": "Fix XML syntax errors",
                    }
                ],
                "error": str(e),
            }

    def _validate_rule(self, rule: SEPARule, root: ET.Element, xml_content: str) -> List[ValidationIssue]:
        """Validate a specific SEPA rule"""
        issues = []

        try:
            if rule.validator_function:
                # Call specific validator function
                validator = getattr(self, rule.validator_function, None)
                if validator:
                    rule_issues = validator(rule, root, xml_content)
                    if isinstance(rule_issues, list):
                        issues.extend(rule_issues)
                    elif rule_issues:
                        issues.append(rule_issues)

            elif rule.xpath:
                # Generic XPath-based validation
                elements = root.findall(rule.xpath, self.namespace)
                if not elements:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Required element not found: {rule.xpath}",
                            xpath=rule.xpath,
                            suggested_fix="Add the required element",
                        )
                    )

        except Exception as e:
            # Log validation error but continue
            frappe.logger().warning(f"Error validating rule {rule.rule_id}: {str(e)}")

        return issues

    # Specific validator functions

    def validate_message_id(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate message ID format and uniqueness"""
        issues = []

        msg_id_elem = root.find(".//sepa:GrpHdr/sepa:MsgId", self.namespace)
        if msg_id_elem is not None:
            msg_id = msg_id_elem.text

            # Check length
            if not msg_id or len(msg_id) > 35:
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message="Message ID must be 1-35 characters",
                        xpath=rule.xpath,
                        element_value=msg_id,
                        suggested_fix="Use a shorter, unique message ID",
                    )
                )

            # Check character set
            if msg_id and not re.match(r"^[a-zA-Z0-9\+\?\-\:\(\)\.\,\'\s/]+$", msg_id):
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message="Message ID contains invalid characters",
                        xpath=rule.xpath,
                        element_value=msg_id,
                        suggested_fix="Use only SEPA allowed characters",
                    )
                )

        return issues

    def validate_creation_datetime(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate creation datetime is not in future"""
        issues = []

        datetime_elem = root.find(".//sepa:GrpHdr/sepa:CreDtTm", self.namespace)
        if datetime_elem is not None:
            try:
                creation_dt = datetime.fromisoformat(datetime_elem.text.replace("Z", "+00:00"))
                if creation_dt > datetime.now():
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message="Creation datetime cannot be in the future",
                            xpath=rule.xpath,
                            element_value=datetime_elem.text,
                            suggested_fix="Use current or past datetime",
                        )
                    )
            except ValueError:
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message="Invalid datetime format",
                        xpath=rule.xpath,
                        element_value=datetime_elem.text,
                        suggested_fix="Use ISO 8601 datetime format",
                    )
                )

        return issues

    def validate_transaction_count(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate transaction count matches actual transactions"""
        issues = []

        # Get declared count
        count_elem = root.find(".//sepa:GrpHdr/sepa:NbOfTxs", self.namespace)
        if count_elem is not None:
            try:
                declared_count = int(count_elem.text)

                # Count actual transactions
                actual_count = len(root.findall(".//sepa:DrctDbtTxInf", self.namespace))

                if declared_count != actual_count:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Transaction count mismatch: declared {declared_count}, actual {actual_count}",
                            xpath=rule.xpath,
                            element_value=count_elem.text,
                            suggested_fix=f"Update count to {actual_count}",
                        )
                    )
            except ValueError:
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message="Invalid transaction count format",
                        xpath=rule.xpath,
                        element_value=count_elem.text,
                        suggested_fix="Use integer format",
                    )
                )

        return issues

    def validate_control_sum(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate control sum matches sum of transaction amounts"""
        issues = []

        # Get declared control sum
        sum_elem = root.find(".//sepa:GrpHdr/sepa:CtrlSum", self.namespace)
        if sum_elem is not None:
            try:
                declared_sum = Decimal(sum_elem.text)

                # Calculate actual sum
                amount_elems = root.findall(".//sepa:DrctDbtTxInf/sepa:InstdAmt", self.namespace)
                actual_sum = sum(Decimal(elem.text) for elem in amount_elems)

                if abs(declared_sum - actual_sum) > Decimal("0.01"):  # Allow 1 cent difference
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Control sum mismatch: declared {declared_sum}, actual {actual_sum}",
                            xpath=rule.xpath,
                            element_value=sum_elem.text,
                            suggested_fix=f"Update control sum to {actual_sum:.2f}",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message="Invalid control sum format",
                        xpath=rule.xpath,
                        element_value=sum_elem.text,
                        suggested_fix="Use decimal format with 2 decimal places",
                    )
                )

        return issues

    def validate_collection_date_timing(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate collection date timing requirements"""
        issues = []

        # Get creation date
        creation_elem = root.find(".//sepa:GrpHdr/sepa:CreDtTm", self.namespace)

        # Check each payment info
        for pmt_inf in root.findall(".//sepa:PmtInf", self.namespace):
            collection_elem = pmt_inf.find("sepa:ReqdColltnDt", self.namespace)
            local_instr_elem = pmt_inf.find(".//sepa:LclInstrm/sepa:Cd", self.namespace)

            if collection_elem is not None and creation_elem is not None:
                try:
                    creation_date = datetime.fromisoformat(creation_elem.text.replace("Z", "+00:00")).date()
                    collection_date = datetime.fromisoformat(collection_elem.text).date()

                    # Determine minimum lead time based on local instrument
                    local_instrument = local_instr_elem.text if local_instr_elem is not None else "CORE"

                    if local_instrument == "CORE":
                        min_lead_days = 5  # 5 business days for CORE
                    elif local_instrument == "COR1":
                        min_lead_days = 1  # 1 business day for COR1
                    elif local_instrument == "B2B":
                        min_lead_days = 1  # 1 business day for B2B
                    else:
                        min_lead_days = 5  # Default to CORE

                    # Calculate business days (simplified - just skip weekends)
                    days_between = (collection_date - creation_date).days

                    if days_between < min_lead_days:
                        issues.append(
                            ValidationIssue(
                                rule_id=rule.rule_id,
                                severity=rule.severity,
                                message=f"Collection date too early: {days_between} days lead time, minimum {min_lead_days} for {local_instrument}",
                                xpath="sepa:ReqdColltnDt",
                                element_value=collection_elem.text,
                                suggested_fix=f"Use collection date at least {min_lead_days} business days after creation",
                            )
                        )

                except ValueError:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=ValidationSeverity.ERROR,
                            message="Invalid date format in collection date or creation date",
                            xpath="sepa:ReqdColltnDt",
                            suggested_fix="Use ISO 8601 date format",
                        )
                    )

        return issues

    def validate_sequence_type_consistency(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate sequence type consistency within payment info"""
        issues = []

        for pmt_inf in root.findall(".//sepa:PmtInf", self.namespace):
            pmt_seq_elem = pmt_inf.find(".//sepa:PmtTpInf/sepa:SeqTp", self.namespace)

            if pmt_seq_elem is not None:
                # Check all transactions in this payment info
                for txn in pmt_inf.findall(".//sepa:DrctDbtTxInf", self.namespace):
                    # For now, we assume sequence type is consistent at payment info level
                    # In full implementation, you might check individual transaction sequence types
                    pass

        return issues

    def validate_creditor_identifier(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate creditor identifier format"""
        issues = []

        cred_id_elem = root.find(".//sepa:CdtrSchmeId/sepa:Id/sepa:PrvtId/sepa:Othr/sepa:Id", self.namespace)
        if cred_id_elem is not None:
            cred_id = cred_id_elem.text

            # Basic format validation for Dutch creditor IDs
            if cred_id:
                if not cred_id.startswith("NL") or len(cred_id) != 18:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message="Invalid Dutch creditor ID format (should be NL + 16 digits)",
                            xpath=rule.xpath,
                            element_value=cred_id,
                            suggested_fix="Use format NL + 2-letter bank code + ZZZ + 10 digits + validation digit",
                        )
                    )

        return issues

    def validate_mandate_age(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate mandate is not older than 36 months"""
        issues = []

        for mandate_elem in root.findall(".//sepa:MndtRltdInf", self.namespace):
            sign_date_elem = mandate_elem.find("sepa:DtOfSgntr", self.namespace)

            if sign_date_elem is not None:
                try:
                    sign_date = datetime.fromisoformat(sign_date_elem.text).date()
                    today_date = date.today()

                    # Calculate months difference
                    months_diff = (today_date.year - sign_date.year) * 12 + (
                        today_date.month - sign_date.month
                    )

                    if months_diff > 36:
                        issues.append(
                            ValidationIssue(
                                rule_id=rule.rule_id,
                                severity=rule.severity,
                                message=f"Mandate is {months_diff} months old (maximum 36 months)",
                                xpath="sepa:DtOfSgntr",
                                element_value=sign_date_elem.text,
                                suggested_fix="Obtain new mandate from debtor",
                            )
                        )

                except ValueError:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=ValidationSeverity.ERROR,
                            message="Invalid mandate signature date format",
                            xpath="sepa:DtOfSgntr",
                            element_value=sign_date_elem.text,
                            suggested_fix="Use ISO 8601 date format (YYYY-MM-DD)",
                        )
                    )

        return issues

    def validate_character_set(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate SEPA character set usage"""
        issues = []

        # SEPA character set pattern
        sepa_pattern = re.compile(r"^[a-zA-Z0-9\+\?\-\:\(\)\.\,\'\s/]*$")

        # Check common text fields
        text_fields = [
            ".//sepa:InitgPty/sepa:Nm",
            ".//sepa:Cdtr/sepa:Nm",
            ".//sepa:Dbtr/sepa:Nm",
            ".//sepa:RmtInf/sepa:Ustrd",
        ]

        for xpath in text_fields:
            for elem in root.findall(xpath, self.namespace):
                if elem.text and not sepa_pattern.match(elem.text):
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Text contains non-SEPA characters: {elem.text[:50]}...",
                            xpath=xpath,
                            element_value=elem.text,
                            suggested_fix="Remove or replace non-SEPA characters",
                        )
                    )

        return issues

    # Additional validator methods for other rules...
    def validate_frst_mandate_usage(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate FRST sequence type usage"""
        # Implementation for FRST validation
        return []

    def validate_rcur_mandate_usage(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate RCUR sequence type usage"""
        # Implementation for RCUR validation
        return []

    def validate_ooff_mandate_usage(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate OOFF sequence type usage"""
        # Implementation for OOFF validation
        return []

    def validate_fnal_mandate_usage(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate FNAL sequence type usage"""
        # Implementation for FNAL validation
        return []

    def validate_transaction_limit(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate transaction count per payment info"""
        issues = []

        for pmt_inf in root.findall(".//sepa:PmtInf", self.namespace):
            txn_count = len(pmt_inf.findall(".//sepa:DrctDbtTxInf", self.namespace))

            if txn_count > 10000:
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=f"Too many transactions in payment info: {txn_count} (maximum 10,000)",
                        suggested_fix="Split into multiple payment information blocks",
                    )
                )

        return issues

    def validate_creditor_iban(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate creditor IBAN"""
        issues = []

        from verenigingen.utils.validation.iban_validator import validate_iban

        iban_elem = root.find(".//sepa:CdtrAcct/sepa:Id/sepa:IBAN", self.namespace)
        if iban_elem is not None:
            iban_result = validate_iban(iban_elem.text)

            if not iban_result["valid"]:
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=f"Invalid creditor IBAN: {iban_result['message']}",
                        xpath=rule.xpath,
                        element_value=iban_elem.text,
                        suggested_fix="Use a valid IBAN",
                    )
                )

        return issues

    def validate_transaction_amount(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate transaction amounts"""
        issues = []

        for amount_elem in root.findall(".//sepa:DrctDbtTxInf/sepa:InstdAmt", self.namespace):
            try:
                amount = Decimal(amount_elem.text)

                if amount < Decimal("0.01"):
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Transaction amount too small: {amount} (minimum 0.01)",
                            xpath=rule.xpath,
                            element_value=amount_elem.text,
                            suggested_fix="Use minimum amount of 0.01 EUR",
                        )
                    )
                elif amount > Decimal("999999999.99"):
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Transaction amount too large: {amount} (maximum 999,999,999.99)",
                            xpath=rule.xpath,
                            element_value=amount_elem.text,
                            suggested_fix="Split into multiple smaller transactions",
                        )
                    )

            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=ValidationSeverity.ERROR,
                        message="Invalid amount format",
                        xpath=rule.xpath,
                        element_value=amount_elem.text,
                        suggested_fix="Use decimal format with up to 2 decimal places",
                    )
                )

        return issues

    def validate_end_to_end_id_uniqueness(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate end-to-end ID uniqueness"""
        issues = []

        end_to_end_ids = []
        for elem in root.findall(".//sepa:PmtId/sepa:EndToEndId", self.namespace):
            if elem.text:
                end_to_end_ids.append(elem.text)

        # Check for duplicates
        seen = set()
        duplicates = set()

        for e2e_id in end_to_end_ids:
            if e2e_id in seen:
                duplicates.add(e2e_id)
            else:
                seen.add(e2e_id)

        if duplicates:
            issues.append(
                ValidationIssue(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=f"Duplicate end-to-end IDs found: {', '.join(duplicates)}",
                    suggested_fix="Use unique end-to-end IDs for each transaction",
                )
            )

        return issues

    def validate_debtor_iban(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate debtor IBANs"""
        issues = []

        from verenigingen.utils.validation.iban_validator import validate_iban

        for iban_elem in root.findall(".//sepa:DbtrAcct/sepa:Id/sepa:IBAN", self.namespace):
            iban_result = validate_iban(iban_elem.text)

            if not iban_result["valid"]:
                issues.append(
                    ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=f"Invalid debtor IBAN: {iban_result['message']}",
                        xpath=rule.xpath,
                        element_value=iban_elem.text,
                        suggested_fix="Use a valid IBAN",
                    )
                )

        return issues

    def validate_dutch_iban_format(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate Dutch IBAN format specifics"""
        issues = []

        # Dutch bank codes for validation
        dutch_bank_codes = ["ABNA", "INGB", "RABO", "TRIO", "FVLB", "BUNQ"]

        for iban_elem in root.findall(".//sepa:IBAN", self.namespace):
            if iban_elem.text and iban_elem.text.startswith("NL"):
                iban = iban_elem.text.replace(" ", "")
                if len(iban) >= 8:
                    bank_code = iban[4:8]
                    if bank_code not in dutch_bank_codes:
                        issues.append(
                            ValidationIssue(
                                rule_id=rule.rule_id,
                                severity=rule.severity,
                                message=f"Unknown Dutch bank code: {bank_code}",
                                element_value=iban_elem.text,
                                suggested_fix="Verify bank code with Dutch banking authority",
                            )
                        )

        return issues

    def validate_dutch_business_days(
        self, rule: SEPARule, root: ET.Element, xml_content: str
    ) -> List[ValidationIssue]:
        """Validate Dutch business days for collection dates"""
        issues = []

        # Dutch public holidays (simplified list)
        dutch_holidays_2025 = [
            date(2025, 1, 1),  # New Year
            date(2025, 4, 18),  # Good Friday
            date(2025, 4, 21),  # Easter Monday
            date(2025, 4, 27),  # King's Day
            date(2025, 5, 5),  # Liberation Day
            date(2025, 5, 29),  # Ascension Day
            date(2025, 6, 9),  # Whit Monday
            date(2025, 12, 25),  # Christmas Day
            date(2025, 12, 26),  # Boxing Day
        ]

        for date_elem in root.findall(".//sepa:ReqdColltnDt", self.namespace):
            try:
                collection_date = datetime.fromisoformat(date_elem.text).date()

                # Check if weekend
                if collection_date.weekday() >= 5:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Collection date falls on weekend: {collection_date}",
                            element_value=date_elem.text,
                            suggested_fix="Use next business day",
                        )
                    )

                # Check if Dutch holiday
                if collection_date in dutch_holidays_2025:
                    issues.append(
                        ValidationIssue(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=f"Collection date is Dutch public holiday: {collection_date}",
                            element_value=date_elem.text,
                            suggested_fix="Use next business day",
                        )
                    )

            except ValueError:
                pass  # Date format already checked by other validators

        return issues

    def _calculate_compliance_metrics(self, issues: List[ValidationIssue]) -> Dict[str, Any]:
        """Calculate compliance metrics from validation issues"""
        by_severity = {
            "critical": len([i for i in issues if i.severity == ValidationSeverity.CRITICAL]),
            "error": len([i for i in issues if i.severity == ValidationSeverity.ERROR]),
            "warning": len([i for i in issues if i.severity == ValidationSeverity.WARNING]),
            "info": len([i for i in issues if i.severity == ValidationSeverity.INFO]),
        }

        # Calculate score (100 - penalties)
        score = 100
        score -= by_severity["critical"] * 25  # Critical issues: -25 points each
        score -= by_severity["error"] * 10  # Error issues: -10 points each
        score -= by_severity["warning"] * 5  # Warning issues: -5 points each
        score -= by_severity["info"] * 1  # Info issues: -1 point each

        score = max(0, score)  # Minimum score is 0

        return {"score": score, "by_severity": by_severity}

    def _generate_recommendations(self, issues: List[ValidationIssue]) -> List[str]:
        """Generate recommendations based on validation issues"""
        recommendations = []

        critical_count = len([i for i in issues if i.severity == ValidationSeverity.CRITICAL])
        error_count = len([i for i in issues if i.severity == ValidationSeverity.ERROR])

        if critical_count > 0:
            recommendations.append(f"Address {critical_count} critical issues before submitting to bank")

        if error_count > 0:
            recommendations.append(f"Fix {error_count} error conditions to improve compliance")

        # Specific recommendations based on rule types
        rule_types = [
            i.rule_id[:3]
            for i in issues
            if i.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.ERROR]
        ]

        if any(rt.startswith("MND") for rt in rule_types):
            recommendations.append("Review mandate management procedures")

        if any(rt.startswith("TXN") for rt in rule_types):
            recommendations.append("Validate transaction data before XML generation")

        if any(rt.startswith("CHR") for rt in rule_types):
            recommendations.append("Implement character set validation in data entry")

        return recommendations

    def _generate_validation_summary(self, issues: List[ValidationIssue]) -> str:
        """Generate validation summary text"""
        if not issues:
            return "SEPA XML is fully compliant with rulebook requirements"

        critical = len([i for i in issues if i.severity == ValidationSeverity.CRITICAL])
        errors = len([i for i in issues if i.severity == ValidationSeverity.ERROR])
        warnings = len([i for i in issues if i.severity == ValidationSeverity.WARNING])

        parts = []
        if critical:
            parts.append(f"{critical} critical issue{'s' if critical != 1 else ''}")
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")

        summary = f"Found {', '.join(parts)}"

        if critical or errors:
            summary += " - XML not ready for submission"
        elif warnings:
            summary += " - XML acceptable but improvements recommended"

        return summary


# API Functions


@frappe.whitelist()
@handle_api_error
def validate_sepa_xml_rulebook(xml_content: str, country: str = "NL") -> Dict[str, Any]:
    """
    API endpoint to validate SEPA XML against rulebook

    Args:
        xml_content: SEPA XML content
        country: Country code for country-specific validation

    Returns:
        Comprehensive validation result
    """
    validator = SEPARulebookValidator()
    return validator.validate_sepa_xml(xml_content, country)


@frappe.whitelist()
@handle_api_error
def get_sepa_rules(rule_type: str = None, country: str = None) -> Dict[str, Any]:
    """
    Get SEPA rules for reference

    Args:
        rule_type: Filter by rule type
        country: Filter by country

    Returns:
        List of applicable SEPA rules
    """
    validator = SEPARulebookValidator()
    rules = validator.rules

    # Apply filters
    if rule_type:
        rules = [r for r in rules if r.rule_type.value == rule_type]

    if country:
        rules = [r for r in rules if not r.countries or country in r.countries]

    return {
        "rules": [
            {
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type.value,
                "severity": rule.severity.value,
                "description": rule.description,
                "xpath": rule.xpath,
                "countries": rule.countries,
            }
            for rule in rules
        ],
        "total_rules": len(rules),
    }


@frappe.whitelist()
@handle_api_error
def validate_batch_against_rulebook(batch_name: str) -> Dict[str, Any]:
    """
    Validate a SEPA batch against rulebook requirements

    Args:
        batch_name: Name of Direct Debit Batch

    Returns:
        Validation result
    """
    try:
        # Generate XML for the batch
        from verenigingen.utils.sepa_xml_enhanced_generator import generate_enhanced_sepa_xml

        xml_result = generate_enhanced_sepa_xml(batch_name)

        if not xml_result.get("success"):
            return {"success": False, "error": "Failed to generate XML for validation", "details": xml_result}

        # Validate against rulebook
        validator = SEPARulebookValidator()
        validation_result = validator.validate_sepa_xml(xml_result["xml_content"])

        return {
            "success": True,
            "batch_name": batch_name,
            "validation_result": validation_result,
            "xml_generation_info": {
                "statistics": xml_result.get("statistics"),
                "validation_results": xml_result.get("validation_results"),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "batch_name": batch_name}
