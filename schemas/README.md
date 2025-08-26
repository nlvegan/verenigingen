# SEPA XML Schema Files

This directory contains XSD schema files for SEPA XML validation.

## Required Files

- `pain.008.001.08.xsd` - SEPA Direct Debit Schema (2019 version)

## Download Sources

The official SEPA XSD schemas can be downloaded from:

- **ISO 20022**: https://www.iso20022.org/catalogue-messages/iso-20022-messages-archive
- **European Payments Council**: https://www.europeanpaymentscouncil.eu/document-library/rulebooks
- **Swift**: https://www2.swift.com/knowledgecentre/products/Standards/ISO20022

## Installation

1. Download the `pain.008.001.08.xsd` file from the official source
2. Place it in this directory
3. Install the `xmlschema` Python package: `pip install xmlschema`

## Note

Schema validation is optional - the SEPA XML generator will work without these files but will skip validation if they're not present.
