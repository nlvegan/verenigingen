# Verenigingen

A complete association management system designed specifically for Dutch non-profit organizations. Manages your members, finances, volunteers, and chapters while ensuring compliance with Dutch regulations.

## What Verenigingen Does for Your Association

Verenigingen handles all aspects of running a modern Dutch association - from member applications to financial management to volunteer coordination. It automates routine tasks, ensures regulatory compliance, and gives your board the tools to make informed decisions.

### What Your Association Gets

- **Complete Member Management**: Handle applications, renewals, and member communications automatically
- **Automated Financial Operations**: SEPA direct debit, invoicing, and bank reconciliation without manual work
- **Geographic Chapter Organization**: Organize members by location with automated assignment based on postal codes
- **Volunteer Coordination**: Track volunteer skills, manage teams, and handle expense reimbursements
- **Professional Accounting Integration**: Direct connection to eBoekhouden for seamless bookkeeping
- **Modern Payment Processing**: Accept online payments through Mollie for donations and memberships
- **Easy Migration**: Seamlessly import your existing member data from Mijnrood exports
- **Regulatory Compliance**: Built-in compliance with Dutch association law and financial regulations
- **Administrative Automation**: Daily tasks handled automatically, freeing up your board's time


- **Additional details can be found VERENIGINGEN_PROJECT_OVERVIEW.md**
## Key Features for Your Association

### Member Management That Works
- **Online Applications**: Members apply through your website, with automatic review workflows
- **Smart Organization**: Members automatically assigned to local chapters based on their address
- **Communication Tools**: Send targeted emails to specific member groups or chapters
- **Member Portal**: Members can update their own information and view payment history
- **Proper Dutch Names**: Handles Dutch naming conventions including tussenvoegsel correctly

### Finances Made Simple
- **Automatic Dues Collection**: SEPA direct debit (batch) support for membership dues payments
- **Professional Invoicing**: Generate invoices that comply with Dutch standards
- **Bank Integration**: Import bank statements and match payments automatically
- **eBoekhouden Connection**: Your accounting records update automatically
- **Payment Flexibility**: Accept online payments for donations and fees through Mollie

### Volunteer Management
- **Skills Database**: Track what volunteers can do and match them to opportunities
- **Team Organization**: Organize volunteers into project teams with clear leadership
- **Expense Handling**: Volunteers submit expenses online, board approves with one click
- **Recognition Tools**: Track volunteer contributions and celebrate achievements

### Chapter Operations
- **Geographic Organization**: Chapters automatically get members from their area
- **Board Management**: Track chapter board positions and terms
- **Local Events**: Each chapter can manage their own activities and communications
- **Reporting**: See how each chapter is performing with membership and finances

### Compliance and Security
- **Dutch Law Compliance**: Built-in compliance with association governance requirements
- **Data Protection**: Full AVG/GDPR compliance with proper consent management
- **Audit Trails**: Complete record of who did what and when for accountability
- **Secure Access**: Role-based permissions ensure people only see what they should

## Technical Foundation

### Built for Dutch Associations
- **Modern Web Platform**: Reliable, secure, and fast
- **Dutch Integration**: Native support for Dutch banking, accounting, and regulations
- **Professional Services**: Integrates with eBoekhouden accounting and Mollie payments
- **Scalable**: Grows with your association from small local groups to large national organizations

### What You Need
- **Web Browser**: Works on any device - desktop, tablet, or phone
- **Internet Connection**: Cloud-based system accessible anywhere
- **Dutch Bank Account**: For SEPA direct debit functionality
- **Optional Integrations**: eBoekhouden for accounting, Mollie for online payments
## 🚀 **Quick Start**

### Installation

**Quick Install** (ERPNext v15+ required):
```bash
# Clone the app
bench get-app https://github.com/0spinboson/verenigingen
# Install on your site
bench --site your-site-name install-app verenigingen
# Run initial setup
bench --site your-site-name migrate
bench --site your-site-name build --app verenigingen
```

**Requirements Check**:
```bash
# Verify dependencies
bench --version  # Should be v15.0.0+
# Required apps: erpnext, payments, hrms, crm
```

### Essential Configuration
1. **Organization Setup**: Configure basic association information
2. **User Roles**: Assign role profiles to staff members
3. **Membership Types**: Define membership categories and pricing
4. **Payment Methods**: Configure SEPA and other payment options
5. **Email Templates**: Customize communication templates

### Documentation

#### Technical Overview
- **[Technical Overview](docs/VERENIGINGEN_TECHNICAL_OVERVIEW.md)** - Complete system architecture and integration

#### Detailed Subsystem Documentation
- **[Member Lifecycle Management](docs/subsystems/member-lifecycle-management.md)** - Member management and workflows
- **[Financial Operations](docs/subsystems/financial-operations.md)** - SEPA, billing, and payment processing
- **[eBoekhouden Integration](docs/subsystems/eboekhouden-integration.md)** - Dutch accounting platform sync
- **[Volunteer Management](docs/subsystems/volunteer-management.md)** - Volunteer coordination and team management
- **[Chapter Organization](docs/subsystems/chapter-organization.md)** - Geographic structure and governance
- **[Payment Processing](docs/subsystems/payment-processing-mollie.md)** - Mollie integration with payments and backend APIs, support for subscriptions and one-off payment making
- **[Security Framework](docs/subsystems/security-and-permissions.md)** - Security and compliance systems
- **[Background Processing](docs/subsystems/background-processing.md)** - Asynchronous task management
- **[Test Infrastructure](docs/subsystems/test-infrastructure.md)** - Comprehensive testing framework

#### Development
- **[Developer Guide](CLAUDE.md)** - Development workflow, commands, and guidelines
- **[Security Guide](SECURITY.md)** - Security configuration and compliance

## Perfect For Your Association

### Types of Organizations
- **Local Associations**: Sports clubs, hobby groups, neighborhood organizations
- **Professional Networks**: Industry associations, trade organizations
- **Advocacy Groups**: Environmental, social, and political organizations
- **Multi-Chapter Organizations**: National organizations with local chapters
- **Charitable Organizations**: ANBI-qualified institutions managing donations
- **Volunteer Organizations**: Groups coordinating community service and projects

### Flexible for Any Organization
- **Scales with your needs**: Use the features that matter to your organization, ignore the rest
- **Start simple, grow complex**: Begin with basic member management and add capabilities as needed
- **Multi-Chapter or Single Location**: Works equally well for local clubs and national organizations
- **Migration Support**: Seamlessly import your existing Mijnrood member data to get started quickly

## Security & Compliance You Can Trust

### Your Data Is Protected
- **Enhanced API Security**: Multi-layer security framework beyond standard protections
- **Secure Access**: Only authorized board members and volunteers can access relevant information
- **Audit Records**: Complete trail of who accessed or changed what information
- **Data Backup**: Your association's data is safely backed up and protected
- **Member Consent**: Consent management for all member communications

### Regulatory Compliance
- **Association Governance**: Meets Dutch association law requirements
- **Financial Standards**: SEPA banking compliance for automated payments (including full support for SEPA Direct Debit batches)
- **Tax Compliance**: Proper documentation for ANBI status and donations
- **Board Accountability**: Tools to ensure transparent and compliant governance
- **Security Standards**: Enterprise-grade secure operations middleware protecting sensitive data

*For technical details on our security implementation, see [Security Framework Documentation](docs/subsystems/security-and-permissions.md)*

## Support & Development

### Getting Help
- **Documentation**: Comprehensive technical guides and system documentation
- **GitHub Issues**: Bug reports and feature requests
- **Development Support**: Available for implementation and customization

### Contributing
- **Code Contributions**: Pull requests for features, fixes, and improvements welcome
- **Documentation**: Technical documentation and implementation guides
- **Testing**: Comprehensive testing framework validation
- **Security**: Responsible disclosure and security improvements

## 📄 **License**

AGPL-3.0 - See [LICENSE](license.txt) for full details

---

**Verenigingen** - Empowering Dutch associations with modern technology and compliance tools.
