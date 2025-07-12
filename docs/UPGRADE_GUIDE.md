# 🔄 Upgrade Guide

This guide covers upgrading your Verenigingen installation to the latest version safely and efficiently.

## 📋 Table of Contents
- [🎯 Overview](#-overview)
- [⚠️ Pre-Upgrade Requirements](#️-pre-upgrade-requirements)
- [📦 Backup Procedures](#-backup-procedures)
- [🔧 Upgrade Steps](#-upgrade-steps)
- [🧪 Post-Upgrade Verification](#-post-upgrade-verification)
- [🔄 Rollback Procedures](#-rollback-procedures)
- [🚨 Troubleshooting](#-troubleshooting)
- [📞 Getting Help](#-getting-help)

## 🎯 Overview

The Verenigingen app follows semantic versioning and provides structured upgrade paths to ensure data integrity and system stability during updates.

### 🏷️ Version Strategy
- **Major versions** (x.0.0): Breaking changes requiring migration
- **Minor versions** (x.y.0): New features, backward compatible
- **Patch versions** (x.y.z): Bug fixes and security updates

### ⏱️ Upgrade Schedule
- **Security patches**: Apply immediately
- **Minor updates**: Apply monthly during maintenance windows
- **Major updates**: Plan quarterly with thorough testing

## ⚠️ Pre-Upgrade Requirements

### ✅ Compatibility Check
```bash
# Check current versions
bench version
bench --site your-site execute "import frappe; print(frappe.__version__)"

# Check Verenigingen version
bench --site your-site execute "frappe.get_installed_apps()"
```

### 📋 Pre-Upgrade Checklist
- [ ] **System backup** completed and verified
- [ ] **Database backup** completed and tested
- [ ] **Maintenance window** scheduled (recommend 4-hour window)
- [ ] **User notification** sent about system downtime
- [ ] **Staging environment** tested with upgrade
- [ ] **Dependencies** verified (ERPNext, Payments, HRMS, CRM)
- [ ] **Custom modifications** documented and backed up
- [ ] **Integration endpoints** tested and documented

### 🔍 System Health Check
```bash
# Verify system status
bench doctor
bench --site your-site migrate --dry-run
bench --site your-site execute "frappe.db.check_database_integrity()"
```

## 📦 Backup Procedures

### 🗄️ Complete System Backup
```bash
# Stop services
sudo supervisorctl stop all

# Create backup directory
mkdir -p ~/backups/$(date +%Y%m%d_%H%M%S)
cd ~/backups/$(date +%Y%m%d_%H%M%S)

# Database backup
bench --site your-site backup --with-files

# Configuration backup
cp -r ~/frappe-bench/sites/your-site/site_config.json ./
cp -r ~/frappe-bench/sites/common_site_config.json ./

# Custom files backup
tar -czf custom_files.tar.gz ~/frappe-bench/apps/verenigingen/

# Verify backup integrity
bench --site your-site restore-backup database.sql.gz --verify-only
```

### 🧪 Test Backup Recovery
```bash
# Create test site from backup
bench new-site test-site.local
bench --site test-site.local restore-backup database.sql.gz
bench --site test-site.local migrate
```

## 🔧 Upgrade Steps

### 📥 Method 1: Standard Upgrade
```bash
# 1. Enable maintenance mode
bench --site your-site set-maintenance-mode on

# 2. Update Verenigingen app
cd ~/frappe-bench/apps/verenigingen
git fetch origin
git checkout main
git pull origin main

# 3. Update dependencies if needed
bench update --requirements

# 4. Run migrations
bench --site your-site migrate

# 5. Rebuild assets
bench build --app verenigingen

# 6. Clear cache
bench --site your-site clear-cache

# 7. Restart services
bench restart

# 8. Disable maintenance mode
bench --site your-site set-maintenance-mode off
```

### 🔄 Method 2: Zero-Downtime Upgrade (Production)
```bash
# 1. Create staging environment
bench clone-site your-site staging-site

# 2. Test upgrade on staging
bench --site staging-site migrate
bench --site staging-site execute "verenigingen.utils.upgrade_validation.run_tests()"

# 3. Schedule production upgrade during maintenance window
# Follow Method 1 during scheduled maintenance
```

### 🏗️ Major Version Upgrades
For major version upgrades (e.g., v1.x to v2.x):

```bash
# 1. Review breaking changes
curl -s https://raw.githubusercontent.com/0spinboson/verenigingen/main/CHANGELOG.md

# 2. Run pre-upgrade checks
bench --site your-site execute "verenigingen.utils.upgrade_validator.check_major_upgrade()"

# 3. Apply data migrations
bench --site your-site execute "verenigingen.patches.major_upgrade.run_data_migration()"

# 4. Update custom code if needed
# Review and update any custom modifications

# 5. Complete standard upgrade process
```

## 🧪 Post-Upgrade Verification

### ✅ System Verification Checklist
```bash
# Test core functionality
bench --site your-site execute "verenigingen.tests.utils.quick_validation.run_quick_tests()"

# Verify database integrity
bench --site your-site execute "frappe.db.check_database_integrity()"

# Test integrations
bench --site your-site execute "verenigingen.utils.integration_tests.test_all_integrations()"

# Performance check
bench --site your-site execute "verenigingen.utils.performance_monitor.run_health_check()"
```

### 🔍 Functional Testing
- [ ] **Member login** and portal access
- [ ] **Payment processing** and SEPA functionality
- [ ] **eBoekhouden integration** and data sync
- [ ] **Volunteer portal** and expense submission
- [ ] **Admin dashboard** and reporting
- [ ] **Email notifications** and templates
- [ ] **API endpoints** and external integrations

### 📊 Performance Validation
```bash
# Check response times
bench --site your-site execute "verenigingen.utils.performance_monitor.benchmark_critical_operations()"

# Verify background jobs
bench --site your-site execute "frappe.monitor.check_scheduler_status()"

# Database optimization
bench --site your-site execute "frappe.db.optimize_tables()"
```

## 🔄 Rollback Procedures

### 🚨 Emergency Rollback
If issues are encountered after upgrade:

```bash
# 1. Enable maintenance mode immediately
bench --site your-site set-maintenance-mode on

# 2. Stop services
sudo supervisorctl stop all

# 3. Restore from backup
bench --site your-site restore-backup path/to/backup/database.sql.gz

# 4. Restore previous code version
cd ~/frappe-bench/apps/verenigingen
git checkout previous-version-tag

# 5. Rebuild and restart
bench build
bench restart

# 6. Verify rollback
bench --site your-site execute "verenigingen.tests.utils.quick_validation.run_quick_tests()"

# 7. Disable maintenance mode
bench --site your-site set-maintenance-mode off
```

### 📝 Rollback Documentation
Document rollback actions:
- **Reason for rollback**
- **Data loss (if any)**
- **Actions taken**
- **Users affected**
- **Next steps planned**

## 🚨 Troubleshooting

### 🔧 Common Issues

#### Migration Failures
```bash
# Check migration status
bench --site your-site execute "frappe.db.get_value('Module Def', 'Verenigingen', 'app_version')"

# Retry specific migration
bench --site your-site migrate --verbose

# Skip problematic migration (CAUTION)
bench --site your-site execute "frappe.db.set_value('Patch Log', 'patch-name', 'executed', 1)"
```

#### Performance Issues
```bash
# Check slow queries
bench --site your-site execute "frappe.db.enable_query_log()"

# Rebuild database indices
bench --site your-site execute "frappe.db.rebuild_indices()"

# Clear all caches
bench --site your-site clear-cache
bench --site your-site clear-website-cache
```

#### Integration Failures
```bash
# Test eBoekhouden connection
bench --site your-site execute "verenigingen.utils.eboekhouden.test_connection()"

# Verify SEPA configuration
bench --site your-site execute "verenigingen.utils.sepa.validate_configuration()"

# Check email settings
bench --site your-site execute "frappe.email.test_email_configuration()"
```

### 📋 Diagnostic Commands
```bash
# System status
bench doctor

# App status
bench --site your-site list-apps

# Database status
bench --site your-site mariadb -e "SHOW TABLE STATUS;"

# Log analysis
tail -f ~/frappe-bench/logs/worker.error.log
```

## 📞 Getting Help

### 🆘 Support Channels
1. **Documentation**: Check [FAQ & Troubleshooting](FAQ_TROUBLESHOOTING.md)
2. **GitHub Issues**: Report bugs and problems
3. **Community Forum**: Ask questions and get community help
4. **Professional Support**: Contact for critical issues

### 📋 Information to Provide
When seeking help, include:
- **Current version**: `bench version`
- **Error messages**: Full error logs
- **System information**: OS, RAM, storage
- **Custom modifications**: Any code changes
- **Backup status**: Confirmation of working backups

### 🔍 Debug Information
```bash
# Generate diagnostic report
bench --site your-site execute "verenigingen.utils.diagnostics.generate_upgrade_report()"

# Export system configuration
bench --site your-site execute "frappe.utils.doctor.get_system_info()"
```

---

## 🎯 Best Practices

### 📅 Regular Maintenance
- **Weekly**: Review system logs and performance
- **Monthly**: Apply minor updates and security patches
- **Quarterly**: Plan major version updates
- **Annually**: Complete system audit and optimization

### 🛡️ Security Considerations
- Always test in staging environment first
- Keep backups for at least 30 days
- Monitor system for unusual activity post-upgrade
- Update security configurations as needed

### 📈 Performance Optimization
- Monitor database growth and optimize regularly
- Review and update system resources as needed
- Clean up old logs and temporary files
- Update SSL certificates and security configurations

---

**Remember**: Always test upgrades in a staging environment before applying to production systems. When in doubt, maintain your current stable version until issues are resolved.
