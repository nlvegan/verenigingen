# Verenigingen App Permissions Audit Summary
Generated: 2025-08-03 23:35:11.037151

## Overview
- Total DocTypes: 51
- Total Reports: 17
- DocTypes with Issues: 4
- Reports with Issues: 0

## Priority Issues
- Critical: 4
- High: 0
- Medium: 1

## 🚨 CRITICAL Issues (Immediate Action Required)

**Direct Debit Batch**: FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions
**Donation**: FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions
**Member**: BROAD_ACCESS_SENSITIVE: Sensitive DocType has 9 roles with read access
**SEPA Mandate**: FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions

## Module Breakdown

### E-Boekhouden
- Total DocTypes: 8
- DocTypes with Issues: 0

### Verenigingen
- Total DocTypes: 43
- DocTypes with Issues: 4
- DocTypes: Chapter, Chapter Board Member, Chapter Member, Chapter Membership History, Chapter Role, Communication History, Contribution Amendment Request, Direct Debit Batch, Direct Debit Batch Invoice, Donation, Donation History, Donation Type, Donor, Donor Relationships, Expense Category, Expulsion Report Entry, Member, Member Contact Request, Member Fee Change History, Member Payment History, Member SEPA Mandate Link, Member Volunteer Expenses, Membership, Membership Termination Request, Membership Type, Pledge History, Region, SEPA Mandate, SEPA Mandate Usage, Team, Team Member, Team Responsibility, Team Role, Termination Audit Entry, Verenigingen Settings, Volunteer, Volunteer Activity, Volunteer Assignment, Volunteer Development Goal, Volunteer Expense, Volunteer Interest Area, Volunteer Interest Category, Volunteer Skill

## Detailed DocType Issues

### Direct Debit Batch (Verenigingen)
- FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions

### Donation (Verenigingen)
- FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions

### Member (Verenigingen)
- BROAD_ACCESS_SENSITIVE: Sensitive DocType has 9 roles with read access
- COMPLEX_PERMISSIONS: 9 permission entries may be hard to maintain

### SEPA Mandate (Verenigingen)
- FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions
