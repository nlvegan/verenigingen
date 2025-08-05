# eBoekhouden Integration Improvement Plan

> **Archive Status**: Moved from unimplemented-plans during Phase 1B consolidation (January 2025)
> **Implementation Status**: ✅ **LARGELY COMPLETED** - Backend functionality implemented
> **Note**: The core duplicate detection and merging functionality described in this plan has been implemented in `verenigingen/utils/migration/migration_duplicate_detection.py` with whitelisted functions `detect_migration_duplicates()` and `merge_duplicate_group()`. Only the web UI component remains unimplemented.

## Executive Summary

This document outlines the improvement plan for the eBoekhouden integration system based on analysis of current capabilities and identified gaps. The plan focuses on enhancing data quality, system resilience, user experience, and maintainability.

## Current State Assessment

### ✅ Already Implemented
- REST API integration with full transaction history
- Opening balance import (€324K+ successfully imported)
- Intelligent party resolution with provisional customer/supplier creation
- Enhanced payment naming and item creation
- Duplicate detection for invoice numbers
- Comprehensive error logging

### ⚠️ Key Gaps Identified
- Customer/supplier merge functionality exists but not exposed as user-friendly interface
- Limited resilience for API failures and long-running imports
- Basic progress reporting without real-time updates
- Fixed batch sizes that don't adapt to system resources
- No systematic data quality regression testing
- Limited configuration flexibility for different organizations

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
**Goal**: Establish critical data quality and management capabilities

#### 1.1 Customer/Supplier Merge User Interface
**Priority**: Critical
**Effort**: 2-3 days

**Current State**:
- ✅ Merge logic exists in `migration_duplicate_detection.py`
- ✅ `DuplicateMerger` class with `merge_duplicates()` method
- ✅ Reference updating via `_update_references()`
- ✅ Whitelisted functions: `detect_migration_duplicates()` and `merge_duplicate_group()`
- ❌ No user-friendly interface for accessing this functionality

**Implementation**:
```python
# Create UI page for party merge management
# Path: verenigingen/www/party_merge_tool.html
"""
{% extends "templates/web.html" %}

{% block title %}{{ _("Customer/Supplier Merge Tool") }}{% endblock %}

{% block page_content %}
<div class="party-merge-tool">
    <h1>{{ _("Customer/Supplier Merge Tool") }}</h1>

    <div class="merge-controls">
        <select id="party-type">
            <option value="Customer">Customer</option>
            <option value="Supplier">Supplier</option>
        </select>

        <button onclick="detectDuplicates()">
            {{ _("Detect Duplicates") }}
        </button>
    </div>

    <div id="duplicate-groups" class="mt-4"></div>
</div>

<script>
function detectDuplicates() {
    const partyType = document.getElementById('party-type').value;

    frappe.call({
        method: 'verenigingen.utils.migration.migration_duplicate_detection.detect_migration_duplicates',
        args: { doctype: partyType },
        callback: function(r) {
            displayDuplicateGroups(r.message);
        }
    });
}

function displayDuplicateGroups(data) {
    // Display duplicate groups with merge buttons
    const container = document.getElementById('duplicate-groups');
    container.innerHTML = data.duplicate_groups.map(group => `
        <div class="duplicate-group card p-3 mb-3">
            <h4>Primary: ${group.primary}</h4>
            <p>Duplicates: ${group.duplicates.join(', ')}</p>
            <p>Confidence: ${group.confidence}%</p>
            <button onclick="mergeGroup('${data.doctype}', '${group.primary}',
                            '${JSON.stringify(group.duplicates)}')">
                Merge Group
            </button>
        </div>
    `).join('');
}

function mergeGroup(doctype, primary, duplicatesJson) {
    const duplicates = JSON.parse(duplicatesJson);

    if (!confirm(`Merge ${duplicates.length} records into ${primary}?`)) {
        return;
    }

    frappe.call({
        method: 'verenigingen.utils.migration.migration_duplicate_detection.merge_duplicate_group',
        args: {
            doctype: doctype,
            primary: primary,
            duplicates: duplicates
        },
        callback: function(r) {
            frappe.show_alert({
                message: `Successfully merged ${r.message.merged_count} records`,
                indicator: 'green'
            });
            detectDuplicates(); // Refresh
        }
    });
}
</script>
{% endblock %}
"""

# Add route in hooks.py
website_route_rules = [
    {"from_route": "/party-merge-tool", "to_route": "party_merge_tool"},
]

# Create improved detection for generic/provisional parties
def detect_provisional_parties(party_type="Customer"):
    """Detect provisional parties that need merging"""

    provisional_patterns = [
        "E-Boekhouden %",
        "eBoekhouden Import %",
        "% (eBoekhouden Import)",
        "E-Boekhouden Relation %"
    ]

    provisional_parties = []
    for pattern in provisional_patterns:
        parties = frappe.get_all(
            party_type,
            filters={f"{party_type.lower()}_name": ["like", pattern]},
            fields=["name", f"{party_type.lower()}_name", "creation"]
        )
        provisional_parties.extend(parties)

    # Group by similar names
    return group_similar_parties(provisional_parties)
```

**Deliverables**:
- User-friendly web interface for party merging
- Provisional party detection
- Batch merge capabilities
- Progress tracking for large merge operations
- Merge history and audit log

#### 1.2 Data Quality Regression Testing Framework
**Priority**: High
**Effort**: 2-3 days

**Implementation**:
```python
# Quality metrics tracking
class EBoekhoudenQualityMetrics:
    """Track and compare data quality metrics before/after migrations"""

    def capture_baseline(self):
        return {
            "timestamp": datetime.now(),
            "metrics": {
                "party_quality": {
                    "generic_customers": self.count_generic_parties("Customer"),
                    "generic_suppliers": self.count_generic_parties("Supplier"),
                    "empty_tax_ids": self.count_empty_tax_ids(),
                    "missing_addresses": self.count_missing_addresses()
                },
                "transaction_quality": {
                    "unbalanced_entries": self.count_unbalanced_entries(),
                    "missing_references": self.count_missing_references(),
                    "orphaned_payments": self.count_orphaned_payments()
                },
                "account_quality": {
                    "unmapped_accounts": self.count_unmapped_accounts(),
                    "duplicate_accounts": self.count_duplicate_accounts()
                }
            }
        }

    def generate_comparison_report(self, baseline, current):
        """Generate detailed comparison report with improvements/regressions"""
```

**Deliverables**:
- Quality metrics DocType
- Automated quality testing functions
- Comparison reporting system
- Scheduled quality checks
- Quality dashboard page

### Phase 2: Resilience & Performance (Weeks 3-4)
**Goal**: Make the system robust and scalable

#### 2.1 Enhanced Error Recovery
**Priority**: High
**Effort**: 3-4 days

**Implementation**:
```python
# Resumable migration with state persistence
class ResumableMigration:
    def __init__(self, migration_id):
        self.migration_id = migration_id
        self.state = self.load_or_create_state()

    def save_checkpoint(self):
        """Save current progress for resume capability"""
        self.state.update({
            "last_processed_id": self.current_mutation_id,
            "processed_count": self.processed_count,
            "failed_items": self.failed_items,
            "checkpoint_time": datetime.now()
        })
        frappe.db.set_value("E-Boekhouden Migration",
                          self.migration_id,
                          "state",
                          json.dumps(self.state))

# Retry mechanism with exponential backoff
@retry_with_backoff(max_retries=3, backoff_factor=2)
def fetch_with_resilience(url, headers):
    """Fetch with automatic retry on failure"""
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code >= 500:
        raise RetryableError(f"Server error: {response.status_code}")
    return response
```

**Deliverables**:
- Migration state persistence
- Resume functionality
- Retry decorators for all API calls
- Circuit breaker implementation
- Failed item queue for manual review

#### 2.2 Adaptive Performance Management
**Priority**: Medium
**Effort**: 2-3 days

**Implementation**:
```python
# Dynamic batch sizing based on system resources
class AdaptiveBatchProcessor:
    def __init__(self):
        self.batch_size = 100
        self.performance_history = []

    def adjust_batch_size(self):
        """Dynamically adjust batch size based on performance"""
        memory_usage = psutil.virtual_memory().percent
        cpu_usage = psutil.cpu_percent(interval=1)

        if memory_usage > 80 or cpu_usage > 90:
            self.batch_size = max(10, int(self.batch_size * 0.7))
        elif memory_usage < 50 and cpu_usage < 50:
            self.batch_size = min(1000, int(self.batch_size * 1.3))

        # Adjust based on processing time
        if self.performance_history:
            avg_time = sum(self.performance_history[-5:]) / 5
            if avg_time > 30:  # Taking too long
                self.batch_size = max(10, int(self.batch_size * 0.8))

# Memory-efficient streaming processor
class StreamingProcessor:
    def process_large_dataset(self, mutation_iterator):
        """Process mutations without loading all into memory"""
        buffer = []
        for mutation in mutation_iterator:
            buffer.append(mutation)
            if len(buffer) >= self.batch_size:
                yield from self.process_buffer(buffer)
                buffer = []
                frappe.db.commit()  # Free memory
```

**Deliverables**:
- Adaptive batch sizing algorithm
- Memory monitoring integration
- Streaming processor for large datasets
- Performance metrics collection
- Auto-optimization based on history

### Phase 3: User Experience (Weeks 5-6)
**Goal**: Provide visibility and control over migrations

#### 3.1 Real-time Progress Dashboard
**Priority**: Medium
**Effort**: 4-5 days

**Implementation**:
```python
# WebSocket-based progress updates
class MigrationProgressBroadcaster:
    def __init__(self, migration_id):
        self.migration_id = migration_id
        self.channel = f"eboekhouden_migration_{migration_id}"

    def broadcast_progress(self, current, total, phase="processing"):
        """Send real-time progress updates"""
        progress_data = {
            "migration_id": self.migration_id,
            "phase": phase,
            "current": current,
            "total": total,
            "percentage": (current / total * 100) if total > 0 else 0,
            "current_entity": self.current_entity_description,
            "estimated_completion": self.calculate_eta(),
            "memory_usage": psutil.virtual_memory().percent,
            "processing_rate": self.calculate_rate()
        }

        frappe.publish_realtime(
            event="migration_progress",
            message=progress_data,
            room=self.channel
        )

# Vue.js dashboard component
"""
<template>
  <div class="migration-dashboard">
    <div class="progress-header">
      <h3>{{ migrationTitle }}</h3>
      <div class="controls">
        <button @click="pauseMigration" :disabled="!canPause">
          {{ isPaused ? 'Resume' : 'Pause' }}
        </button>
        <button @click="cancelMigration" class="danger">Cancel</button>
      </div>
    </div>

    <div class="progress-details">
      <progress-bar :value="progress.percentage" />
      <div class="stats-grid">
        <div class="stat">
          <label>Progress</label>
          <value>{{ progress.current }} / {{ progress.total }}</value>
        </div>
        <div class="stat">
          <label>Processing Rate</label>
          <value>{{ progress.processing_rate }} items/min</value>
        </div>
        <div class="stat">
          <label>ETA</label>
          <value>{{ formatTime(progress.estimated_completion) }}</value>
        </div>
        <div class="stat">
          <label>Memory Usage</label>
          <value :class="memoryClass">{{ progress.memory_usage }}%</value>
        </div>
      </div>
    </div>

    <div class="current-item">
      <label>Currently Processing:</label>
      <span>{{ progress.current_entity }}</span>
    </div>
  </div>
</template>
"""
```

**Deliverables**:
- WebSocket integration for real-time updates
- Migration dashboard page
- Pause/resume functionality
- Progress persistence
- Email notifications for completion/failure

### Phase 4: Configuration & Flexibility (Weeks 7-8)
**Goal**: Make the system adaptable to different organizational needs

#### 4.1 Rule-Based Mapping Engine
**Priority**: Medium
**Effort**: 3-4 days

**Implementation**:
```python
# Flexible mapping rules system
class MappingRuleEngine:
    def __init__(self, company):
        self.company = company
        self.rules = self.load_rules()
        self.script_cache = {}

    def create_rule(self, rule_data):
        """Create a new mapping rule"""
        rule = frappe.new_doc("eBoekhouden Mapping Rule")
        rule.update({
            "rule_name": rule_data["name"],
            "source_pattern": rule_data["pattern"],
            "target_template": rule_data["template"],
            "rule_type": rule_data["type"],  # account, party, item
            "conditions": json.dumps(rule_data.get("conditions", [])),
            "transformation_script": rule_data.get("script", ""),
            "priority": rule_data.get("priority", 100)
        })
        rule.save()

    def apply_mapping(self, source_value, rule_type):
        """Apply mapping rules to transform values"""
        applicable_rules = self.get_applicable_rules(source_value, rule_type)

        for rule in applicable_rules:
            if self.matches_rule(source_value, rule):
                return self.transform_value(source_value, rule)

        return source_value  # No transformation

# UI for rule management
"""
frappe.ui.form.on('eBoekhouden Mapping Rule', {
    test_rule: function(frm) {
        frappe.prompt({
            label: 'Test Value',
            fieldname: 'test_value',
            fieldtype: 'Data'
        }, (values) => {
            frappe.call({
                method: 'test_mapping_rule',
                args: {
                    rule: frm.doc.name,
                    test_value: values.test_value
                },
                callback: (r) => {
                    frappe.msgprint(`
                        Input: ${values.test_value}<br>
                        Output: ${r.message.output}<br>
                        Matched: ${r.message.matched}
                    `);
                }
            });
        });
    }
});
"""
```

**Deliverables**:
- Mapping Rule DocType
- Rule engine implementation
- Rule testing interface
- Import/export rules functionality
- Rule templates for common scenarios

### Phase 5: Advanced Features (Weeks 9-10)
**Goal**: Add sophisticated capabilities for large-scale operations

#### 5.1 API Rate Limiting & Monitoring
**Priority**: Low
**Effort**: 2-3 days

**Implementation**:
```python
# Intelligent rate limiting with monitoring
class SmartAPIClient:
    def __init__(self):
        self.rate_limiter = TokenBucket(tokens_per_minute=60)
        self.metrics = APIMetrics()

    def make_request(self, endpoint, method="GET", **kwargs):
        """Make API request with smart rate limiting"""

        # Wait for token if needed
        wait_time = self.rate_limiter.consume()
        if wait_time > 0:
            self.log_rate_limit_wait(wait_time)
            time.sleep(wait_time)

        # Track request
        request_start = time.time()

        try:
            response = requests.request(method, endpoint, **kwargs)
            response_time = time.time() - request_start

            # Update metrics
            self.metrics.record_request(
                endpoint=endpoint,
                response_time=response_time,
                status_code=response.status_code,
                response_size=len(response.content)
            )

            # Adaptive throttling
            if response_time > 2.0:
                self.rate_limiter.reduce_rate(0.8)
            elif response_time < 0.5:
                self.rate_limiter.increase_rate(1.1)

            return response

        except Exception as e:
            self.metrics.record_error(endpoint, str(e))
            raise

# API metrics dashboard
class APIMetricsDashboard:
    def get_metrics_summary(self, timeframe="1h"):
        """Get API performance metrics"""
        return {
            "total_requests": self.count_requests(timeframe),
            "average_response_time": self.avg_response_time(timeframe),
            "error_rate": self.calculate_error_rate(timeframe),
            "rate_limit_hits": self.count_rate_limits(timeframe),
            "endpoints": self.get_endpoint_breakdown(timeframe)
        }
```

**Deliverables**:
- Smart rate limiting implementation
- API metrics collection
- Performance monitoring dashboard
- Automatic throttling adjustment
- Alert system for API issues

## Success Metrics

### Phase 1 Success Criteria
- ✅ 90% reduction in generic customer/supplier entries after merge
- ✅ Data quality scores improve by 25% or more
- ✅ Zero data loss during merge operations

### Phase 2 Success Criteria
- ✅ 100% of migrations can be resumed after failure
- ✅ 50% reduction in migration failures due to timeouts
- ✅ Automatic batch size optimization reduces memory errors by 80%

### Phase 3 Success Criteria
- ✅ Real-time progress updates with <1 second latency
- ✅ 90% of users successfully use pause/resume feature
- ✅ 75% reduction in support tickets about migration status

### Phase 4 Success Criteria
- ✅ 80% of mapping customizations done through UI (no code)
- ✅ 60% reduction in post-migration data cleanup time
- ✅ Successfully deploy organization-specific rules

### Phase 5 Success Criteria
- ✅ Zero API rate limit errors during normal operations
- ✅ 99.9% API availability tracking
- ✅ Automatic performance optimization reduces API costs by 20%

## Risk Mitigation

### Technical Risks
1. **WebSocket compatibility**: Provide polling fallback for older browsers
2. **Memory constraints**: Implement hard limits and graceful degradation
3. **API changes**: Version detection and compatibility layer

### Data Risks
1. **Merge conflicts**: Comprehensive validation before merge
2. **Performance impact**: Run heavy operations during off-hours
3. **Data integrity**: Transaction-based operations with rollback

### User Risks
1. **Complexity**: Progressive disclosure UI with sensible defaults
2. **Training**: Built-in help and video tutorials
3. **Change management**: Gradual rollout with pilot users

## Resource Requirements

### Development Team
- 1 Senior Backend Developer (10 weeks)
- 1 Frontend Developer (4 weeks for UI components)
- 1 QA Engineer (2 weeks for testing)

### Infrastructure
- WebSocket server for real-time updates
- Additional Redis memory for progress tracking
- Monitoring infrastructure (optional Sentry/DataDog)

### Timeline Summary
- **Phase 1**: Weeks 1-2 (Foundation)
- **Phase 2**: Weeks 3-4 (Resilience)
- **Phase 3**: Weeks 5-6 (User Experience)
- **Phase 4**: Weeks 7-8 (Configuration)
- **Phase 5**: Weeks 9-10 (Advanced Features)
- **Testing & Deployment**: Week 11
- **Documentation & Training**: Week 12

## Conclusion

This improvement plan addresses the key gaps in the eBoekhouden integration while building on the solid foundation already in place. The phased approach allows for incremental delivery of value while minimizing disruption to existing operations.

The focus on data quality, resilience, and user experience will significantly improve the reliability and usability of the integration, reducing support burden and improving data accuracy across the system.
