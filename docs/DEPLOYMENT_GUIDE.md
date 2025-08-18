# Mollie Backend API Integration - Deployment Guide

## Table of Contents
1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Environment Setup](#environment-setup)
3. [Installation Steps](#installation-steps)
4. [Configuration](#configuration)
5. [Database Migrations](#database-migrations)
6. [Security Setup](#security-setup)
7. [Testing](#testing)
8. [Go-Live Procedures](#go-live-procedures)
9. [Rollback Plan](#rollback-plan)
10. [Post-Deployment Verification](#post-deployment-verification)

## Pre-Deployment Checklist

### Requirements Verification
- [ ] Frappe Framework v15+ installed
- [ ] Python 3.10+ available
- [ ] Redis server running
- [ ] MySQL 8.0+ or MariaDB 10.6+ configured
- [ ] SSL certificates installed
- [ ] Backup system operational
- [ ] Monitoring infrastructure ready

### Mollie Account Setup
- [ ] Production API keys obtained
- [ ] Webhook URLs whitelisted
- [ ] IP addresses verified
- [ ] Rate limits confirmed
- [ ] Settlement accounts configured

### Team Readiness
- [ ] Operations team trained
- [ ] Support procedures documented
- [ ] Escalation paths defined
- [ ] Emergency contacts updated

## Environment Setup

### 1. System Dependencies

```bash
# Update system packages
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    redis-server \
    nginx \
    supervisor \
    git \
    curl

# Install Python dependencies
pip3 install --upgrade pip
pip3 install frappe-bench
```

### 2. Database Configuration

```sql
-- Create database and user
CREATE DATABASE verenigingen_prod;
CREATE USER 'frappe_prod'@'localhost' IDENTIFIED BY 'strong_password';
GRANT ALL PRIVILEGES ON verenigingen_prod.* TO 'frappe_prod'@'localhost';
FLUSH PRIVILEGES;
```

**Production MySQL Configuration**

**For MySQL 8.0+ (`/etc/mysql/mysql.conf.d/mysqld.cnf`):**
```ini
[mysqld]
# Security
bind-address = 127.0.0.1
mysqlx-bind-address = 127.0.0.1

# Performance tuning (adjust based on available RAM)
innodb_buffer_pool_size = 2G
max_connections = 200
innodb_log_file_size = 256M
innodb_flush_log_at_trx_commit = 2

# Frappe-specific optimizations
sql_mode = "STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION"
character_set_server = utf8mb4
collation_server = utf8mb4_unicode_ci

# Disable binary logging if not using replication
skip-log-bin
```

**For MariaDB 10.6+ (`/etc/mysql/mariadb.conf.d/50-server.cnf`):**
```ini
[mysqld]
# Security
bind-address = 127.0.0.1

# Performance tuning (adjust based on available RAM)
innodb_buffer_pool_size = 2G
max_connections = 200
innodb_log_file_size = 256M
innodb_flush_log_at_trx_commit = 2

# Query cache (still available in MariaDB)
query_cache_type = 1
query_cache_size = 64M

# Frappe-specific optimizations
sql_mode = "STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION"
character_set_server = utf8mb4
collation_server = utf8mb4_unicode_ci

# Disable binary logging if not using replication
skip-log-bin
```

**Apply configuration:**
```bash
# Restart MySQL/MariaDB after configuration changes
sudo systemctl restart mysql     # For MySQL
# OR
sudo systemctl restart mariadb   # For MariaDB
```

### 3. Redis Configuration

```bash
# Edit /etc/redis/redis.conf
maxmemory 512mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000

# SECURITY: Network binding (CRITICAL)
bind 127.0.0.1 ::1
protected-mode yes

# Restart Redis
sudo systemctl restart redis-server
```

## Installation Steps

### 1. Clone and Setup

```bash
# Create bench
cd /opt
bench init frappe-bench --frappe-branch version-15

# Get the app
cd frappe-bench
bench get-app verenigingen https://github.com/your-org/verenigingen.git

# Create production site
bench new-site prod.verenigingen.nl \
    --db-name verenigingen_prod \
    --mariadb-root-password $DB_ROOT_PASS \
    --admin-password $ADMIN_PASS

# Install app
bench --site prod.verenigingen.nl install-app verenigingen
```

### 2. Apply Mollie Backend Integration

```bash
# Copy integration files
cp -r /path/to/mollie-backend/* apps/verenigingen/

# Run migrations
bench --site prod.verenigingen.nl migrate

# Clear cache
bench --site prod.verenigingen.nl clear-cache
```

### 3. Install Python Dependencies

```bash
# Activate bench environment
source env/bin/activate

# Install Mollie SDK
pip install mollie-api-python==3.6.0

# Install additional dependencies
pip install pycryptodome==3.19.0
pip install python-jose==3.3.0
```

## Configuration

### 1. Site Configuration

Create `/opt/frappe-bench/sites/prod.verenigingen.nl/site_config.json`:

```json
{
  "db_name": "verenigingen_prod",
  "db_password": "db_password_here",
  "db_type": "mariadb",
  "encryption_key": "generate_strong_key_here",

  "redis_cache": "redis://localhost:11311",
  "redis_queue": "redis://localhost:11312",
  "redis_socketio": "redis://localhost:11313",

  "developer_mode": 0,
  "maintenance_mode": 0,
  "pause_scheduler": 0,

  "host_name": "https://prod.verenigingen.nl",
  "enable_frappe_logger": 1,
  "monitor": 1,

  "limits": {
    "space_usage": {
      "database_size": 10737418240,
      "backup_size": 5368709120,
      "files_size": 5368709120
    }
  }
}
```

### 2. Mollie Settings Configuration

```bash
# Configure via UI or console
bench --site prod.verenigingen.nl console

# In console:
mollie_settings = frappe.new_doc("Mollie Settings")
mollie_settings.gateway_name = "Production"
mollie_settings.secret_key = "live_xxx"  # Will be encrypted
mollie_settings.profile_id = "pfl_xxx"
mollie_settings.webhook_secret = "webhook_secret_xxx"
mollie_settings.enable_backend_api = True
mollie_settings.enable_encryption = True
mollie_settings.enable_audit_trail = True

# Resilience settings
mollie_settings.circuit_breaker_failure_threshold = 5
mollie_settings.circuit_breaker_timeout = 60
mollie_settings.rate_limit_requests_per_second = 25
mollie_settings.retry_max_attempts = 3

# Reconciliation settings
mollie_settings.auto_reconcile = True
mollie_settings.reconciliation_hour = 2
mollie_settings.reconciliation_tolerance = 0.01

# Alert settings
mollie_settings.low_balance_threshold = 1000.00
mollie_settings.enable_balance_alerts = True
mollie_settings.alert_recipients = "finance@company.com"

mollie_settings.insert()
frappe.db.commit()
```

### 3. Environment Variables

Create `/opt/frappe-bench/.env`:

```bash
# Mollie Configuration
MOLLIE_API_KEY=live_xxx
MOLLIE_PROFILE_ID=pfl_xxx
MOLLIE_WEBHOOK_SECRET=xxx

# Security
ENCRYPTION_KEY=generate_32_byte_key
JWT_SECRET=generate_secret_key

# Monitoring
SENTRY_DSN=https://xxx@sentry.io/xxx
DATADOG_API_KEY=xxx

# Email
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=notifications@company.com
SMTP_PASS=xxx
```

## Database Migrations

### 1. Create Required Tables

```bash
# Run migrations
bench --site prod.verenigingen.nl migrate

# Verify tables created
bench --site prod.verenigingen.nl mariadb

# In MariaDB:
SHOW TABLES LIKE '%mollie%';
-- Should show:
-- tabMollie Settings
-- tabMollie Audit Log
-- tabDispute Case
-- tabDispute Evidence
-- tabDispute Metrics
-- tabBalance Threshold
-- tabMollie Webhook Log
```

### 2. Create Indexes

```sql
-- Performance indexes
CREATE INDEX idx_audit_event ON `tabMollie Audit Log` (event_type, created);
CREATE INDEX idx_dispute_status ON `tabDispute Case` (status, priority);
CREATE INDEX idx_webhook_processed ON `tabMollie Webhook Log` (webhook_id, processed);
CREATE INDEX idx_balance_threshold ON `tabBalance Threshold` (balance_id, active);
```

### 3. Initial Data Setup

```python
# Create scheduled jobs
bench --site prod.verenigingen.nl console

# In console:
from frappe.utils.scheduler import get_jobs

# Add scheduled jobs
jobs = [
    {
        "job_name": "mollie.balance_monitoring",
        "job_type": "Cron",
        "cron_format": "*/15 * * * *",  # Every 15 minutes
        "method": "verenigingen.verenigingen_payments.monitoring.balance_monitor.run_balance_monitoring"
    },
    {
        "job_name": "mollie.reconciliation",
        "job_type": "Cron",
        "cron_format": "0 2 * * *",  # Daily at 2 AM
        "method": "verenigingen.verenigingen_payments.workflows.reconciliation_engine.run_daily_reconciliation"
    },
    {
        "job_name": "mollie.subscription_sync",
        "job_type": "Cron",
        "cron_format": "0 */6 * * *",  # Every 6 hours
        "method": "verenigingen.verenigingen_payments.workflows.subscription_manager.sync_all_subscription_payments"
    }
]

for job in jobs:
    doc = frappe.new_doc("Scheduled Job Type")
    doc.update(job)
    doc.insert()

frappe.db.commit()
```

## Security Setup

### 1. SSL Configuration

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d prod.verenigingen.nl

# Auto-renewal
sudo certbot renew --dry-run
```

### 2. Firewall Rules

```bash
# Configure UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow required ports
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS

# MySQL: SECURITY - Only allow from specific application servers
# Replace with your actual app server IPs in production
# sudo ufw allow from 10.0.0.10 to any port 3306 proto tcp
# sudo ufw allow from 10.0.0.11 to any port 3306 proto tcp
# For single-server setup, MySQL should bind to localhost only (no UFW rule needed)

# Redis: SECURITY - Do NOT expose Redis publicly
# Redis is configured to bind to localhost only (see redis.conf above)
# No UFW rule needed when Redis binds to 127.0.0.1

# Enable firewall
sudo ufw enable
```

### 3. API Key Rotation

```python
# Initial API key setup
bench --site prod.verenigingen.nl console

from verenigingen.verenigingen_payments.core.security import MollieSecurityManager

manager = MollieSecurityManager("Production")
manager.rotate_api_key()

# Schedule automatic rotation
frappe.db.set_value("Mollie Settings", "Production", "api_key_rotation_days", 90)
```

### 4. Webhook Security

```nginx
# Nginx configuration for webhook endpoint
location /api/method/verenigingen.utils.payment_gateways.mollie_webhook {
    # Mollie IP whitelist
    allow 87.233.217.24/29;
    allow 87.233.217.32/29;
    deny all;

    proxy_pass http://frappe-bench-frappe;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

## Testing

### 1. Pre-Production Testing

```bash
# Run test suite
bench --site prod.verenigingen.nl run-tests --app verenigingen --module vereinigingen.tests

# Run security tests
bench --site prod.verenigingen.nl run-tests --module verenigingen.tests.security.test_security_penetration

# Run performance tests
bench --site prod.verenigingen.nl run-tests --module verenigingen.tests.test_mollie_performance_benchmarks
```

### 2. Integration Testing

```python
# Test Mollie connection
bench --site prod.verenigingen.nl console

from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

client = BalancesClient("Production")
balances = client.list_balances()
print(f"Connected! Found {len(balances)} balances")
```

### 3. Load Testing

```bash
# Install locust
pip install locust

# Create locustfile.py
cat > locustfile.py << 'EOF'
from locust import HttpUser, task, between

class MollieAPIUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def get_balance(self):
        self.client.get("/api/method/get_account_balance")

    @task
    def get_dashboard(self):
        self.client.get("/api/method/get_dashboard_metrics")
EOF

# Run load test
locust -f locustfile.py --host=https://prod.verenigingen.nl
```

## Go-Live Procedures

### 1. Pre-Launch (T-24 hours)

```bash
# Full backup
bench --site prod.verenigingen.nl backup --with-files

# Verify backup
ls -la sites/prod.verenigingen.nl/private/backups/

# Test restore procedure (on staging)
bench --site staging.verenigingen.nl restore backup_file.sql.gz
```

### 2. Launch Window (T-0)

```bash
# Enable maintenance mode
bench --site prod.verenigingen.nl set-maintenance-mode on

# Final migration
bench --site prod.verenigingen.nl migrate

# Clear all caches
bench --site prod.verenigingen.nl clear-cache
bench --site prod.verenigingen.nl clear-website-cache

# Restart services
sudo supervisorctl restart all

# Disable maintenance mode
bench --site prod.verenigingen.nl set-maintenance-mode off
```

### 3. Smoke Tests

```python
# Critical path testing
tests = [
    "Test webhook reception",
    "Test balance retrieval",
    "Test settlement reconciliation",
    "Test subscription creation",
    "Test dispute creation"
]

for test in tests:
    print(f"[ ] {test}")
```

## Rollback Plan

### 1. Immediate Rollback (< 1 hour)

```bash
# Stop services
sudo supervisorctl stop all

# Restore database
bench --site prod.verenigingen.nl restore backup_file.sql.gz

# Restore files
tar -xzf files_backup.tar.gz -C sites/prod.verenigingen.nl/

# Clear cache
bench --site prod.verenigingen.nl clear-cache

# Restart services
sudo supervisorctl start all
```

### 2. Partial Rollback

```python
# Disable specific features
bench --site prod.verenigingen.nl console

frappe.db.set_value("Mollie Settings", "Production", {
    "enable_backend_api": False,
    "auto_reconcile": False
})
frappe.db.commit()
```

## Post-Deployment Verification

### 1. Health Checks

```bash
# System health
curl https://prod.verenigingen.nl/api/method/ping

# Database connectivity
bench --site prod.verenigingen.nl mariadb
SHOW STATUS LIKE 'Threads_connected';

# Redis connectivity
redis-cli ping

# Background jobs
bench --site prod.verenigingen.nl show-jobs
```

### 2. Monitoring Setup

```python
# Verify monitoring
bench --site prod.verenigingen.nl console

# Check audit trail
logs = frappe.get_all("Mollie Audit Log",
    filters={"created": [">", "2024-01-01"]},
    limit=10)
print(f"Audit logging active: {len(logs)} recent entries")

# Check alerts
from verenigingen.verenigingen_payments.monitoring.balance_monitor import BalanceMonitor
monitor = BalanceMonitor("Production")
health = monitor.run_monitoring_cycle()
print(f"Monitoring active: {health['status']}")
```

### 3. Performance Baseline

```sql
-- Capture baseline metrics
SELECT
    COUNT(*) as audit_logs,
    MAX(created) as latest_entry
FROM `tabMollie Audit Log`;

SELECT
    COUNT(*) as total_disputes,
    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_disputes
FROM `tabDispute Case`;
```

### 4. Documentation Updates

- [ ] Update runbook with production URLs
- [ ] Document actual configuration values
- [ ] Record baseline performance metrics
- [ ] Update emergency contacts
- [ ] Share credentials via secure channel

## Troubleshooting

### Common Issues

#### API Connection Failures
```bash
# Check connectivity
curl -X GET https://api.mollie.com/v2/balances \
  -H "Authorization: Bearer live_xxx"

# Check firewall
sudo iptables -L -n | grep 443
```

#### Webhook Not Received
```bash
# Check nginx logs
tail -f /var/log/nginx/access.log | grep mollie

# Verify webhook registration
bench --site prod.verenigingen.nl console
settings = frappe.get_doc("Mollie Settings", "Production")
print(settings.webhook_url)
```

#### High Memory Usage
```bash
# Check memory
free -h

# Restart workers
sudo supervisorctl restart frappe-bench-workers:*

# Clear cache
bench --site prod.verenigingen.nl clear-cache
```

## Support Contacts

### Internal Team
- Operations Lead: ops-lead@company.com
- Database Admin: dba@company.com
- Security Team: security@company.com

### External Support
- Mollie Support: support@mollie.com
- Mollie API Status: https://status.mollie.com
- Frappe Support: support@frappe.io

---

*Last Updated: August 2024*
*Version: 1.0.0*
