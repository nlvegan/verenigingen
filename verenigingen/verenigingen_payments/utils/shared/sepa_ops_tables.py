"""Install/migrate bootstrap for the ad-hoc SEPA operations tables.

Six tables back SEPA notification, distributed-locking and rollback tracking.
None of them is a registered DocType, so nothing in the framework's normal
install/migrate machinery (``sync_for``) creates them. Historically each
manager created its own tables lazily, the first time it was instantiated
(``SEPANotificationManager._ensure_notification_tables``,
``SEPADistributedLock._ensure_lock_table``,
``SEPARollbackManager._ensure_rollback_tables``). That DDL ran inside
whatever transaction the caller already held: the first write in that
transaction makes any later ``CREATE TABLE`` raise ``ImplicitCommitError``
(DDL auto-commits in MariaDB), and every one of those call sites swallowed
that exception. On a fresh site (every CI shard, and any newly installed
site before some write-free request happened to construct the manager
first) the table is silently never created, and the first read against it
fails with "table doesn't exist" (#1510).

This module owns all six ``CREATE TABLE IF NOT EXISTS`` statements in one
place and is called from both ``after_install`` and ``after_migrate``
(``verenigingen/hooks/lifecycle.py``) so every site -- fresh install or an
upgrade of an existing one -- has the tables before any request-path code
can run. ``after_install`` covers CI (a fresh site never runs
``patches.txt`` or a bare ``bench migrate``, but does run ``after_install``
via ``install-app``); ``after_migrate`` covers every subsequent
``bench migrate`` on a site that already had the app installed.

Each statement uses ``frappe.db.sql_ddl()`` rather than ``frappe.db.sql()``:
DDL auto-commits in MariaDB, so running it through ``frappe.db.sql()`` mid
transaction raises ``ImplicitCommitError``; ``sql_ddl()`` commits any pending
work first, then runs the DDL, so it is safe regardless of how much (if any)
prior transaction state exists at install/migrate time. This also means a
genuine failure here is NOT swallowed -- it propagates out of
``after_install``/``after_migrate`` like any other patch failure, unlike the
old per-manager code that logged a warning and moved on.

Schemas are byte-for-byte identical to the ones the three managers used to
create inline, so ``IF NOT EXISTS`` stays a true no-op on every site that
already has these tables from an earlier run.
"""

import frappe

_CREATE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS `tabSEPA_Notification_Log` (
        `name` varchar(255) NOT NULL PRIMARY KEY,
        `creation` datetime(6) DEFAULT NULL,
        `modified` datetime(6) DEFAULT NULL,
        `notification_id` varchar(255) NOT NULL UNIQUE,
        `notification_type` varchar(100) NOT NULL,
        `priority` varchar(50) NOT NULL,
        `channels` varchar(255) DEFAULT NULL,
        `recipients` longtext DEFAULT NULL,
        `subject` text DEFAULT NULL,
        `message` longtext DEFAULT NULL,
        `context` longtext DEFAULT NULL,
        `delivery_status` varchar(50) DEFAULT 'pending',
        `delivery_attempts` int DEFAULT 0,
        `last_attempt` datetime(6) DEFAULT NULL,
        `delivered_at` datetime(6) DEFAULT NULL,
        `error_message` text DEFAULT NULL,
        INDEX `idx_notification_type` (`notification_type`),
        INDEX `idx_delivery_status` (`delivery_status`),
        INDEX `idx_creation` (`creation`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `tabSEPA_Notification_Preferences` (
        `name` varchar(255) NOT NULL PRIMARY KEY,
        `creation` datetime(6) DEFAULT NULL,
        `modified` datetime(6) DEFAULT NULL,
        `user_email` varchar(255) NOT NULL,
        `notification_type` varchar(100) NOT NULL,
        `enabled` tinyint(1) DEFAULT 1,
        `channels` varchar(255) DEFAULT 'email',
        `minimum_priority` varchar(50) DEFAULT 'medium',
        UNIQUE KEY `unique_user_type` (`user_email`, `notification_type`),
        INDEX `idx_user_email` (`user_email`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `tabSEPA_Distributed_Lock` (
        `name` varchar(255) NOT NULL PRIMARY KEY,
        `creation` datetime(6) DEFAULT NULL,
        `modified` datetime(6) DEFAULT NULL,
        `modified_by` varchar(255) DEFAULT NULL,
        `owner` varchar(255) DEFAULT NULL,
        `docstatus` int(1) NOT NULL DEFAULT 0,
        `lock_id` varchar(255) NOT NULL,
        `resource` varchar(255) NOT NULL,
        `lock_owner` varchar(255) NOT NULL,
        `acquired_at` datetime(6) NOT NULL,
        `expires_at` datetime(6) NOT NULL,
        `lock_type` varchar(100) NOT NULL,
        `metadata` longtext DEFAULT NULL,
        `is_active` tinyint(1) DEFAULT 1,
        INDEX `idx_resource_active` (`resource`, `is_active`),
        INDEX `idx_expires_at` (`expires_at`),
        INDEX `idx_lock_owner` (`lock_owner`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `tabSEPA_Rollback_Operation` (
        `name` varchar(255) NOT NULL PRIMARY KEY,
        `creation` datetime(6) DEFAULT NULL,
        `modified` datetime(6) DEFAULT NULL,
        `modified_by` varchar(255) DEFAULT NULL,
        `owner` varchar(255) DEFAULT NULL,
        `docstatus` int(1) NOT NULL DEFAULT 0,
        `operation_id` varchar(255) NOT NULL UNIQUE,
        `batch_name` varchar(255) NOT NULL,
        `reason` varchar(100) NOT NULL,
        `scope` varchar(100) NOT NULL,
        `initiated_by` varchar(255) NOT NULL,
        `initiated_at` datetime(6) NOT NULL,
        `affected_invoices` longtext DEFAULT NULL,
        `affected_members` longtext DEFAULT NULL,
        `total_amount` decimal(18,2) DEFAULT 0.00,
        `compensation_actions` longtext DEFAULT NULL,
        `status` varchar(50) DEFAULT 'pending',
        `completed_at` datetime(6) DEFAULT NULL,
        `error_log` longtext DEFAULT NULL,
        `metadata` longtext DEFAULT NULL,
        INDEX `idx_batch_name` (`batch_name`),
        INDEX `idx_initiated_at` (`initiated_at`),
        INDEX `idx_status` (`status`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `tabSEPA_Compensation_Transaction` (
        `name` varchar(255) NOT NULL PRIMARY KEY,
        `creation` datetime(6) DEFAULT NULL,
        `modified` datetime(6) DEFAULT NULL,
        `modified_by` varchar(255) DEFAULT NULL,
        `owner` varchar(255) DEFAULT NULL,
        `docstatus` int(1) NOT NULL DEFAULT 0,
        `transaction_id` varchar(255) NOT NULL UNIQUE,
        `operation_id` varchar(255) NOT NULL,
        `action_type` varchar(100) NOT NULL,
        `original_invoice` varchar(255) DEFAULT NULL,
        `original_amount` decimal(18,2) DEFAULT 0.00,
        `compensation_amount` decimal(18,2) DEFAULT 0.00,
        `reason` text DEFAULT NULL,
        `status` varchar(50) DEFAULT 'pending',
        `created_at` datetime(6) NOT NULL,
        `document_references` longtext DEFAULT NULL,
        `metadata` longtext DEFAULT NULL,
        INDEX `idx_operation_id` (`operation_id`),
        INDEX `idx_original_invoice` (`original_invoice`),
        INDEX `idx_created_at` (`created_at`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `tabSEPA_Rollback_Audit` (
        `name` varchar(255) NOT NULL PRIMARY KEY,
        `creation` datetime(6) DEFAULT NULL,
        `modified` datetime(6) DEFAULT NULL,
        `entry_id` varchar(255) NOT NULL UNIQUE,
        `operation_id` varchar(255) DEFAULT NULL,
        `timestamp` datetime(6) NOT NULL,
        `action` varchar(255) NOT NULL,
        `details` longtext DEFAULT NULL,
        `user` varchar(255) DEFAULT NULL,
        `system_info` longtext DEFAULT NULL,
        INDEX `idx_operation_id` (`operation_id`),
        INDEX `idx_timestamp` (`timestamp`),
        INDEX `idx_action` (`action`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def ensure_sepa_ops_tables() -> None:
    """Create the six SEPA operations tables if they do not already exist.

    Called from ``after_install`` and ``after_migrate``. Each ``CREATE TABLE``
    runs through ``frappe.db.sql_ddl()`` so it is safe to call at any point in
    the install/migrate lifecycle, and a real failure raises instead of being
    swallowed (matching how every other schema-bootstrap entry in
    ``after_migrate`` behaves).
    """
    for create_sql in _CREATE_STATEMENTS:
        frappe.db.sql_ddl(create_sql)
