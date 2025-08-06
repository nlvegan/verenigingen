# 🚀 Installation Guide

Complete installation and setup guide for the Verenigingen comprehensive association management system with ERPNext integration.

## 📋 Table of Contents
- [🎯 Overview](#-overview)
- [⚙️ System Requirements](#️-system-requirements)
- [📋 Prerequisites](#-prerequisites)
- [🔧 Installation Steps](#-installation-steps)
- [🎛️ Initial Configuration](#️-initial-configuration)
- [🔄 Post-Installation Setup](#-post-installation-setup)
- [🌐 Production Deployment](#-production-deployment)
- [📊 Integration Setup](#-integration-setup)
- [🧪 Testing and Validation](#-testing-and-validation)
- [🔧 Troubleshooting](#-troubleshooting)
- [✅ Verification Checklist](#-verification-checklist)

## 🎯 Overview

The Verenigingen app is a comprehensive association management system built on the Frappe Framework with ERPNext integration. This guide covers the complete installation process from system preparation to production deployment.

### 🌟 Key Features Installed
- **👥 Member Management**: Complete member lifecycle with automated workflows
- **🏢 Chapter Organization**: Geographic organization with postal code matching
- **🤝 Volunteer Coordination**: Team management with expense tracking
- **💰 Financial Integration**: ERPNext Sales Invoice integration with SEPA direct debit
- **🧾 eBoekhouden Integration**: Complete Dutch accounting system synchronization
- **📱 Portal Systems**: Member and volunteer self-service portals
- **📈 Analytics & Reporting**: Business intelligence and compliance reporting
- **🎨 Brand Management**: Customizable theming and portal appearance
- **🇳🇱 Dutch Compliance**: ANBI, GDPR, and Belastingdienst reporting capabilities

## ⚙️ System Requirements

### 💻 Minimum Requirements
- **Operating System**: Ubuntu 20.04+ LTS, Debian 11+, CentOS Stream 8+, or RHEL 8+
- **RAM**: 8GB minimum, 16GB recommended for production
- **Storage**: 50GB minimum, 100GB+ recommended for production with eBoekhouden integration
- **CPU**: 4 cores minimum, 8+ cores recommended for production
- **Network**: Stable internet connection (required for eBoekhouden API and email services)

### 🏭 Production Requirements
- **RAM**: 32GB recommended for large organizations (5000+ members)
- **Storage**: SSD storage with 200GB+ for optimal performance
- **CPU**: 16+ cores for heavy financial integration workloads
- **Backup**: Automated backup solution with off-site storage
- **Monitoring**: System monitoring and alerting capabilities

### 🔧 Software Dependencies

#### Core Framework Dependencies
- **Python**: 3.10+ (Python 3.11+ recommended)
- **Node.js**: 18.x LTS or 20.x LTS
- **MariaDB**: 10.6+ (10.11+ recommended)
- **Redis**: 6.x+ (7.x recommended)
- **Nginx**: 1.20+ (for production)
- **Supervisor**: 4.x+ (for process management)

#### Development Dependencies
- **Git**: 2.34+ for source control
- **Yarn**: Latest stable for asset building
- **wkhtmltopdf**: 0.12.6+ for PDF generation
- **ImageMagick**: For image processing

## 📋 Prerequisites

### 🎯 Required Frappe Framework Apps

The Verenigingen app has specific dependencies that must be installed in order:

#### Core Framework Apps
1. **Frappe Framework** v15.x (latest stable)
2. **ERPNext** v15.x (latest stable - provides accounting foundation)
3. **Payments App** (latest stable - essential for payment processing)

#### Essential Additional Apps
4. **HRMS App** (v15.x - required for employee and volunteer management)
5. **Insights App** (optional but recommended - for advanced analytics)

### 🌐 External Service Prerequisites

#### Required Services
- **Email Service**:
  - SMTP server (Gmail, SendGrid, Mailgun, or corporate SMTP)
  - Domain authentication (SPF, DKIM records) for production
  - Daily sending limits appropriate for your member count

- **eBoekhouden Account** (for Dutch organizations):
  - Active eBoekhouden subscription
  - API access credentials (REST API recommended)
  - Administrative access for account mapping

#### Recommended Services
- **SSL Certificate**: Let's Encrypt or commercial certificate
- **Domain Name**: Dedicated domain for your association
- **Backup Service**: Cloud backup solution (AWS S3, Google Cloud, etc.)
- **Monitoring Service**: Uptime monitoring and alerting

### 🔐 Security Prerequisites

#### System Security
- **Firewall Configuration**: Restrict access to necessary ports only
- **User Management**: Non-root user for Frappe installation
- **SSH Security**: Key-based authentication, disable password login
- **Regular Updates**: Automated security updates for OS packages

#### Application Security
- **Strong Passwords**: Enforce strong password policies
- **Two-Factor Authentication**: Enable 2FA for administrative users
- **Access Logging**: Enable audit logging for sensitive operations
- **Data Encryption**: Encryption at rest and in transit

## 🔧 Installation Steps

### Step 1: System Preparation

#### 🔨 Install System Dependencies

1. **Update System Packages**:
   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt upgrade -y

   # Install essential packages
   sudo apt install -y python3-dev python3-pip python3-venv \
                       nodejs npm yarn redis-server mariadb-server \
                       nginx supervisor git curl wget \
                       wkhtmltopdf xvfb libfontconfig
   ```

2. **Configure MariaDB**:
   ```bash
   # Secure MariaDB installation
   sudo mysql_secure_installation

   # Configure MariaDB for Frappe
   sudo mysql -u root -p -e "SET GLOBAL innodb_file_format=Barracuda;"
   sudo mysql -u root -p -e "SET GLOBAL innodb_file_per_table=1;"
   sudo mysql -u root -p -e "SET GLOBAL innodb_large_prefix=1;"

   # Add to MariaDB config (/etc/mysql/conf.d/frappe.cnf)
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

3. **Setup Frappe User**:
   ```bash
   # Create frappe user
   sudo adduser frappe --home /home/frappe
   sudo usermod -aG sudo frappe

   # Switch to frappe user for remaining installation
   sudo su - frappe
   ```

### Step 2: Install Frappe Bench

#### 📦 Bench Installation

1. **Install Frappe Bench**:
   ```bash
   # Install frappe-bench using pip
   pip3 install frappe-bench

   # Add local bin to PATH (add to ~/.bashrc for persistence)
   export PATH=$PATH:~/.local/bin
   echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc
   ```

2. **Initialize New Bench (Frappe v15)**:
   ```bash
   # Initialize bench with Frappe v15
   bench init --frappe-branch version-15 frappe-bench
   cd frappe-bench

   # Switch to production configuration
   bench config dns_multitenant off
   bench config restart_supervisor_on_update on
   bench config restart_systemd_on_update on
   ```

3. **Create Site**:
   ```bash
   # Create new site (replace with your domain)
   bench new-site your-association.com --admin-password your-secure-password

   # Set as default site
   bench use your-association.com
   ```

### Step 3: Install Required Applications

#### 🎯 Core Application Installation

1. **Install ERPNext**:
   ```bash
   # Get ERPNext v15
   bench get-app --branch version-15 erpnext

   # Install ERPNext on your site
   bench --site your-association.com install-app erpnext
   ```

2. **Install Payments App**:
   ```bash
   # Get Payments app
   bench get-app payments

   # Install Payments app
   bench --site your-association.com install-app payments
   ```

3. **Install HRMS (Essential for Volunteer Management)**:
   ```bash
   # Get HRMS v15
   bench get-app --branch version-15 hrms

   # Install HRMS
   bench --site your-association.com install-app hrms
   ```

4. **Install Insights (Optional - Enhanced Analytics)**:
   ```bash
   # Get Insights app for advanced reporting
   bench get-app insights

   # Install Insights (optional but recommended)
   bench --site your-association.com install-app insights
   ```

### Step 4: Install Verenigingen App

#### 🏢 Primary Application Installation

1. **Get Verenigingen App**:
   ```bash
   # Clone from repository (replace with your repository URL)
   bench get-app verenigingen https://github.com/your-organization/verenigingen.git

   # Alternative: Install from local development
   # bench get-app verenigingen /path/to/local/verenigingen
   ```

2. **Install Application**:
   ```bash
   # Install Verenigingen app
   bench --site your-association.com install-app verenigingen

   # Verify installation completed successfully
   bench --site your-association.com list-apps
   ```

3. **Run Migrations and Build Assets**:
   ```bash
   # Run database migrations
   bench --site your-association.com migrate

   # Build static assets
   bench build --app verenigingen

   # Clear cache to ensure clean start
   bench --site your-association.com clear-cache
   ```

### Step 5: Verification and Initial Access

#### ✅ Installation Verification

1. **Start Development Server**:
   ```bash
   # Start all services
   bench start

   # Access via browser: http://localhost:8000 or http://your-association.com:8000
   ```

2. **Verify System Access**:
   - **Login**: Use Administrator credentials created during site setup
   - **Module Check**: Go to **Desk → Modules** and verify "Verenigingen" appears
   - **App Verification**: Navigate to **Settings → Apps** to confirm all apps are installed
   - **System Health**: Check **Settings → System Settings** for any configuration warnings

3. **Initial System Check**:
   ```bash
   # Run system diagnostics
   bench --site your-association.com doctor

   # Check installed apps and versions
   bench --site your-association.com list-apps --verbose

   # Verify database connectivity
   bench --site your-association.com mariadb --execute "SHOW TABLES LIKE 'tab%';"
   ```

#### 🔧 Post-Installation Fixes

1. **Fix Permissions** (if needed):
   ```bash
   # Fix file permissions
   sudo chown -R frappe:frappe /home/frappe/frappe-bench
   chmod -R 755 /home/frappe/frappe-bench
   ```

2. **Restart Services**:
   ```bash
   # Restart bench processes
   bench restart

   # Alternative: Restart individual services
   bench restart-supervisor
   bench restart-nginx  # if nginx is managed by bench
   ```

## 🎛️ Initial Configuration

### Step 1: Company and Organization Setup

#### 🏢 Company Configuration

1. **Configure Company Details**:
   ```bash
   # Navigate to: Accounting → Company
   ```
   - **Company Name**: Enter your association's legal name
   - **Abbreviation**: Short code for your organization (e.g., "VNV")
   - **Default Currency**: EUR for Dutch organizations
   - **Country**: Netherlands
   - **Tax ID**: KvK number or other tax identifier
   - **Address**: Complete legal address including postal code

2. **Fiscal Year Setup**:
   ```bash
   # Navigate to: Accounting → Fiscal Year
   ```
   - **Year Start Date**: January 1 (standard for Dutch organizations)
   - **Year End Date**: December 31
   - **Year Name**: Clear naming convention (e.g., "2024-2025")

3. **Chart of Accounts Configuration**:
   ```bash
   # Navigate to: Accounting → Chart of Accounts
   ```
   - Use the default ERPNext chart or customize for your needs
   - Ensure accounts are set up for eBoekhouden integration
   - Create accounts for membership fees, donations, expenses

#### 🌐 Global Settings Configuration

1. **System Settings**:
   ```bash
   # Navigate to: Settings → System Settings
   ```
   - **Country**: Netherlands
   - **Time Zone**: Europe/Amsterdam
   - **Date Format**: dd-mm-yyyy (Dutch standard)
   - **Number Format**: #.###,## (European format)
   - **Float Precision**: 2 (for currency)

2. **Website Settings**:
   ```bash
   # Navigate to: Website → Website Settings
   ```
   - **Website Title**: Your association name
   - **Title Prefix**: Prefix for page titles
   - **Footer Items**: Add relevant footer links
   - **Google Analytics**: Configure if using analytics

### Step 2: User Management and Security

#### 👥 User Account Setup

1. **Create Administrative Users**:
   ```bash
   # Navigate to: Users and Permissions → User
   ```
   - **Board Members**: Users with administrative access
   - **Coordinators**: Users with operational access
   - **Volunteers**: Users with limited access to volunteer portal

2. **Configure User Roles Automatically**:
   ```bash
   # CLI-friendly method (recommended for installation)
   bench --site your-association.com execute verenigingen.setup.role_profile_setup.setup_role_profiles_cli

   # Alternative method
   bench --site your-association.com execute verenigingen.setup.role_profile_setup.setup_role_profiles
   ```

3. **Manual Role Configuration** (if needed):
   ```bash
   # Navigate to: Users and Permissions → Role Profile
   ```
   - **Board Member Profile**: Full system access
   - **Coordinator Profile**: Member and volunteer management
   - **Volunteer Profile**: Limited to volunteer functions
   - **Member Profile**: Self-service portal access only

#### 🔐 Security Configuration

1. **Enable Two-Factor Authentication**:
   ```bash
   # Navigate to: Settings → System Settings → Security
   ```
   - Enable for all administrative users
   - Recommend for coordinators and board members

2. **Configure Password Policies**:
   ```bash
   # Navigate to: Users and Permissions → Password Policy
   ```
   - **Minimum Length**: 12 characters
   - **Require Special Characters**: Yes
   - **Require Numbers**: Yes
   - **Password Expiry**: 90 days for admin users

### Step 3: Communication Setup

#### 📧 Email Configuration

1. **Configure Primary Email Domain**:
   ```bash
   # Navigate to: Settings → Email Domain
   ```
   - **Domain Name**: your-association.org
   - **Email Server**: Your organization's email server
   - **SMTP Settings**: Configure outgoing mail settings

2. **Setup SMTP for Outgoing Emails**:
   ```bash
   # Navigate to: Settings → Email Account
   ```
   - **Email Server**: smtp.your-provider.com (Gmail: smtp.gmail.com)
   - **Port**: 587 (TLS) or 465 (SSL)
   - **Use TLS**: Yes
   - **Login ID**: Your email address
   - **Password**: App-specific password (for Gmail)

3. **Install and Configure Email Templates**:
   ```bash
   # CLI-friendly method (recommended for installation)
   bench --site your-association.com execute verenigingen.api.email_template_manager.create_email_templates_cli

   # Alternative standard method
   bench --site your-association.com execute verenigingen.api.email_template_manager.create_comprehensive_email_templates

   # Verify templates were created
   # Navigate to: Settings → Email Template
   ```

4. **Test Email Configuration**:
   ```bash
   # Send test email to verify configuration
   # Navigate to: Settings → Email Account → Send Test Email
   ```

#### 📱 Notification Setup

1. **Configure System Notifications**:
   ```bash
   # Navigate to: Setup → Notification
   ```
   - Set up notifications for membership applications
   - Configure payment failure notifications
   - Setup volunteer expense approval alerts

### Step 4: Association-Specific Data Setup

#### 👥 Membership Configuration

1. **Create Membership Types**:
   ```bash
   # Navigate to: Verenigingen → Membership Type
   ```
   - **Individual**: Standard individual membership
   - **Student**: Discounted student membership
   - **Senior**: Senior citizen rates
   - **Family**: Family membership options
   - **Corporate**: Organizational memberships

2. **Configure Membership Fees**:
   - Set annual fee amounts for each type
   - Configure payment intervals (annual, quarterly, monthly)
   - Set up discount structures if applicable

#### 🏢 Chapter Organization

1. **Setup Geographic Chapters** (if applicable):
   ```bash
   # Navigate to: Verenigingen → Chapter
   ```
   - **Amsterdam**: Postal codes 1000-1109
   - **Rotterdam**: Postal codes 3000-3199
   - **The Hague**: Postal codes 2490-2599
   - **Utrecht**: Postal codes 3500-3585
   - **Other**: Define additional regional chapters

2. **Configure Chapter Settings**:
   - Assign coordinators to each chapter
   - Set up meeting locations and schedules
   - Configure regional activities and events

#### 💰 Payment Method Configuration

1. **Configure SEPA Direct Debit**:
   ```bash
   # Navigate to: Verenigingen → SEPA Settings
   ```
   - **Creditor ID**: Your organization's SEPA creditor identifier
   - **Bank Account**: Primary organization bank account
   - **Mandate Configuration**: Set up mandate templates
   - **Batch Processing**: Configure automatic batch creation

2. **Setup Online Payment Gateways** (optional):
   ```bash
   # Navigate to: Integrations → Payment Gateway
   ```
   - **iDEAL**: For Dutch online payments
   - **PayPal**: For international donations
   - **Stripe**: For credit card processing

### Step 5: Integration Configuration

#### 🧾 eBoekhouden Integration Setup

1. **Configure eBoekhouden Settings**:
   ```bash
   # Navigate to: Setup → E-Boekhouden Settings
   ```
   - **API URL**: https://secure.e-boekhouden.nl/bh/api.asp
   - **REST API URL**: https://api.e-boekhouden.nl
   - **Username**: Your eBoekhouden username
   - **Security Codes**: Primary and secondary codes
   - **API Token**: REST API token for enhanced access
   - **Default Company**: Map to your ERPNext company

2. **Test eBoekhouden Connectivity**:
   ```bash
   # Test API connection
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator
   ```

3. **Setup Account Mapping**:
   ```bash
   # Create initial account mappings
   # Navigate to: Setup → eBoekhouden Account Mapping
   ```
   - Map eBoekhouden accounts to ERPNext chart of accounts
   - Configure default accounts for common transaction types

#### 📊 Analytics Configuration

1. **Setup Business Intelligence**:
   ```bash
   # Configure Insights app (if installed)
   # Navigate to: Insights → Dashboard
   ```
   - Create membership analytics dashboard
   - Setup financial reporting dashboard
   - Configure volunteer activity tracking

### Step 6: Portal Configuration

#### 🌐 Member Portal Setup

1. **Configure Member Portal Home Page**:
   ```bash
   # Setup member portal homepage
   bench --site your-association.com execute verenigingen.scripts.setup.setup_member_portal_home.main
   ```

2. **Configure Portal Settings**:
   ```bash
   # Navigate to: Website → Portal Settings
   ```
   - **Default Role**: Member (for new portal users)
   - **Default Home Page**: /member/dashboard
   - **Menu Items**: Configure navigation for members

#### 🤝 Volunteer Portal Setup

1. **Setup Volunteer Portal Pages**:
   ```bash
   # Configure volunteer portal
   # Navigate to: Verenigingen → Volunteer Settings
   ```
   - Enable expense submission features
   - Configure team assignment workflows
   - Setup activity tracking

2. **Configure Volunteer Teams**:
   ```bash
   # Navigate to: Verenigingen → Volunteer Team
   ```
   - Create organizational teams
   - Assign team leaders and coordinators
   - Configure team-specific permissions

## 🔄 Post-Installation Setup

### Step 7: Brand and Appearance Configuration

#### 🎨 Brand Management Setup

1. **Configure Organization Branding**:
   ```bash
   # Access brand management (System Manager role required)
   # Navigate to: /brand_management
   ```
   - **Primary Color**: Set your organization's primary brand color
   - **Secondary Color**: Complementary color for accents
   - **Logo Upload**: Upload organization logo and favicon
   - **Portal Theming**: Configure member and volunteer portal appearance

2. **CSS and Theme Customization**:
   ```bash
   # Generate and apply custom CSS
   # Navigate to: Website → Brand CSS (/brand_css)
   ```
   - Custom CSS variables for consistent theming
   - Portal-specific styling modifications
   - Print format customizations

### Step 8: User Onboarding and Training

#### 📚 Onboarding Configuration

1. **Setup User Onboarding Flows**:
   ```bash
   # Create minimal onboarding setup
   bench --site your-association.com execute verenigingen.scripts.setup.create_minimal_onboarding.main
   ```

2. **Configure Welcome Messages**:
   ```bash
   # Navigate to: Settings → Website Settings → Onboarding
   ```
   - Member welcome email sequences
   - Volunteer orientation materials
   - Board member training resources

3. **Setup Help Documentation**:
   ```bash
   # Create user documentation shortcuts
   # Navigate to: Help → Documentation
   ```
   - Link to user manuals and guides
   - Video tutorials and walkthroughs
   - FAQ and troubleshooting resources

### Step 9: Testing and Validation

#### 🧪 Development Testing (Non-Production Only)

1. **Generate Test Data**:
   ```bash
   # Create test members for system validation
   bench --site your-association.com execute verenigingen.api.generate_test_members.create_test_members --args '{"count": 25}'

   # Create test applications
   bench --site your-association.com execute verenigingen.api.generate_test_applications.create_test_applications --args '{"count": 10}'

   # Generate test volunteer data
   bench --site your-association.com execute verenigingen.api.generate_test_volunteers.create_test_volunteers --args '{"count": 15}'
   ```

2. **Run Comprehensive System Tests**:
   ```bash
   # Run smoke tests to verify basic functionality
   cd /home/frappe/frappe-bench/apps/verenigingen
   python verenigingen/tests/test_runner.py smoke

   # Run core functionality tests
   python scripts/testing/runners/run_volunteer_portal_tests.py --suite core

   # Run comprehensive regression tests
   python scripts/testing/runners/regression_test_runner.py

   # Test eBoekhouden integration (if configured)
   python scripts/testing/integration/test_eboekhouden_integration.py
   ```

#### ✅ Production Validation

1. **System Health Checks**:
   ```bash
   # Run system diagnostics
   bench --site your-association.com doctor

   # Check system configuration
   bench --site your-association.com check-server-status

   # Validate database integrity
   bench --site your-association.com mariadb --execute "CHECK TABLE tabMember, tabVolunteer, tabChapter;"
   ```

2. **Integration Testing**:
   ```bash
   # Test email functionality
   bench --site your-association.com execute verenigingen.api.email_test.send_test_email --args '{"recipient": "admin@your-association.com"}'

   # Test SEPA mandate creation (if configured)
   bench --site your-association.com execute verenigingen.api.sepa_test.test_mandate_creation

   # Test eBoekhouden connectivity (if configured)
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator
   ```

## 🌐 Production Deployment

### Step 10: Production Environment Setup

#### 🔧 Production Configuration

1. **Configure Production Mode**:
   ```bash
   # Enable production settings
   bench --site your-association.com set-config developer_mode 0
   bench --site your-association.com set-config allow_tests 0
   bench --site your-association.com set-config server_script_enabled 0

   # Setup production services
   sudo bench setup production --user frappe
   ```

2. **Configure Process Management**:
   ```bash
   # Setup Supervisor for process management
   sudo bench setup supervisor
   sudo supervisorctl reread
   sudo supervisorctl update

   # Setup Redis for background jobs
   sudo bench setup redis
   ```

3. **Configure Web Server**:
   ```bash
   # Setup Nginx for web serving
   sudo bench setup nginx

   # Enable and start nginx
   sudo systemctl enable nginx
   sudo systemctl start nginx

   # Test nginx configuration
   sudo nginx -t
   ```

#### 🔒 SSL and Security Setup

1. **Install SSL Certificate**:
   ```bash
   # Option 1: Let's Encrypt (Free, Automated)
   sudo bench setup lets-encrypt your-association.com

   # Option 2: Custom SSL Certificate
   # Copy certificates to /etc/ssl/certs/ and /etc/ssl/private/
   # Update nginx configuration manually
   ```

2. **Configure Security Headers**:
   ```bash
   # Add security headers to nginx configuration
   # Edit: /etc/nginx/conf.d/frappe.conf
   ```
   ```nginx
   # Add to server block
   add_header X-Frame-Options "SAMEORIGIN" always;
   add_header X-Content-Type-Options "nosniff" always;
   add_header X-XSS-Protection "1; mode=block" always;
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
   ```

3. **Setup Firewall**:
   ```bash
   # Configure UFW firewall
   sudo ufw enable
   sudo ufw allow ssh
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw reload
   ```

#### 📊 Monitoring and Logging

1. **Configure System Monitoring**:
   ```bash
   # Setup log rotation
   sudo tee /etc/logrotate.d/frappe > /dev/null <<EOF
   /home/frappe/frappe-bench/logs/*.log {
       daily
       missingok
       rotate 52
       compress
       delaycompress
       notifempty
       create 644 frappe frappe
   }
   EOF
   ```

2. **Setup Performance Monitoring**:
   ```bash
   # Configure Frappe monitoring
   bench --site your-association.com enable-scheduler

   # Setup background job monitoring
   bench setup systemd
   sudo systemctl enable frappe-bench-frappe-web.service
   sudo systemctl enable frappe-bench-frappe-schedule.service
   sudo systemctl enable frappe-bench-frappe-short-worker.service
   sudo systemctl enable frappe-bench-frappe-long-worker.service
   ```

#### 💾 Backup Configuration

1. **Setup Automated Backups**:
   ```bash
   # Configure automatic daily backups
   bench --site your-association.com set-config backup_count 7
   bench --site your-association.com enable-scheduler

   # Setup cron for automated backups
   crontab -e
   # Add: 0 2 * * * cd /home/frappe/frappe-bench && bench --site your-association.com backup --with-files
   ```

2. **Configure Offsite Backup**:
   ```bash
   # Example: AWS S3 backup script
   sudo tee /home/frappe/backup_to_s3.sh > /dev/null <<'EOF'
   #!/bin/bash
   SITE="your-association.com"
   BACKUP_DIR="/home/frappe/frappe-bench/sites/$SITE/private/backups"
   S3_BUCKET="your-backup-bucket"

   # Upload latest backups to S3
   aws s3 sync $BACKUP_DIR s3://$S3_BUCKET/daily-backups/

   # Clean up local backups older than 7 days
   find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
   find $BACKUP_DIR -name "*-files.tar" -mtime +7 -delete
   EOF

   chmod +x /home/frappe/backup_to_s3.sh

   # Add to cron for daily execution
   # 0 3 * * * /home/frappe/backup_to_s3.sh
   ```

### Step 11: Performance Optimization

#### ⚡ Database Optimization

1. **Configure MariaDB for Production**:
   ```bash
   # Edit MariaDB configuration
   sudo nano /etc/mysql/conf.d/frappe-production.cnf
   ```
   ```ini
   [mysqld]
   # Performance settings
   innodb_buffer_pool_size = 1G
   innodb_log_file_size = 256M
   innodb_flush_log_at_trx_commit = 2
   innodb_file_per_table = 1

   # Connection settings
   max_connections = 200
   query_cache_size = 128M
   query_cache_type = 1

   # Logging
   slow_query_log = 1
   slow_query_log_file = /var/log/mysql/slow.log
   long_query_time = 2
   ```

2. **Optimize Database Indexes**:
   ```bash
   # Run database optimization
   bench --site your-association.com mariadb --execute "OPTIMIZE TABLE tabMember, tabVolunteer, tabChapter, tabMembership;"

   # Analyze tables for query optimization
   bench --site your-association.com mariadb --execute "ANALYZE TABLE tabMember, tabVolunteer, tabChapter;"
   ```

#### 🚀 Application Performance

1. **Configure Redis for Caching**:
   ```bash
   # Configure Redis for better performance
   sudo nano /etc/redis/redis.conf
   # Set: maxmemory 512mb
   # Set: maxmemory-policy allkeys-lru

   sudo systemctl restart redis
   ```

2. **Optimize Static Asset Serving**:
   ```bash
   # Build and compress assets
   bench build --app verenigingen
   bench --site your-association.com migrate

   # Clear cache
   bench --site your-association.com clear-cache
   bench --site your-association.com clear-website-cache
   ```

## 📊 Integration Setup

### Step 12: Advanced Integration Configuration

#### 🧾 eBoekhouden Integration (Dutch Organizations)

1. **Pre-Migration Setup**:
   ```bash
   # Test eBoekhouden API connectivity
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator

   # Validate account mappings
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_full_migration.analyze_missing_ledger_mappings
   ```

2. **Complete Data Migration**:
   ```bash
   # Start full eBoekhouden migration (production-ready system)
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_full_migration.start_full_rest_import --args '{"migration_name": "Initial Migration 2025"}'

   # Monitor migration progress
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_full_migration.get_migration_status
   ```

3. **Post-Migration Validation**:
   ```bash
   # Verify balance accuracy
   bench --site your-association.com execute verenigingen.api.eboekhouden_account_manager.system_health_check

   # Test opening balance import
   bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_full_migration.test_opening_balance_import
   ```

#### 💳 Payment Gateway Integration

1. **iDEAL Configuration** (Dutch online payments):
   ```bash
   # Navigate to: Integrations → Payment Gateway → iDEAL
   ```
   - Configure merchant credentials
   - Set up webhook URLs for payment confirmation
   - Test payment flow with small amounts

2. **SEPA Direct Debit Advanced Setup**:
   ```bash
   # Navigate to: Verenigingen → SEPA Batch Management
   ```
   - Configure automated batch creation schedules
   - Setup mandate collection workflows
   - Configure payment failure handling

## 🧪 Testing and Validation

### Step 13: Comprehensive System Testing

#### 🔍 Functional Testing

1. **Core Functionality Tests**:
   ```bash
   # Test member lifecycle
   bench --site your-association.com execute verenigingen.api.test_member_lifecycle.run_comprehensive_test

   # Test volunteer management
   bench --site your-association.com execute verenigingen.api.test_volunteer_system.run_full_test_suite

   # Test payment processing
   bench --site your-association.com execute verenigingen.api.test_payment_system.test_sepa_workflow
   ```

2. **Integration Testing**:
   ```bash
   # Test email system
   cd /home/frappe/frappe-bench/apps/verenigingen
   python scripts/testing/integration/test_email_integration.py

   # Test eBoekhouden integration (if configured)
   python scripts/testing/integration/test_eboekhouden_integration.py

   # Test portal functionality
   python scripts/testing/integration/test_portal_functionality.py
   ```

#### 🛡️ Security and Performance Testing

1. **Security Validation**:
   ```bash
   # Run security tests (from app directory)
   cd /home/frappe/frappe-bench/apps/verenigingen
   python verenigingen/tests/test_security_comprehensive.py

   # Test permission systems
   python scripts/testing/unit/permissions/test_permission_system.py

   # Validate GDPR compliance
   python scripts/testing/unit/compliance/test_gdpr_compliance.py
   ```

2. **Performance Testing**:
   ```bash
   # Test database performance (from app directory)
   cd /home/frappe/frappe-bench/apps/verenigingen
   python verenigingen/tests/test_performance_edge_cases.py

   # Test system load handling
   python scripts/testing/integration/test_system_performance.py
   ```

## 🔧 Troubleshooting

### Common Installation Issues

#### 🚨 Installation and Setup Problems

**Issue**: Frappe Bench installation fails with permission errors
```bash
# Solution: Ensure proper user setup and permissions
sudo adduser frappe --home /home/frappe
sudo usermod -aG sudo frappe
sudo chown -R frappe:frappe /home/frappe
```

**Issue**: App installation fails with dependency conflicts
```bash
# Solution: Clean installation approach
bench --site your-association.com uninstall-app verenigingen
bench remove-app verenigingen
bench get-app verenigingen https://github.com/your-org/verenigingen.git
bench --site your-association.com install-app verenigingen --force
```

**Issue**: Migration errors during app installation
```bash
# Solution: Reset database and migrate step by step
bench --site your-association.com migrate --reset-permissions
bench --site your-association.com rebuild-global-search
bench --site your-association.com clear-cache
```

#### 🗄️ Database and Performance Issues

**Issue**: MariaDB connection timeouts
```bash
# Solution: Optimize MariaDB configuration
sudo nano /etc/mysql/conf.d/frappe.cnf
# Add: wait_timeout = 28800
# Add: interactive_timeout = 28800
sudo systemctl restart mariadb
```

**Issue**: Slow query performance
```bash
# Solution: Optimize database and add indexes
bench --site your-association.com mariadb --execute "SHOW PROCESSLIST;"
bench --site your-association.com mariadb --execute "ANALYZE TABLE tabMember, tabVolunteer, tabChapter;"
```

**Issue**: High memory usage
```bash
# Solution: Optimize Redis and Frappe configuration
# Edit Redis config: sudo nano /etc/redis/redis.conf
# Set: maxmemory 1gb
# Set: maxmemory-policy allkeys-lru
sudo systemctl restart redis
```

#### 📧 Communication and Integration Issues

**Issue**: Emails not sending
```bash
# Solution: Debug email configuration step by step
bench --site your-association.com console
# In console:
import frappe
frappe.sendmail(recipients=['test@example.com'], subject='Test', message='Test message')
```

**Issue**: eBoekhouden API connection failures
```bash
# Solution: Validate credentials and connectivity
bench --site your-association.com execute verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator

# Check API settings
# Navigate to: Setup → E-Boekhouden Settings
# Verify all credentials and URLs
```

**Issue**: SEPA mandate creation errors
```bash
# Solution: Validate IBAN and mandate settings
bench --site your-association.com execute verenigingen.utils.iban_validator.validate_iban --args '{"iban": "NL91ABNA0417164300"}'

# Check SEPA settings
# Navigate to: Verenigingen → SEPA Settings
```

#### 🌐 Portal and Frontend Issues

**Issue**: Portal pages not loading correctly
```bash
# Solution: Rebuild assets and clear cache
bench build --app verenigingen
bench --site your-association.com clear-cache
bench --site your-association.com clear-website-cache
```

**Issue**: Brand CSS not applying
```bash
# Solution: Regenerate brand CSS and verify configuration
# Navigate to: /brand_management
# Check brand settings and regenerate CSS
bench --site your-association.com execute verenigingen.templates.pages.brand_css.regenerate_brand_css
```

### 🔍 Diagnostic Tools

#### System Health Checks

1. **Comprehensive System Diagnostics**:
   ```bash
   # Run full system diagnostics
   bench --site your-association.com doctor

   # Check service status
   sudo systemctl status nginx mariadb redis-server supervisor

   # Monitor system resources
   htop
   df -h
   free -h
   ```

2. **Application-Specific Diagnostics**:
   ```bash
   # Check Verenigingen app status
   bench --site your-association.com list-apps --verbose

   # Validate configuration
   bench --site your-association.com execute verenigingen.api.system_health.run_comprehensive_health_check

   # Check background jobs
   bench --site your-association.com doctor-jobs
   ```

#### 📊 Log Analysis

1. **System Log Monitoring**:
   ```bash
   # Monitor Frappe logs
   tail -f /home/frappe/frappe-bench/logs/web.log
   tail -f /home/frappe/frappe-bench/logs/worker.log
   tail -f /home/frappe/frappe-bench/logs/schedule.log

   # Monitor system logs
   sudo tail -f /var/log/nginx/error.log
   sudo tail -f /var/log/mysql/error.log
   ```

2. **Error Log Analysis**:
   ```bash
   # Search for specific errors
   grep -r "ERROR" /home/frappe/frappe-bench/logs/
   grep -r "Exception" /home/frappe/frappe-bench/logs/

   # Check for permission issues
   grep -r "Permission denied" /var/log/
   ```

### 🆘 Getting Help and Support

#### Documentation and Resources

1. **Official Documentation**:
   - **Installation Guide**: This document
   - **User Manual**: `/docs/user-manual/`
   - **Administrator Guide**: `/docs/ADMIN_GUIDE.md`
   - **API Documentation**: `/docs/API_DOCUMENTATION.md`
   - **eBoekhouden Integration**: `/docs/features/eboekhouden-integration.md`

2. **Development Resources**:
   - **CLAUDE.md**: Technical development guidance
   - **Testing Documentation**: `/docs/testing/`
   - **Integration Examples**: `/docs/examples/`

#### Community and Support

1. **Community Support**:
   - **GitHub Repository**: Post issues and feature requests
   - **Frappe Community**: Frappe framework support and discussions
   - **ERPNext Community**: ERPNext-specific questions and solutions

2. **Professional Support**:
   - **Development Team**: Contact for custom development and integration
   - **Hosting Providers**: Managed hosting solutions for Frappe/ERPNext
   - **Local Partners**: Netherlands-based implementation partners

## ✅ Verification Checklist

### Post-Installation Verification

#### 🎯 Core System Functionality

- [ ] **System Access**: Login successful with Administrator account
- [ ] **Module Loading**: Verenigingen module appears in module list
- [ ] **Database Connectivity**: All tables created and accessible
- [ ] **App Installation**: All required apps installed and listed in apps page
- [ ] **Migrations**: All database migrations completed successfully

#### 👥 User Management and Security

- [ ] **User Creation**: Able to create and configure user accounts
- [ ] **Role Profiles**: Role profiles deployed and functional
- [ ] **Permission System**: Users can only access permitted functions
- [ ] **Two-Factor Authentication**: 2FA working for administrative users
- [ ] **Password Policies**: Strong password requirements enforced

#### 📧 Communication Systems

- [ ] **Email Configuration**: SMTP settings configured and tested
- [ ] **Email Templates**: All email templates created and functional
- [ ] **Test Emails**: Test emails sending successfully
- [ ] **Notification System**: System notifications working properly
- [ ] **Portal Communication**: Member and volunteer portals accessible

#### 💰 Financial and Payment Systems

- [ ] **Company Setup**: Company and fiscal year configured
- [ ] **Chart of Accounts**: Accounting structure set up properly
- [ ] **Payment Methods**: SEPA and other payment methods configured
- [ ] **SEPA Mandates**: SEPA mandate creation working (if applicable)
- [ ] **eBoekhouden Integration**: API connectivity and data sync working (if applicable)

#### 🏢 Association Management

- [ ] **Membership Types**: Membership categories created and configured
- [ ] **Chapter Management**: Geographic chapters set up (if applicable)
- [ ] **Volunteer System**: Volunteer teams and assignments functional
- [ ] **Portal Access**: Member and volunteer portals accessible and functional
- [ ] **Brand Management**: Organization branding configured and applied

#### 🧪 Testing and Validation

- [ ] **Smoke Tests**: Basic functionality tests pass
- [ ] **Integration Tests**: All integration tests pass
- [ ] **Security Tests**: Security validation tests pass
- [ ] **Performance Tests**: System performance within acceptable limits
- [ ] **Production Readiness**: System ready for production use

### 🏭 Production Deployment Checklist

#### 🔒 Security and SSL

- [ ] **SSL Certificate**: SSL/TLS certificate installed and working
- [ ] **Security Headers**: HTTP security headers configured
- [ ] **Firewall Configuration**: Only necessary ports open
- [ ] **Access Controls**: Administrative access properly restricted
- [ ] **Audit Logging**: Security events logged and monitored

#### ⚡ Performance and Optimization

- [ ] **Database Optimization**: MariaDB optimized for production workload
- [ ] **Redis Configuration**: Redis caching configured and working
- [ ] **Asset Optimization**: Static assets built and compressed
- [ ] **CDN Setup**: Content delivery network configured (if applicable)
- [ ] **Monitoring Setup**: System monitoring and alerting active

#### 💾 Backup and Recovery

- [ ] **Automated Backups**: Daily automated backups configured
- [ ] **Offsite Backup**: Backups stored in multiple locations
- [ ] **Backup Testing**: Backup restoration tested successfully
- [ ] **Disaster Recovery**: Recovery procedures documented and tested
- [ ] **Data Retention**: Backup retention policies implemented

## 🚀 Next Steps

### Immediate Actions After Installation

1. **📚 User Training and Documentation**:
   - Train board members and coordinators on system usage
   - Create organization-specific user guides
   - Setup help desk procedures for user support
   - Document custom configurations and modifications

2. **📊 Data Migration and Import**:
   - Import existing member database (if applicable)
   - Migrate historical financial data via eBoekhouden integration
   - Import volunteer and chapter data
   - Validate all imported data for accuracy

3. **🔄 Process Implementation**:
   - Implement membership application and approval workflows
   - Setup payment collection and SEPA mandate processes
   - Configure volunteer recruitment and management procedures
   - Establish reporting and analytics routines

### Long-term Success Strategies

1. **📈 Continuous Improvement**:
   - Regularly review system performance and usage
   - Gather user feedback and implement improvements
   - Stay updated with Verenigingen app updates and new features
   - Monitor industry best practices and compliance requirements

2. **🛡️ Maintenance and Support**:
   - Schedule regular system maintenance windows
   - Keep all software components updated and patched
   - Monitor system logs and performance metrics
   - Maintain documentation and procedures

3. **🚀 Growth and Scaling**:
   - Plan for increased membership and data volume
   - Consider additional integrations and automation
   - Evaluate advanced features like analytics and business intelligence
   - Assess opportunities for process optimization

---

**🎉 Congratulations!** You have successfully installed and configured the Verenigingen comprehensive association management system. Your organization now has a powerful platform for managing members, volunteers, finances, and operations with Dutch compliance and eBoekhouden integration.

For ongoing support and detailed usage instructions, refer to the complete documentation in the `/docs/` directory and the [User Manual](user-manual/) for role-specific guidance.
