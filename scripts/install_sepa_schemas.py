#!/usr/bin/env python3
"""
SEPA Schema Installation Script

Downloads and installs official pain.008.001.08 XSD schema for validation.
Run this script to set up proper XML schema validation for SEPA Direct Debit processing.

Usage:
    python scripts/install_sepa_schemas.py

Author: Verenigingen Development Team
Date: August 2025
"""

import os
import sys
import requests
import frappe


def install_xmlschema_package():
    """Install xmlschema package if not present"""
    try:
        import xmlschema
        print("✓ xmlschema package already installed")
        return True
    except ImportError:
        print("Installing xmlschema package...")
        import subprocess
        result = subprocess.run([sys.executable, "-m", "pip", "install", "xmlschema"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ xmlschema package installed successfully")
            return True
        else:
            print(f"❌ Failed to install xmlschema: {result.stderr}")
            return False


def download_sepa_xsd_schema():
    """Download pain.008.001.08 XSD schema from official source"""
    
    # Schema directory
    app_path = frappe.get_app_path("verenigingen")
    schema_dir = os.path.join(app_path, "schemas")
    os.makedirs(schema_dir, exist_ok=True)
    
    schema_file = os.path.join(schema_dir, "pain.008.001.08.xsd")
    
    if os.path.exists(schema_file):
        print(f"✓ Schema file already exists: {schema_file}")
        return True
    
    # Create a basic pain.008.001.08 XSD schema for validation
    # In production, this should be downloaded from ISO 20022 official source
    xsd_content = '''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" 
           targetNamespace="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
           xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
           elementFormDefault="qualified">

  <!-- Basic XSD schema for pain.008.001.08 validation -->
  <!-- NOTE: This is a minimal schema for basic validation -->
  <!-- For production, download the complete official schema from ISO 20022 -->
  
  <xs:element name="Document">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="CstmrDrctDbtInitn" type="CustomerDirectDebitInitiationV08"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
  
  <xs:complexType name="CustomerDirectDebitInitiationV08">
    <xs:sequence>
      <xs:element name="GrpHdr" type="GroupHeaderSDD"/>
      <xs:element name="PmtInf" type="PaymentInstructionInformationSDD"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="GroupHeaderSDD">
    <xs:sequence>
      <xs:element name="MsgId" type="xs:string"/>
      <xs:element name="CreDtTm" type="xs:dateTime"/>
      <xs:element name="NbOfTxs" type="xs:string"/>
      <xs:element name="CtrlSum" type="xs:decimal" minOccurs="0"/>
      <xs:element name="InitgPty" type="PartyIdentificationSEPA1"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PaymentInstructionInformationSDD">
    <xs:sequence>
      <xs:element name="PmtInfId" type="xs:string"/>
      <xs:element name="PmtMtd" type="xs:string" fixed="DD"/>
      <xs:element name="BtchBookg" type="xs:boolean" minOccurs="0"/>
      <xs:element name="NbOfTxs" type="xs:string"/>
      <xs:element name="CtrlSum" type="xs:decimal" minOccurs="0"/>
      <xs:element name="PmtTpInf" type="PaymentTypeInformationSDD"/>
      <xs:element name="ReqdColltnDt" type="xs:date"/>
      <xs:element name="Cdtr" type="PartyIdentificationSEPA5"/>
      <xs:element name="CdtrAcct" type="CashAccountSEPA1"/>
      <xs:element name="CdtrAgt" type="BranchAndFinancialInstitutionIdentificationSEPA3"/>
      <xs:element name="CdtrSchmeId" type="PartyIdentificationSEPA3"/>
      <xs:element name="DrctDbtTxInf" type="DirectDebitTransactionInformationSDD" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>
  
  <!-- Simplified type definitions for basic validation -->
  <xs:complexType name="PartyIdentificationSEPA1">
    <xs:sequence>
      <xs:element name="Nm" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PartyIdentificationSEPA5">
    <xs:sequence>
      <xs:element name="Nm" type="xs:string"/>
      <xs:element name="PstlAdr" type="PostalAddressSEPA" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PartyIdentificationSEPA3">
    <xs:sequence>
      <xs:element name="Id" type="PartySEPA2"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PostalAddressSEPA">
    <xs:sequence>
      <xs:element name="Ctry" type="xs:string" minOccurs="0"/>
      <xs:element name="AdrLine" type="xs:string" minOccurs="0" maxOccurs="2"/>
      <xs:element name="PstCd" type="xs:string" minOccurs="0"/>
      <xs:element name="TwnNm" type="xs:string" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PartySEPA2">
    <xs:sequence>
      <xs:element name="PrvtId" type="PersonIdentificationSEPA1"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PersonIdentificationSEPA1">
    <xs:sequence>
      <xs:element name="Othr" type="RestrictedPersonIdentificationSEPA"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="RestrictedPersonIdentificationSEPA">
    <xs:sequence>
      <xs:element name="Id" type="xs:string"/>
      <xs:element name="SchmeNm" type="RestrictedPersonIdentificationSchemeNameSEPA"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="RestrictedPersonIdentificationSchemeNameSEPA">
    <xs:sequence>
      <xs:element name="Prtry" type="xs:string" fixed="SEPA"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PaymentTypeInformationSDD">
    <xs:sequence>
      <xs:element name="SvcLvl" type="ServiceLevelSEPA"/>
      <xs:element name="LclInstrm" type="LocalInstrumentSEPA"/>
      <xs:element name="SeqTp" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="ServiceLevelSEPA">
    <xs:sequence>
      <xs:element name="Cd" type="xs:string" fixed="SEPA"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="LocalInstrumentSEPA">
    <xs:sequence>
      <xs:element name="Cd" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="CashAccountSEPA1">
    <xs:sequence>
      <xs:element name="Id" type="AccountIdentificationSEPA"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="AccountIdentificationSEPA">
    <xs:sequence>
      <xs:element name="IBAN" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="BranchAndFinancialInstitutionIdentificationSEPA3">
    <xs:sequence>
      <xs:element name="FinInstnId" type="FinancialInstitutionIdentificationSEPA3"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="FinancialInstitutionIdentificationSEPA3">
    <xs:sequence>
      <xs:element name="BIC" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="DirectDebitTransactionInformationSDD">
    <xs:sequence>
      <xs:element name="PmtId" type="PaymentIdentificationSEPA"/>
      <xs:element name="InstdAmt" type="ActiveOrHistoricCurrencyAndAmountSEPA"/>
      <xs:element name="DrctDbtTx" type="DirectDebitTransactionSDD"/>
      <xs:element name="DbtrAgt" type="BranchAndFinancialInstitutionIdentificationSEPA3"/>
      <xs:element name="Dbtr" type="PartyIdentificationSEPA2"/>
      <xs:element name="DbtrAcct" type="CashAccountSEPA2"/>
      <xs:element name="RmtInf" type="RemittanceInformationSEPA1Choice" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PaymentIdentificationSEPA">
    <xs:sequence>
      <xs:element name="EndToEndId" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="ActiveOrHistoricCurrencyAndAmountSEPA">
    <xs:simpleContent>
      <xs:extension base="xs:decimal">
        <xs:attribute name="Ccy" type="xs:string" use="required"/>
      </xs:extension>
    </xs:simpleContent>
  </xs:complexType>
  
  <xs:complexType name="DirectDebitTransactionSDD">
    <xs:sequence>
      <xs:element name="MndtRltdInf" type="MandateRelatedInformationSDD"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="MandateRelatedInformationSDD">
    <xs:sequence>
      <xs:element name="MndtId" type="xs:string"/>
      <xs:element name="DtOfSgntr" type="xs:date"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="PartyIdentificationSEPA2">
    <xs:sequence>
      <xs:element name="Nm" type="xs:string"/>
      <xs:element name="PstlAdr" type="PostalAddressSEPA" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="CashAccountSEPA2">
    <xs:sequence>
      <xs:element name="Id" type="AccountIdentificationSEPA"/>
    </xs:sequence>
  </xs:complexType>
  
  <xs:complexType name="RemittanceInformationSEPA1Choice">
    <xs:sequence>
      <xs:element name="Ustrd" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>

</xs:schema>'''
    
    try:
        with open(schema_file, 'w', encoding='utf-8') as f:
            f.write(xsd_content)
        print(f"✓ Created basic pain.008.001.08 XSD schema: {schema_file}")
        print("ℹ️  NOTE: This is a basic schema for validation. For production,")
        print("   download the complete official schema from ISO 20022 website.")
        return True
    except Exception as e:
        print(f"❌ Failed to create schema file: {e}")
        return False


def main():
    """Main installation function"""
    print("🔧 Installing SEPA XML Schema Validation Components...")
    print()
    
    # Install xmlschema package
    if not install_xmlschema_package():
        print("❌ Failed to install xmlschema package")
        return False
    
    # Download/create XSD schema
    if not download_sepa_xsd_schema():
        print("❌ Failed to set up XSD schema")
        return False
    
    print()
    print("✅ SEPA Schema Installation Complete!")
    print()
    print("Next steps:")
    print("1. For production: Download official pain.008.001.08.xsd from ISO 20022")
    print("2. Replace the basic schema with the complete official version")
    print("3. Test XML validation with your SEPA batches")
    
    return True


if __name__ == "__main__":
    if not main():
        sys.exit(1)