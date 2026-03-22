# Installation Guide

Complete installation and setup guide for the Vereiningen association management system with ERPNext integration.

## Table of Contents

- [Overview](#overview)
- [System Requirements](#system-requirements)
- [Prerequisites](#prerequisites)
- [Installation Steps](#installation-steps)
- [Initial Configuration](#initial-configuration)
- [Post-Installation Setup](#post-installation-setup)
- [Production Deployment](#production-deployment)
- [Integration Setup](#integration-setup)
- [Testing and Validation](#testing-and-validation)
- [Troubleshooting](#troubleshooting)
- [Verification Checklist](#verification-checklist)

## Overview

The Vereiningen app is a comprehensive association management system built on the Frappe Framework with ERPNext integration. This guide covers the complete installation process from system preparation to production deployment.

### Key Features Installed

- **Member Management**: Complete member lifecycle with automated workflows
- **Chapter Organization**: Geographic organization with postal code matching
- **Volunteer Coordination**: Team management with expense tracking
- **Financial Integration**: ERPNext Sales Invoice integration with SEPA direct debit
- **eBoekhouden Integration**: Complete Dutch accounting system synchronization
- **Portal Systems**: Member and volunteer self-service portals
- **Analytics and Reporting**: Business intelligence and compliance reporting
- **Brand Management**: Customizable theming and portal appearance
- **Dutch Compliance**: ANBI, GDPR, and Belastingdienst reporting capabilities

## System Requirements

### Minimum Requirements

- **Operating System**: Ubuntu 22.04+ LTS, Debian 12+
- **RAM**: 8 GB minimum, 16 GB recommended for production
- **Storage**: 50 GB minimum, 100 GB+ recommended for production with eBoekhouden integration
- **CPU**: 4 cores minimum, 8+ cores recommended for production
- **Network**: Stable internet connection (required for eBoekhouden API and email services)

### Production Requirements

- **RAM**: 32 GB recommended for large organizations (5000+ members)
- **Storage**: SSD storage with 200 GB+ for optimal performance
- **CPU**: 16+ cores for heavy financial integration workloads
- **Backup**: Automated backup solution with off-site storage
- **Monitoring**: System monitoring and alerting capabilities

### Software Dependencies

#### Core Framework Dependencies

- **Python**: 3.10+ (3.11 or 3.12 recommended)
- **Node.js**: 18.x LTS or 20.x LTS
- **MariaDB**: 10.6+ (10.11+ recommended)
- **Redis**: 6.x+ (7.x recommended)
- **Nginx**: 1.20+ (for production)
- **Supervisor**: 4.x+ (for process management)

#### Python Dependencies (from pyproject.toml)

| Package | Version | Purpose |
|---------|---------|---------|
| mollie-api-python | >= 3.6.0 | Mollie payment gateway integration |
| cryptography | >= 41.0.0 | Encryption and signing |
| requests | >= 2.31.0 | HTTP client |
| python-dateutil | >= 2.8.2 | Date/time utilities |
| scikit-learn | >= 1.0.0 | Predictive analytics (churn, etc.) |
| mt-940 | >= 4.0 | Bank statement (MT940) parsing |
| defusedxml | >= 0.7.1 | XML security (XXE prevention) |
| sshtunnel | >= 0.4.0 | MijnRood sync SSH tunneling |
| paramiko | >= 2.7.2, < 4.0 | SSH transport (pinned < 4.0 for sshtunnel compat) |
| pymysql | >= 1.1.0 | MijnRood remote MySQL client |

**Dev/test extras** (installed with `pip install -e ".[dev]"`):

| Package | Version | Purpose |
|---------|---------|---------|
| faker | >= 18.0.0 | Test data generation |
| requests-mock | >= 1.11.0 | HTTP mocking in tests |
| pytest | >= 7.0.0 | Test runner |
| psutil | >= 5.9.0 | System metrics in tests |
| hypothesis | >= 6.0.0 | Property-based testing |

#### Node.js Dependencies (from package.json)

Runtime: `frappe-ui`, `js-yaml`

Dev/build: `tailwindcss` (v4), `jest`, `cypress`, `playwright`, `eslint`, `prettier`

See `package.json` for the full list.

#### Development Dependencies

- **Git**: 2.34+ for source control
- **Yarn**: Latest stable for asset building
- **wkhtmltopdf**: 0.12.6+ for PDF generation

## Prerequisites

### Required Frappe Framework Apps

The Vereiningen app depends on these apps (declared in `pyproject.toml` under `[tool.bench.frappe-dependencies]`):

| App | Version | Purpose |
|-----|---------|---------|
| Frappe Framework | v16-dev (develop branch) | Core framework |
| ERPNext | >= 15.0.0 | Accounting, invoicing, company structure |
| Payments | >= 0.0.1 | Payment gateway infrastructure |
| HRMS | >= 15.0.0 | Employee and volunteer management |

### External Service Prerequisites

#### Required Services

- **Email Service**: SMTP server (Gmail, SendGrid, Mailgun, or corporate SMTP). Domain authentication (SPF, DKIM) recommended for production.
- **eBoekhouden Account** (for Dutch organizations): Active subscription with API access credentials.

#### Recommended Services

- **SSL Certificate**: Let's Encrypt or commercial certificate
- **Domain Name**: Dedicated domain for your association
- **Backup Service**: Cloud backup solution (AWS S3, Google Cloud, etc.)

## Installation Steps

### Step 1: System Preparation

1. **Update System Packages**:

   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt upgrade -y

   sudo apt install -y python3-dev python3-pip python3-venv \
                       nodejs npm yarn redis-server mariadb-server \
                       nginx supervisor git curl wget \
                       wkhtmltopdf xvfb libfontconfig
   ```

2. **Configure MariaDB**:

   ```bash
   sudo mysql_secure_installation

   sudo tee /etc/mysql/conf.d/frappe.cnf > /dev/null <<EOF
   [mysqld]
   character-set-client-handshake = FALSE
   character-set-server = utf8mb4
   collation-server = utf8mb4_unicode_ci

   [mysql]
   default-character-set = utf8mb4
   EOF

   sudo systemctl restart mariadb
   ```

3. **Create Frappe User**:

   ```bash
   sudo adduser frappe --home /home/frappe
   sudo usermod -aG sudo frappe
   sudo su - frappe
   ```

### Step 2: Install Frappe Bench

1. **Install Frappe Bench**:

   ```bash
   pip3 install frappe-bench
   export PATH=$PATH:~/.local/bin
   echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc
   ```

2. **Initialize New Bench**:

   ```bash
   bench init --frappe-branch develop frappe-bench
   cd frappe-bench
   ```

3. **Create Site**:

   ```bash
   bench new-site your-association.com --admin-password your-secure-password
   bench use your-association.com
   ```

### Step 3: Install Required Applications

1. **Install ERPNext**:

   ```bash
   bench get-app --branch develop erpnext
   bench --site your-association.com install-app erpnext
   ```

2. **Install Payments App**:

   ```bash
   bench get-app --branch develop payments
   bench --site your-association.com install-app payments
   ```

3. **Install HRMS**:

   ```bash
   bench get-app --branch develop hrms
   bench --site your-association.com install-app hrms
   ```

### Step 4: Install Vereiningen App

1. **Get Vereiningen App**:

   ```bash
   # From repository (replace with your repository URL)
   bench get-app verenigingen https://github.com/your-organization/verenigingen.git

   # Or from a local path
   # bench get-app verenigingen /path/to/local/verenigingen
   ```

2. **Install Application**:

   ```bash
   bench --site your-association.com install-app verenigingen
   bench --site your-association.com list-apps
   ```

3. **Run Migrations and Build Assets**:

   ```bash
   bench --site your-association.com migrate
   bench build --app verenigingen
   bench --site your-association.com clear-cache
   ```

### What Happens During Installation

When `install-app verenigingen` runs, the framework executes the `after_install` hooks defined in `verenigingen/hooks/lifecycle.py`:

1. **`verenigingen.setup.execute_after_install`** -- Creates initial reference data (membership types, email templates, payment modes). This is idempotent and checks a `initial_setup_complete` flag to avoid overwriting user customizations on re-run.
2. **`verenigingen.setup.security_setup.setup_all_security`** -- Configures security framework (roles, permission rules, audit logging).
3. **`verenigingen.setup.critical_operation_rules_setup.setup_critical_operation_rules`** -- Creates rate-limiting rules for sensitive operations (merges, deletions, etc.).

After every migration (`bench migrate`), the `after_migrate` hooks run additional setup:

- Ensures required payment modes exist
- Creates default Brand Settings
- Sets up security framework and database indexes
- Runs performance optimization patches
- Syncs document category options from Settings into DocField metadata

Fixtures (defined in `vereinigingen/hooks/fixtures.py`) are also imported during install. These include Property Setters, Custom DocPerms, Workflow definitions, Roles, Role Profiles, Workspaces, Dashboard Charts, and the background service user account.

### Step 5: Verification and Initial Access

1. **Start Development Server**:

   ```bash
   bench start
   # Access via browser: http://localhost:8000
   ```

2. **Verify System Access**:
   - Login with Administrator credentials created during site setup
   - Go to Desk and verify "Verenigingen" appears in the module list
   - Navigate to Settings > Installed Applications to confirm all apps are listed

3. **Initial System Check**:

   ```bash
   bench --site your-association.com doctor
   bench --site your-association.com list-apps
   ```

## Initial Configuration

### Step 1: Company and Organization Setup

1. **Configure Company Details** (navigate to Accounting > Company):
   - Company Name, Abbreviation, Default Currency (EUR), Country (Netherlands)
   - Tax ID (KvK number), complete legal address

2. **Fiscal Year Setup** (navigate to Accounting > Fiscal Year):
   - Year Start Date: January 1
   - Year End Date: December 31

3. **System Settings** (navigate to Settings > System Settings):
   - Country: Netherlands
   - Time Zone: Europe/Amsterdam
   - Date Format: dd-mm-yyyy
   - Number Format: #.###,## (European)

### Step 2: User Management and Security

1. **Deploy Role Profiles**:

   ```bash
   bench --site your-association.com execute \
       verenigingen.setup.role_profile_setup.setup_role_profiles_cli
   ```

   This creates eight role profiles: Verenigingen Member, Volunteer, Team Leader, Chapter Board Member, Treasurer, Staff, System Administrator, and Auditor.

2. **Create Administrative Users** (navigate to Users and Permissions > User):
   - Assign appropriate role profiles
   - Enable two-factor authentication for administrators

### Step 3: Communication Setup

1. **Configure Email** (navigate to Settings > Email Account):
   - Set SMTP host, port (587/TLS), credentials
   - Send a test email to verify

2. **Install Email Templates**:

   ```bash
   bench --site your-association.com execute \
       verenigingen.api.email_template_manager.create_comprehensive_email_templates
   ```

### Step 4: Association-Specific Data Setup

1. **Create Membership Types** (navigate to Verenigingen > Membership Type):
   - Define categories (Individual, Student, Senior, Family, Corporate)
   - Set fee amounts and billing frequencies

2. **Setup Chapters** (navigate to Verenigingen > Chapter):
   - Create geographic chapters with postal code patterns

3. **Configure SEPA Direct Debit** (navigate to Vereiningen > SEPA Settings):
   - Creditor ID, bank account, mandate configuration

### Step 5: Integration Configuration

#### eBoekhouden Integration (Dutch Organizations)

1. **Configure Settings** (navigate to Setup > E-Boekhouden Settings):
   - API URL, username, security codes, API token
   - Map to your ERPNext company

2. **Setup Account Mapping** (navigate to Setup > eBoekhouden Account Mapping):
   - Map eBoekhouden accounts to ERPNext chart of accounts

### Step 6: Portal Configuration

1. **Member Portal** (navigate to Website > Portal Settings):
   - Default Role: Member
   - Default Home Page: `/member/dashboard`

2. **Brand Management** (navigate to `/brand_management`):
   - Primary/secondary colors, logo, favicon
   - Portal theming

## Post-Installation Setup

### Brand and Appearance

Configure organization branding at `/brand_management` (requires System Manager role). Upload logos, set colors, and generate custom CSS for portals.

### User Onboarding

1. Create user accounts for staff, assign role profiles
2. Refer administrators to [ADMIN_GUIDE.md](ADMIN_GUIDE.md)
3. Refer members to the [membership management docs](features/membership-management.md)
4. Refer volunteers to the [volunteer management docs](features/volunteer-management.md)

## Production Deployment

### Production Configuration

```bash
# Disable development mode
bench --site your-association.com set-config developer_mode 0
bench --site your-association.com set-config allow_tests 0

# Setup production services (Nginx + Supervisor)
sudo bench setup production --user frappe
```

This single command configures Nginx, Supervisor, and Redis. It also enables and starts the web server, scheduler, and worker processes.

### SSL Setup

```bash
# Let's Encrypt (free, automated)
sudo bench setup lets-encrypt your-association.com
```

### Firewall

```bash
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
```

### Backup Configuration

```bash
# Enable scheduler (needed for automated backups)
bench --site your-association.com enable-scheduler

# Manual backup
bench --site your-association.com backup --with-files
```

For automated offsite backups, set up a cron job that runs `bench backup --with-files` and syncs the output to cloud storage (S3, GCS, etc.).

### Database Tuning (Optional)

For large deployments, add a MariaDB config file (`/etc/mysql/conf.d/frappe-production.cnf`):

```ini
[mysqld]
innodb_buffer_pool_size = 1G
innodb_log_file_size = 256M
innodb_flush_log_at_trx_commit = 2
innodb_file_per_table = 1
max_connections = 200
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 2
```

Restart MariaDB after changes.

## Integration Setup

### eBoekhouden Data Migration

```bash
# Test API connectivity
bench --site your-association.com execute \
    verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator

# Start full import
bench --site your-association.com execute \
    verenigingen.utils.eboekhouden_rest_full_migration.start_full_rest_import \
    --args '{"migration_name": "Initial Migration 2025"}'

# Monitor progress
bench --site your-association.com execute \
    verenigingen.utils.eboekhouden_rest_full_migration.get_migration_status
```

### Scheduled Tasks

The app registers many scheduled tasks (see `verenigingen/hooks/scheduler.py`). Key categories:

- **Daily**: Membership expiry, renewal reminders, dues invoice generation, SEPA mandate checks, eBoekhouden sync, payment retry, bank reconciliation, expense approver sync
- **Hourly**: Security digests, analytics alerts, payment history validation, SEPA pain.002 ingestion
- **Weekly**: Termination reports, security health check, address maintenance
- **Monthly**: Address data cleanup, expense history cleanup
- **Cron (sub-minute)**: Financial history batch processing (every 30 seconds), MijnRood sync (every 15 minutes)

These tasks run automatically when the scheduler is enabled. No manual setup is needed.

## Testing and Validation

### Running the Test Suite

```bash
# Run all Vereiningen tests
cd ~/frappe-bench
bench --site your-association.com run-tests --app verenigingen

# Run tests for a specific DocType
bench --site your-association.com run-tests --app verenigingen --doctype "Member"

# Run parallel tests for faster execution
bench --site your-association.com run-parallel-tests --app verenigingen
```

### JavaScript Tests

```bash
cd ~/frappe-bench/apps/verenigingen

# Jest unit tests
npm test

# Cypress end-to-end tests
npm run test:e2e
```

### Production Validation

After installation, verify these basics:

```bash
# System diagnostics
bench --site your-association.com doctor

# Check installed apps
bench --site your-association.com list-apps

# Verify email works
bench --site your-association.com console
# >>> frappe.sendmail(recipients=['test@example.com'], subject='Test', message='Test')
```

## Troubleshooting

### Common Installation Issues

**Frappe Bench installation fails with permission errors**

```bash
sudo chown -R frappe:frappe /home/frappe
```

**App installation fails with dependency conflicts**

```bash
bench --site your-association.com uninstall-app verenigingen
bench remove-app verenigingen
bench get-app verenigingen https://github.com/your-org/verenigingen.git
bench --site your-association.com install-app verenigingen --force
```

**Migration errors during app installation**

```bash
bench --site your-association.com migrate --reset-permissions
bench --site your-association.com clear-cache
```

**MariaDB connection timeouts**

Add to `/etc/mysql/conf.d/frappe.cnf`:
```
wait_timeout = 28800
interactive_timeout = 28800
```
Then restart MariaDB.

**Emails not sending**

```bash
bench --site your-association.com console
# >>> frappe.sendmail(recipients=['test@example.com'], subject='Test', message='Test message')
```

Check Settings > Email Account for correct SMTP credentials.

**eBoekhouden API connection failures**

```bash
bench --site your-association.com execute \
    verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator
```

Verify credentials at Setup > E-Boekhouden Settings.

**Portal pages not loading**

```bash
bench build --app verenigingen
bench --site your-association.com clear-cache
bench --site your-association.com clear-website-cache
```

### Log Locations

- Application logs: `frappe-bench/logs/`
- Site-specific logs: `frappe-bench/sites/<site>/logs/`
- Worker errors: `frappe-bench/logs/worker.error.log`
- Web server: `frappe-bench/logs/web.log`

## Verification Checklist

### Core System

- [ ] Login successful with Administrator account
- [ ] Vereiningen module appears in module list
- [ ] All required apps listed (`bench list-apps`)
- [ ] All migrations completed successfully

### User Management

- [ ] Role profiles deployed and functional
- [ ] User accounts created with correct permissions
- [ ] Two-factor authentication enabled for admins

### Communication

- [ ] SMTP configured and test email received
- [ ] Email templates created
- [ ] System notifications working

### Financial

- [ ] Company and fiscal year configured
- [ ] Chart of accounts set up
- [ ] Payment methods configured (SEPA, etc.)
- [ ] eBoekhouden connectivity verified (if applicable)

### Association Management

- [ ] Membership types created
- [ ] Chapters set up (if applicable)
- [ ] Member and volunteer portals accessible
- [ ] Brand settings applied

### Production (if deploying to production)

- [ ] SSL certificate installed
- [ ] Firewall configured (ports 80, 443, SSH only)
- [ ] Automated backups configured
- [ ] Scheduler enabled
- [ ] Developer mode disabled

---

For ongoing administration, refer to the [Administrator Guide](ADMIN_GUIDE.md). For role-specific guidance, see the [documentation index](README.md).
