# Verenigingen

A comprehensive association management system built on the Frappe Framework.

## Overview

Verenigingen is a Frappe app that provides functionality for managing associations, including:

- **Member Management**: Complete member lifecycle management with advanced features
- **Chapter Organization**: Geographic chapter management with postal code matching
- **Volunteer Coordination**: Volunteer tracking, assignments, and expense management
- **Financial Integration**: ERPNext integration for payments, invoices, and SEPA mandates
- **Termination Workflows**: Comprehensive member termination with audit trails
- **Regional Management**: Advanced region-based organization with coordinator support

## Features

### Core Modules
- **Member**: Member records with payment integration and status tracking
- **Chapter**: Geographic chapters with board member management
- **Region**: Regional organization with postal code pattern matching
- **Volunteer**: Volunteer management with team assignments and expense tracking
- **Membership Application**: Public application system with review workflows

### Advanced Features
- **SEPA Direct Debit**: Automated payment processing for European members
- **Subscription Management**: Custom override system for membership renewals
- **Termination System**: Governance-compliant termination with appeals process
- **Postal Code Matching**: Intelligent chapter assignment based on location
- **Regional Coordination**: Multi-level regional management structure

## Technical Details

- **Framework**: Frappe Framework (Python)
- **Dependencies**: ERPNext, Payments app
- **Database**: MariaDB/MySQL
- **Frontend**: JavaScript, HTML, CSS

## Installation

This app is designed to be installed in a Frappe/ERPNext environment:

## Configuration

The app requires:
- ERPNext to be installed and configured
- Payments app for financial transactions
- HRMS installed
- CRM installed
- CRM app
- HRMS app
- (Alyf-de) Banking app for reconciliation
- Proper site configuration for association settings

## Development

For development setup, ensure you have a working Frappe development environment and follow standard Frappe app development practices.

## License

agpl-3.0
