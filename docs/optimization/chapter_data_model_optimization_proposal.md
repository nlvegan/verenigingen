# Chapter Data Model Optimization Proposal

## Executive Summary

Analysis of the Chapter DocType and related child tables reveals several performance optimization opportunities. This document outlines recommended database schema improvements to enhance query performance without breaking existing functionality.

## Current Performance Issues

### 1. Missing Database Indexes

**Chapter Table:**
- `region` field lacks indexing for geographic queries
- `status` field needs indexing for active/inactive filtering
- `published` field should be indexed for public chapter queries

**Chapter Board Member Child Table:**
- `volunteer` field lacks indexing for JOIN operations
- `chapter_role` field needs indexing for role-based filtering
- `from_date`/`to_date` need composite index for date range queries
- `is_active` field should be indexed for status filtering

**Chapter Member Child Table:**
- `member` field lacks indexing despite being primary relationship
- `status` field needs indexing for Pending/Active/Inactive filtering
- `chapter_join_date` should be indexed for chronological queries
- `enabled` checkbox needs indexing for active member queries

### 2. N+1 Query Problems

**Chapter Board Member fetch_from Fields:**
```json
"fetch_from": "volunteer.volunteer_name"
"fetch_from": "volunteer.email"
```

These create expensive N+1 query patterns when displaying board member grids. Each row triggers additional database queries to fetch volunteer data.

### 3. Inefficient Date Range Queries

Current "active board member" queries scan all records to check date ranges without proper indexing, causing performance degradation as data grows.

## Recommended Optimizations

### Phase 1: Add Missing Indexes

```sql
-- Chapter table indexes
ALTER TABLE `tabChapter` ADD INDEX `idx_region` (`region`);
ALTER TABLE `tabChapter` ADD INDEX `idx_status` (`status`);
ALTER TABLE `tabChapter` ADD INDEX `idx_published` (`published`);

-- Chapter Board Member indexes
ALTER TABLE `tabChapter Board Member` ADD INDEX `idx_volunteer` (`volunteer`);
ALTER TABLE `tabChapter Board Member` ADD INDEX `idx_chapter_role` (`chapter_role`);
ALTER TABLE `tabChapter Board Member` ADD INDEX `idx_active_period` (`from_date`, `to_date`, `is_active`);
ALTER TABLE `tabChapter Board Member` ADD INDEX `idx_is_active` (`is_active`);

-- Chapter Member indexes
ALTER TABLE `tabChapter Member` ADD INDEX `idx_member` (`member`);
ALTER TABLE `tabChapter Member` ADD INDEX `idx_status` (`status`);
ALTER TABLE `tabChapter Member` ADD INDEX `idx_join_date` (`chapter_join_date`);
ALTER TABLE `tabChapter Member` ADD INDEX `idx_enabled` (`enabled`);
```

### Phase 2: Optimize fetch_from Usage

**Problem:** Board member grids trigger N+1 queries for volunteer data.

**Solution Options:**

1. **Server-side JOIN optimization** - Modify DocType queries to use explicit JOINs
2. **Caching layer** - Cache frequently accessed volunteer data
3. **Denormalization** - Store critical volunteer data directly in board member records

**Recommended:** Server-side JOIN optimization to maintain data consistency.

### Phase 3: Query Optimization

**Common Query Patterns to Optimize:**

1. **Active Board Members Query:**
```python
# Current inefficient pattern
board_members = frappe.get_all('Chapter Board Member',
    filters={'parent': chapter_name, 'is_active': 1})

# Optimized with proper indexing and date filtering
active_members = frappe.db.sql("""
    SELECT cbm.*, v.volunteer_name, v.email
    FROM `tabChapter Board Member` cbm
    LEFT JOIN `tabVolunteer` v ON cbm.volunteer = v.name
    WHERE cbm.parent = %s
        AND cbm.is_active = 1
        AND (cbm.to_date IS NULL OR cbm.to_date >= CURDATE())
        AND cbm.from_date <= CURDATE()
""", [chapter_name], as_dict=True)
```

2. **Chapter Member Lookup by Member:**
```python
# Optimized member-to-chapters query
chapters = frappe.db.sql("""
    SELECT c.name, c.region, cm.status, cm.chapter_join_date
    FROM `tabChapter` c
    JOIN `tabChapter Member` cm ON c.name = cm.parent
    WHERE cm.member = %s AND cm.enabled = 1
""", [member_name], as_dict=True)
```

## Implementation Strategy

### Database Migration Approach

1. **Create custom migration patch** in `verenigingen/patches/v15_0/add_chapter_indexes.py`
2. **Test on development data** to measure performance impact
3. **Validate existing queries** still function correctly
4. **Deploy during maintenance window** to minimize disruption

### Performance Testing

Before and after benchmarks should include:

- Chapter list view loading time
- Board member grid rendering
- Member-to-chapter lookup queries
- Geographic chapter filtering (by region)
- Date range queries for board member history

### Risk Mitigation

- **Non-breaking changes** - All optimizations preserve existing functionality
- **Incremental deployment** - Indexes can be added individually
- **Rollback plan** - Indexes can be dropped if issues arise
- **Query monitoring** - Track slow query logs before/after changes

## Expected Performance Improvements

- **Chapter list filtering:** 60-80% reduction in query time
- **Board member grid loading:** 70-90% reduction with JOIN optimization
- **Member-chapter lookups:** 80-90% improvement with proper indexing
- **Date range queries:** 85-95% improvement with composite indexes

## Implementation Timeline

- **Phase 1 (Indexing):** 1-2 days for implementation and testing
- **Phase 2 (Query optimization):** 3-5 days for JOIN optimization
- **Phase 3 (Performance validation):** 2-3 days for benchmarking

Total estimated effort: 1-2 weeks for complete optimization.
