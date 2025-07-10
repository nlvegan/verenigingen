# Verenigingen

A comprehensive association management system built on the Frappe Framework for Dutch non-profit organizations.

## Overview

Verenigingen is a powerful Frappe application designed specifically for Dutch associations, non-profits, and NGOs. It provides complete business process management with regulatory compliance and modern automation features.

### Core Capabilities

- **Member Management**: Complete lifecycle from application to termination with automated workflows
- **Financial Integration**: Full ERPNext integration with SEPA direct debit and invoice processing
- **Chapter Organization**: Geographic chapters with postal code matching and board management
- **Volunteer Coordination**: Assignment tracking, expense management, and team organization
- **eBoekhouden Integration**: Comprehensive accounting system integration with REST/SOAP API support
- **Dutch Compliance**: ANBI qualification, GDPR compliance, and Belastingdienst reporting
- **Portal Systems**: Member and volunteer self-service portals with responsive design
- **Analytics & Reporting**: Real-time business intelligence with predictive analytics

## Key Features

### 🏢 **Organizational Management**
- **Multi-Chapter Structure**: Regional chapters with geographic postal code assignment
- **Board Management**: Chapter board positions with role-based permissions
- **Regional Coordination**: Hierarchical organization with regional oversight
- **Department Integration**: ERPNext HR integration for staff management

### 👥 **Member Lifecycle Management**
- **Application Processing**: Online applications with review workflows and approval tracking
- **Membership Types**: Flexible membership categories with custom pricing and periods
- **Status Tracking**: Complete member journey from application to termination
- **Automated Billing**: Subscription management with custom override capabilities
- **Termination Workflows**: Governance-compliant termination with audit trails and appeals

### 💰 **Financial Operations**
- **SEPA Direct Debit**: EU-compliant automated payment collection with mandate management
- **eBoekhouden Integration**: Complete accounting system synchronization via REST/SOAP APIs
- **Invoice Processing**: Automated invoice generation and payment tracking
- **Banking Integration**: MT940 import and bank reconciliation with Dutch banking standards
- **Donation Management**: ANBI-compliant donation tracking with tax receipt generation

### 🤝 **Volunteer Management**
- **Volunteer Profiles**: Skills tracking, availability, and assignment history
- **Team Organization**: Project-based teams with leader assignments
- **Expense Management**: Volunteer expense claims with approval workflows
- **Goal Setting**: Personal development tracking and achievement recognition
- **Time Tracking**: Volunteer hour logging and contribution analytics

### 🌐 **Portal Systems**
- **Member Portal**: Self-service member management with payment history and profile updates
- **Volunteer Portal**: Assignment tracking, expense submission, and team collaboration
- **Brand Management**: Customizable theming system with real-time color preview
- **Mobile Responsive**: Full functionality across all device types

### 📊 **Analytics & Intelligence**
- **Membership Analytics**: Real-time KPI tracking with predictive modeling
- **Financial Reporting**: Comprehensive revenue and payment analysis
- **Volunteer Impact**: Contribution tracking and resource optimization
- **Cohort Analysis**: Member retention and lifecycle insights
- **Automated Alerts**: Proactive notifications for critical metrics

## 🛠 **Technical Architecture**

### Technology Stack
- **Backend**: Python 3.10+ with Frappe Framework v15
- **Frontend**: Modern JavaScript ES6+ with responsive HTML5/CSS3
- **Database**: MariaDB/MySQL with optimized indexing
- **Queue System**: Redis for background job processing
- **API**: RESTful APIs with OpenAPI documentation

### Required Dependencies
- **ERPNext**: Core ERP functionality and financial modules
- **Payments App**: Payment gateway integrations and processing
- **HRMS App**: Human resources and employee management
- **CRM App**: Customer relationship management features
- **Banking App** (Alyf-de): Dutch bank reconciliation and MT940 import

### Integration Capabilities
- **eBoekhouden API**: REST/SOAP integration for accounting synchronization
- **SEPA Direct Debit**: EU payment processing compliance
- **Dutch Banking**: MT940, CAMT, and bank reconciliation formats
- **Email Systems**: SMTP, SendGrid, Mailgun integration
- **External APIs**: Extensible API framework for third-party integrations

## 🚀 **Quick Start**

### Installation
```bash
# Install in existing ERPNext environment
bench get-app https://github.com/verenigingen/verenigingen
bench install-app verenigingen --site your-site-name
bench migrate
```

### Essential Configuration
1. **Organization Setup**: Configure basic association information
2. **User Roles**: Assign role profiles to staff members
3. **Membership Types**: Define membership categories and pricing
4. **Payment Methods**: Configure SEPA and other payment options
5. **Email Templates**: Customize communication templates

### Documentation Links
- **[📖 Complete Documentation](docs/README.md)** - Comprehensive guides and references
- **[🚀 Getting Started](docs/GETTING_STARTED.md)** - Step-by-step setup guide
- **[👨‍💼 Admin Guide](docs/ADMIN_GUIDE.md)** - Administrative procedures and configuration
- **[🔌 API Documentation](docs/API_DOCUMENTATION.md)** - Integration and development reference
- **[❓ FAQ & Troubleshooting](docs/FAQ_TROUBLESHOOTING.md)** - Common questions and solutions

## 🎯 **Use Cases**

### Perfect For
- **Non-profit Organizations**: Member-driven associations with complex needs
- **NGOs**: International organizations requiring multi-chapter management
- **Professional Associations**: Industry groups with certification and member services
- **Community Organizations**: Local groups with volunteer coordination needs
- **Charitable Institutions**: ANBI-qualified organizations with donation management

### Organization Sizes
- **Small** (< 100 members): Quick setup with essential features
- **Medium** (100-1000 members): Full automation and process optimization
- **Large** (1000+ members): Enterprise features with advanced analytics
- **Multi-Chapter**: Complex organizational structures with regional management

## 🔒 **Security & Compliance**

### Privacy & Data Protection
- **GDPR Compliant**: Built-in privacy features and data protection
- **ANBI Qualification**: Dutch tax-exempt organization compliance
- **Audit Trails**: Complete activity logging and change tracking
- **Access Controls**: Role-based permissions with fine-grained control
- **Data Encryption**: Secure storage of sensitive member and financial data

### Dutch Regulatory Compliance
- **Belastingdienst Reporting**: Automated tax authority reporting
- **SEPA Compliance**: EU payment processing standards
- **Banking Standards**: Dutch banking integration and reconciliation
- **Accounting Integration**: eBoekhouden and other Dutch accounting systems

## 🤝 **Community & Support**

### Getting Help
- **[Documentation](docs/)**: Comprehensive guides and tutorials
- **GitHub Issues**: Bug reports and feature requests
- **Community Forums**: User discussions and best practices
- **Professional Support**: Available for enterprise deployments

### Contributing
- **Code Contributions**: Pull requests welcome for features and fixes
- **Documentation**: Help improve guides and examples
- **Testing**: Beta testing for new features and releases
- **Feedback**: User experience insights and improvement suggestions

## 📄 **License**

AGPL-3.0 - See [LICENSE](license.txt) for full details

---

**Verenigingen** - Empowering Dutch associations with modern technology and compliance tools.
