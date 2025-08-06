# 💾 Backup & Recovery Guide

Complete guide for data protection, backup strategies, and disaster recovery procedures for Verenigingen installations.

## 📋 Table of Contents
- [🎯 Overview](#-overview)
- [🔄 Backup Strategies](#-backup-strategies)
- [⚙️ Automated Backup Setup](#️-automated-backup-setup)
- [🗄️ Manual Backup Procedures](#️-manual-backup-procedures)
- [🔧 Recovery Procedures](#-recovery-procedures)
- [☁️ Cloud Backup Solutions](#️-cloud-backup-solutions)
- [🧪 Testing and Validation](#-testing-and-validation)
- [🚨 Disaster Recovery](#-disaster-recovery)
- [📋 Compliance and Retention](#-compliance-and-retention)

## 🎯 Overview

Data protection is critical for association management systems. This guide covers comprehensive backup and recovery strategies for Verenigingen installations, ensuring business continuity and regulatory compliance.

### 💡 Backup Principles
- **3-2-1 Rule**: 3 copies of data, 2 different media types, 1 offsite location
- **Regular Testing**: Backup integrity and recovery procedures validated monthly
- **Documentation**: All procedures documented and staff trained
- **Compliance**: GDPR and Dutch data protection requirements met

### ⏱️ Recovery Time Objectives (RTO)
- **Critical Services**: < 4 hours
- **Member Portal**: < 2 hours
- **Financial Data**: < 1 hour
- **Communication Systems**: < 30 minutes

## 🔄 Backup Strategies

### 📊 Data Classification

#### 🔴 Critical Data (Daily Backup)
- **Member database** and personal information
- **Financial transactions** and payment history
- **SEPA mandates** and banking information
- **System configurations** and customizations

#### 🟡 Important Data (Weekly Backup)
- **Volunteer records** and assignment history
- **Communication logs** and email templates
- **Analytics data** and reports
- **Chapter organization** data

#### 🟢 Supporting Data (Monthly Backup)
- **System logs** and audit trails
- **Temporary files** and cache data
- **Development and testing** environments

### 📅 Backup Frequency Schedule

| Data Type | Frequency | Retention Period | Storage Location |
|-----------|-----------|------------------|------------------|
| Database | Daily | 90 days | Local + Cloud |
| Files | Daily | 30 days | Local + Cloud |
| System Config | Weekly | 365 days | Local + Cloud |
| Full System | Weekly | 12 weeks | Cloud only |
| Archive | Monthly | 7 years | Cold storage |

## ⚙️ Automated Backup Setup

### 🤖 Frappe Built-in Backup
```bash
# Enable automatic backups
bench --site your-site enable-scheduler

# Configure backup frequency in site_config.json
{
  "backup_frequency": "daily",
  "backup_with_files": true,
  "backup_compress": true,
  "backup_path": "/backups/",
  "backup_retention": 30
}
```

### 📜 Backup Script Setup
Create `/home/frappe/backup_scripts/daily_backup.sh`:

```bash
#!/bin/bash
# Verenigingen Daily Backup Script

# Configuration
SITE_NAME="your-site"
BACKUP_DIR="/backups/$(date +%Y/%m)"
LOG_FILE="/var/log/verenigingen-backup.log"
RETENTION_DAYS=30
CLOUD_BUCKET="verenigingen-backups"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Function to send notifications
send_notification() {
    local status="$1"
    local message="$2"

    # Send email notification
    echo "$message" | mail -s "Backup $status - Verenigingen" admin@your-org.com

    # Log to system
    log_message "$status: $message"
}

# Start backup process
log_message "Starting daily backup for $SITE_NAME"

# 1. Database backup with files
bench --site "$SITE_NAME" backup --with-files --compress
if [ $? -eq 0 ]; then
    log_message "Database backup completed successfully"
else
    send_notification "FAILED" "Database backup failed for $SITE_NAME"
    exit 1
fi

# 2. Move backup to organized directory
LATEST_BACKUP=$(ls -t ~/frappe-bench/sites/$SITE_NAME/private/backups/*.sql.gz | head -n1)
LATEST_FILES=$(ls -t ~/frappe-bench/sites/$SITE_NAME/private/backups/*-files.tar | head -n1)

if [ -f "$LATEST_BACKUP" ] && [ -f "$LATEST_FILES" ]; then
    mv "$LATEST_BACKUP" "$BACKUP_DIR/"
    mv "$LATEST_FILES" "$BACKUP_DIR/"
    log_message "Backup files moved to $BACKUP_DIR"
else
    send_notification "FAILED" "Backup files not found for $SITE_NAME"
    exit 1
fi

# 3. Verify backup integrity
DB_BACKUP="$BACKUP_DIR/$(basename $LATEST_BACKUP)"
if gunzip -t "$DB_BACKUP" 2>/dev/null; then
    log_message "Backup integrity verified"
else
    send_notification "FAILED" "Backup integrity check failed"
    exit 1
fi

# 4. Upload to cloud storage (example with AWS S3)
if command -v aws &> /dev/null; then
    aws s3 sync "$BACKUP_DIR" "s3://$CLOUD_BUCKET/$(date +%Y/%m)/"
    if [ $? -eq 0 ]; then
        log_message "Cloud upload completed"
    else
        send_notification "WARNING" "Cloud upload failed - local backup available"
    fi
fi

# 5. Clean up old backups
find /backups/ -name "*.gz" -type f -mtime +$RETENTION_DAYS -delete
find /backups/ -name "*.tar" -type f -mtime +$RETENTION_DAYS -delete
log_message "Old backups cleaned up (older than $RETENTION_DAYS days)"

# 6. Generate backup report
BACKUP_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
send_notification "SUCCESS" "Daily backup completed. Size: $BACKUP_SIZE, Location: $BACKUP_DIR"

log_message "Daily backup process completed successfully"
```

### ⏰ Cron Configuration
```bash
# Add to crontab (crontab -e)
# Daily backup at 2 AM
0 2 * * * /home/frappe/backup_scripts/daily_backup.sh

# Weekly full system backup at 3 AM Sunday
0 3 * * 0 /home/frappe/backup_scripts/weekly_full_backup.sh

# Monthly archive at 4 AM on 1st of month
0 4 1 * * /home/frappe/backup_scripts/monthly_archive.sh
```

## 🗄️ Manual Backup Procedures

### 📊 Complete System Backup
```bash
# 1. Enable maintenance mode
bench --site your-site set-maintenance-mode on

# 2. Create timestamped backup directory
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p ~/manual-backups/$BACKUP_DATE

# 3. Database backup
bench --site your-site backup --with-files --compress
cp ~/frappe-bench/sites/your-site/private/backups/*.sql.gz ~/manual-backups/$BACKUP_DATE/
cp ~/frappe-bench/sites/your-site/private/backups/*-files.tar ~/manual-backups/$BACKUP_DATE/

# 4. Configuration backup
cp ~/frappe-bench/sites/your-site/site_config.json ~/manual-backups/$BACKUP_DATE/
cp ~/frappe-bench/sites/common_site_config.json ~/manual-backups/$BACKUP_DATE/

# 5. Custom code backup
tar -czf ~/manual-backups/$BACKUP_DATE/custom-code.tar.gz ~/frappe-bench/apps/verenigingen/

# 6. System configuration
cp -r /etc/nginx/sites-available/verenigingen ~/manual-backups/$BACKUP_DATE/
cp -r /etc/supervisor/conf.d/ ~/manual-backups/$BACKUP_DATE/supervisor/

# 7. SSL certificates (if applicable)
cp -r /etc/letsencrypt/ ~/manual-backups/$BACKUP_DATE/ssl/ 2>/dev/null || true

# 8. Create backup manifest
cat > ~/manual-backups/$BACKUP_DATE/backup_manifest.txt << EOF
Backup Created: $(date)
Site: your-site
Frappe Version: $(bench --version)
Verenigingen Version: $(bench --site your-site execute "frappe.get_installed_apps()[0]")
Files Included:
$(ls -la ~/manual-backups/$BACKUP_DATE/)
EOF

# 9. Disable maintenance mode
bench --site your-site set-maintenance-mode off

echo "Manual backup completed: ~/manual-backups/$BACKUP_DATE"
```

### 🎯 Selective Data Backup
```bash
# Member data only
bench --site your-site export-fixtures Member "Member"

# Financial data only
bench --site your-site export-fixtures "Sales Invoice" "Payment Entry" "Direct Debit Batch"

# Volunteer data only
bench --site your-site export-fixtures Volunteer "Volunteer Expense" "Team Assignment"

# System configuration only
bench --site your-site export-fixtures "Verenigingen Settings" "Email Template"
```

## 🔧 Recovery Procedures

### 🚀 Complete System Recovery
```bash
# 1. Prepare clean environment
bench new-site recovery-site.local

# 2. Install required apps
bench --site recovery-site.local install-app erpnext
bench --site recovery-site.local install-app payments
bench --site recovery-site.local install-app verenigingen

# 3. Restore database
bench --site recovery-site.local restore path/to/backup.sql.gz

# 4. Restore files
tar -xf path/to/files-backup.tar -C ~/frappe-bench/sites/recovery-site.local/

# 5. Restore configurations
cp backup/site_config.json ~/frappe-bench/sites/recovery-site.local/
cp backup/common_site_config.json ~/frappe-bench/sites/

# 6. Run migrations and rebuild
bench --site recovery-site.local migrate
bench --site recovery-site.local build

# 7. Verify recovery
bench --site recovery-site.local execute "verenigingen.tests.utils.quick_validation.run_quick_tests()"
```

### 🎯 Selective Data Recovery
```bash
# Recover specific doctype data
bench --site your-site import-doc path/to/member-export.json

# Recover from SQL backup with specific data
gunzip -c backup.sql.gz | mysql -u root -p your_site_db

# Restore individual files
tar -xf files-backup.tar specific/file/path
```

### 🔄 Point-in-Time Recovery
```bash
# Using binary logs (if enabled)
# 1. Restore from last full backup
bench --site your-site restore backup.sql.gz

# 2. Apply binary logs up to specific time
mysqlbinlog --stop-datetime="2025-01-15 14:30:00" binlog.001 | mysql -u root -p your_site_db

# 3. Verify data consistency
bench --site your-site execute "frappe.db.check_database_integrity()"
```

## ☁️ Cloud Backup Solutions

### 📡 AWS S3 Configuration
```bash
# Install AWS CLI
sudo apt-get install awscli

# Configure credentials
aws configure
# AWS Access Key ID: YOUR_ACCESS_KEY
# AWS Secret Access Key: YOUR_SECRET_KEY
# Default region: eu-west-1
# Output format: json

# Create backup bucket
aws s3 mb s3://verenigingen-backups-eu

# Set lifecycle policy
aws s3api put-bucket-lifecycle-configuration --bucket verenigingen-backups-eu --lifecycle-configuration file://lifecycle.json
```

### 🔄 Automated Cloud Sync
```bash
# Add to daily backup script
# Sync with versioning
aws s3 sync /backups/ s3://verenigingen-backups-eu/ --delete --storage-class STANDARD_IA

# Archive old backups to Glacier
aws s3 cp s3://verenigingen-backups-eu/ s3://verenigingen-archive-eu/ --recursive --storage-class GLACIER
```

### 🏢 Alternative Cloud Providers

#### Google Cloud Storage
```bash
# Install gsutil
curl https://sdk.cloud.google.com | bash

# Upload backup
gsutil cp -r /backups/* gs://verenigingen-backups/
```

#### Microsoft Azure
```bash
# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Upload backup
az storage blob upload-batch --account-name verenigingenbackups --destination backups --source /backups/
```

## 🧪 Testing and Validation

### ✅ Backup Integrity Testing
```bash
#!/bin/bash
# backup_test.sh - Monthly backup testing script

# Test database backup integrity
test_db_backup() {
    local backup_file="$1"

    # Test compression integrity
    if gunzip -t "$backup_file" 2>/dev/null; then
        echo "✅ Compression integrity: PASS"
    else
        echo "❌ Compression integrity: FAIL"
        return 1
    fi

    # Test SQL syntax
    if gunzip -c "$backup_file" | head -100 | grep -q "CREATE TABLE"; then
        echo "✅ SQL structure: PASS"
    else
        echo "❌ SQL structure: FAIL"
        return 1
    fi

    return 0
}

# Test file backup integrity
test_file_backup() {
    local backup_file="$1"

    # Test tar integrity
    if tar -tf "$backup_file" > /dev/null 2>&1; then
        echo "✅ File archive integrity: PASS"
    else
        echo "❌ File archive integrity: FAIL"
        return 1
    fi

    return 0
}

# Run tests on latest backups
echo "🧪 Starting backup integrity tests..."
LATEST_DB=$(ls -t /backups/*/*.sql.gz | head -n1)
LATEST_FILES=$(ls -t /backups/*/*.tar | head -n1)

test_db_backup "$LATEST_DB"
test_file_backup "$LATEST_FILES"

echo "🧪 Backup integrity tests completed"
```

### 🔄 Recovery Testing Schedule
```bash
# Monthly recovery test
# 1st Saturday of each month
0 8 1-7 * 6 [ "$(date +\%u)" = 6 ] && /home/frappe/scripts/monthly_recovery_test.sh

# Quarterly full disaster recovery test
# 1st Saturday of January, April, July, October
0 8 1-7 1,4,7,10 6 [ "$(date +\%u)" = 6 ] && /home/frappe/scripts/quarterly_disaster_test.sh
```

## 🚨 Disaster Recovery

### 🔥 Emergency Recovery Plan

#### Immediate Actions (0-1 hour)
1. **Assess Impact**: Determine scope of data loss or system failure
2. **Activate Team**: Contact technical and management teams
3. **Enable Maintenance Mode**: Prevent further data corruption
4. **Secure Backups**: Verify backup availability and integrity

#### Short-term Recovery (1-4 hours)
1. **Prepare Environment**: Set up recovery environment
2. **Restore Critical Data**: Member and financial information first
3. **Restore Core Functions**: Member portal and payment processing
4. **Basic Testing**: Verify critical operations function

#### Full Recovery (4-24 hours)
1. **Complete Restoration**: All data and functionality
2. **Integration Testing**: Verify all systems working
3. **User Acceptance**: Test with key users
4. **Go-Live**: Return to normal operations

### 📞 Emergency Contacts
```yaml
# Store in secure location accessible during emergencies
Technical Lead: +31-XXX-XXXXXX
System Administrator: +31-XXX-XXXXXX
Hosting Provider: support@provider.com
Database Expert: +31-XXX-XXXXXX
Management: +31-XXX-XXXXXX
```

### 🎯 Recovery Priority Matrix
| System Component | Priority | Max Downtime | Recovery Method |
|------------------|----------|--------------|-----------------|
| Member Database | Critical | 1 hour | Hot standby |
| Payment Processing | Critical | 2 hours | Latest backup |
| Member Portal | High | 4 hours | Latest backup |
| Volunteer Portal | Medium | 8 hours | Daily backup |
| Analytics | Low | 24 hours | Weekly backup |

## 📋 Compliance and Retention

### 🇪🇺 GDPR Requirements
- **Data Minimization**: Only backup necessary personal data
- **Purpose Limitation**: Use backups only for recovery purposes
- **Storage Limitation**: Comply with retention schedules
- **Security**: Encrypt all backups containing personal data
- **Accountability**: Document all backup and recovery activities

### 📅 Retention Schedule
```yaml
Personal Data:
  - Active Members: 7 years after membership ends
  - Former Members: 3 years after departure
  - Financial Records: 7 years (Dutch law requirement)
  - Communication Logs: 2 years
  - System Logs: 1 year
  - Backup Archives: Follow data retention rules

Technical Data:
  - Configuration: 10 years
  - Code Backups: Indefinite
  - System Logs: 2 years
  - Performance Data: 5 years
```

### 🔐 Encryption Requirements
```bash
# Encrypt backup files
gpg --cipher-algo AES256 --compress-algo 1 --s2k-digest-algo SHA512 \
    --cert-digest-algo SHA512 --symmetric backup.sql.gz

# Decrypt when needed
gpg --decrypt backup.sql.gz.gpg | gunzip > backup.sql
```

---

## 🎯 Best Practices Summary

### ✅ Daily Actions
- [ ] Monitor backup completion notifications
- [ ] Verify backup file creation and sizes
- [ ] Check disk space on backup storage
- [ ] Review backup logs for errors

### 📅 Weekly Actions
- [ ] Test backup integrity on sample files
- [ ] Verify cloud backup synchronization
- [ ] Clean up old backup files
- [ ] Review backup performance metrics

### 🗓️ Monthly Actions
- [ ] Full backup integrity testing
- [ ] Recovery procedure testing
- [ ] Update backup retention policies
- [ ] Review and update disaster recovery contacts

### 📊 Quarterly Actions
- [ ] Complete disaster recovery drill
- [ ] Review and update backup strategies
- [ ] Audit compliance with retention policies
- [ ] Update backup documentation

---

**Remember**: Backups are only as good as your ability to restore from them. Regular testing ensures your data protection strategy works when you need it most.
