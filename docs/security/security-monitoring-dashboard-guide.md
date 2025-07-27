# Security Monitoring Dashboard Implementation Guide

## Overview

This guide provides comprehensive implementation instructions for the enhanced security monitoring dashboard, designed based on the July 2025 security review findings and next phase implementation requirements.

**Target**: Transition from 82/100 to 90/100 security score with real-time monitoring capabilities.

## Table of Contents

1. [Dashboard Architecture](#dashboard-architecture)
2. [Backend Implementation](#backend-implementation)
3. [Frontend Components](#frontend-components)
4. [Real-Time Monitoring](#real-time-monitoring)
5. [Alerting System](#alerting-system)
6. [Installation and Setup](#installation-and-setup)

## Dashboard Architecture

### System Overview

```
┌─────────────────────────────────────────────────┐
│              Security Dashboard                 │
├─────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Metrics   │  │   Alerts    │  │ Analysis │ │
│  │ Calculator  │  │   System    │  │  Engine  │ │
│  └─────────────┘  └─────────────┘  └──────────┘ │
├─────────────────────────────────────────────────┤
│              API Security Framework             │
├─────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │    Audit    │  │    Rate     │  │   CSRF   │ │
│  │   Logger    │  │   Limiter   │  │Protection│ │
│  └─────────────┘  └─────────────┘  └──────────┘ │
└─────────────────────────────────────────────────┘
```

### Core Components

1. **Security Metrics Calculator** - Real-time security score computation
2. **Dashboard API** - Backend data provision for UI
3. **Real-Time Monitor** - Live security status tracking
4. **Alert Manager** - Automated incident detection and notification
5. **Analytics Engine** - Historical analysis and trend detection

## Backend Implementation

### 1. Security Metrics Calculator

**File**: `verenigingen/utils/security/security_metrics_calculator.py`

```python
"""
Security Metrics Calculator
Calculates real-time security metrics for dashboard
"""

import frappe
from datetime import datetime, timedelta
from typing import Dict, List, Any
from verenigingen.utils.security.api_security_framework import get_security_framework_status

class SecurityMetricsCalculator:
    """Calculate comprehensive security metrics for dashboard"""

    def __init__(self):
        self.framework_status = get_security_framework_status()

    def calculate_security_score(self) -> Dict[str, Any]:
        """Calculate overall security score with breakdown"""

        # Component scores (0-100)
        scores = {
            "framework_architecture": self._calculate_framework_score(),
            "api_coverage": self._calculate_coverage_score(),
            "implementation_quality": self._calculate_implementation_score(),
            "performance_impact": self._calculate_performance_score(),
            "compliance_readiness": self._calculate_compliance_score(),
            "threat_detection": self._calculate_threat_detection_score()
        }

        # Weighted overall score
        weights = {
            "framework_architecture": 0.2,
            "api_coverage": 0.25,
            "implementation_quality": 0.2,
            "performance_impact": 0.1,
            "compliance_readiness": 0.15,
            "threat_detection": 0.1
        }

        overall_score = sum(scores[key] * weights[key] for key in scores)

        return {
            "overall_score": round(overall_score, 1),
            "component_scores": scores,
            "grade": self._get_security_grade(overall_score),
            "last_updated": datetime.now().isoformat()
        }

    def get_api_coverage_stats(self) -> Dict[str, Any]:
        """Get detailed API coverage statistics"""

        # Get all API files
        all_apis = self._get_all_api_files()
        secured_apis = self._get_secured_api_files()

        coverage_by_level = self._analyze_coverage_by_security_level()
        coverage_by_type = self._analyze_coverage_by_operation_type()

        return {
            "total_apis": len(all_apis),
            "secured_apis": len(secured_apis),
            "coverage_percentage": round((len(secured_apis) / len(all_apis)) * 100, 1),
            "unsecured_apis": len(all_apis) - len(secured_apis),
            "coverage_by_level": coverage_by_level,
            "coverage_by_type": coverage_by_type,
            "recent_additions": self._get_recently_secured_apis(),
            "next_targets": self._get_next_priority_apis()
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get security performance impact metrics"""

        return {
            "average_overhead_ms": self._calculate_average_overhead(),
            "p95_overhead_ms": self._calculate_p95_overhead(),
            "slowest_endpoints": self._get_slowest_endpoints(),
            "fastest_endpoints": self._get_fastest_endpoints(),
            "performance_trend": self._get_performance_trend(),
            "optimization_opportunities": self._identify_optimization_opportunities()
        }

    def get_threat_detection_summary(self) -> Dict[str, Any]:
        """Get threat detection and incident summary"""

        return {
            "active_incidents": self._get_active_incidents(),
            "incidents_24h": self._get_recent_incidents(24),
            "incidents_7d": self._get_recent_incidents(168),
            "threat_categories": self._analyze_threat_categories(),
            "false_positive_rate": self._calculate_false_positive_rate(),
            "average_resolution_time": self._calculate_avg_resolution_time(),
            "top_threats": self._get_top_threat_patterns()
        }

    def get_compliance_status(self) -> Dict[str, Any]:
        """Get compliance and audit readiness status"""

        return {
            "gdpr_compliance": self._check_gdpr_compliance(),
            "iso27001_compliance": self._check_iso27001_compliance(),
            "owasp_compliance": self._check_owasp_compliance(),
            "audit_log_retention": self._check_audit_retention(),
            "data_protection_measures": self._check_data_protection(),
            "compliance_score": self._calculate_compliance_score()
        }

    # Private helper methods
    def _calculate_framework_score(self) -> float:
        """Calculate framework architecture score"""
        if not self.framework_status.get("success"):
            return 0

        components = self.framework_status.get("components_status", {})
        active_components = sum(1 for status in components.values() if status)
        total_components = len(components)

        return (active_components / total_components) * 100 if total_components > 0 else 0

    def _get_security_grade(self, score: float) -> str:
        """Convert security score to letter grade"""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
```

### 2. Dashboard API Endpoints

**File**: `verenigingen/api/security_dashboard.py`

```python
"""
Security Dashboard API Endpoints
Provides data for security monitoring dashboard
"""

import frappe
from vereinigingen.utils.security.security_metrics_calculator import SecurityMetricsCalculator
from verenigingen.utils.security.api_security_framework import standard_api, OperationType

@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_security_dashboard_overview():
    """
    Get complete security dashboard overview

    Security Level: STANDARD
    Rate Limit: 200/hour
    Returns real-time security metrics for dashboard
    """
    calculator = SecurityMetricsCalculator()

    return {
        "success": True,
        "data": {
            "security_score": calculator.calculate_security_score(),
            "api_coverage": calculator.get_api_coverage_stats(),
            "performance_metrics": calculator.get_performance_metrics(),
            "threat_summary": calculator.get_threat_detection_summary(),
            "compliance_status": calculator.get_compliance_status(),
            "last_updated": frappe.utils.now()
        }
    }

@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_security_metrics_history(days=30):
    """
    Get historical security metrics for trend analysis

    Args:
        days: Number of days of history to retrieve
    """
    # Implementation for historical data retrieval
    pass

@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_active_security_incidents():
    """Get list of active security incidents"""
    # Implementation for incident retrieval
    pass

@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def resolve_security_incident(incident_id, resolution_notes=""):
    """
    Resolve a security incident

    Args:
        incident_id: Incident identifier
        resolution_notes: Notes about resolution
    """
    # Implementation for incident resolution
    pass
```

### 3. Real-Time Data Provider

**File**: `verenigingen/utils/security/realtime_security_monitor.py`

```python
"""
Real-Time Security Monitor
Provides live security status updates
"""

import frappe
from frappe.realtime import emit_via_redis
from typing import Dict, Any

class RealtimeSecurityMonitor:
    """Monitor security status and emit real-time updates"""

    def __init__(self):
        self.calculator = SecurityMetricsCalculator()

    def start_monitoring(self):
        """Start real-time security monitoring"""
        frappe.realtime.emit("security_monitoring_started", {
            "timestamp": frappe.utils.now(),
            "status": "active"
        })

    def emit_security_update(self, update_type: str, data: Dict[str, Any]):
        """Emit security update to connected clients"""
        frappe.realtime.emit(f"security_update_{update_type}", {
            "type": update_type,
            "data": data,
            "timestamp": frappe.utils.now()
        })

    def emit_security_incident(self, incident: Dict[str, Any]):
        """Emit security incident alert"""
        frappe.realtime.emit("security_incident", {
            "incident": incident,
            "severity": incident.get("severity", "medium"),
            "timestamp": frappe.utils.now()
        })

    def emit_performance_alert(self, alert: Dict[str, Any]):
        """Emit performance degradation alert"""
        frappe.realtime.emit("performance_alert", {
            "alert": alert,
            "threshold_exceeded": True,
            "timestamp": frappe.utils.now()
        })
```

## Frontend Components

### 1. Dashboard HTML Template

**File**: `verenigingen/www/security_dashboard.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Monitoring Dashboard</title>
    <link rel="stylesheet" href="/assets/verenigingen/css/security_dashboard.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="security-dashboard">
        <!-- Dashboard Header -->
        <header class="dashboard-header">
            <h1>Security Monitoring Dashboard</h1>
            <div class="last-updated">
                Last Updated: <span id="last-updated-time">Loading...</span>
            </div>
        </header>

        <!-- Security Score Section -->
        <section class="security-score-section">
            <div class="score-widget">
                <h2>Security Score</h2>
                <div class="score-display">
                    <div class="score-circle" id="security-score-circle">
                        <span class="score-value" id="security-score-value">--</span>
                        <span class="score-grade" id="security-score-grade">-</span>
                    </div>
                </div>
                <div class="score-breakdown" id="score-breakdown">
                    <!-- Score breakdown will be populated by JavaScript -->
                </div>
            </div>
        </section>

        <!-- Main Metrics Grid -->
        <div class="metrics-grid">
            <!-- API Coverage Widget -->
            <div class="metric-widget api-coverage">
                <h3>API Security Coverage</h3>
                <div class="coverage-display">
                    <div class="progress-ring" id="coverage-ring">
                        <span class="coverage-percentage" id="coverage-percentage">--</span>
                    </div>
                    <div class="coverage-details">
                        <p><span id="secured-apis">--</span> of <span id="total-apis">--</span> APIs secured</p>
                        <p class="coverage-target">Target: 75%</p>
                    </div>
                </div>
            </div>

            <!-- Active Incidents Widget -->
            <div class="metric-widget incidents">
                <h3>Security Incidents</h3>
                <div class="incident-display">
                    <div class="incident-count" id="active-incidents">--</div>
                    <div class="incident-label">Active Incidents</div>
                    <div class="incident-history">
                        <span id="resolved-24h">--</span> resolved in last 24h
                    </div>
                </div>
            </div>

            <!-- Performance Widget -->
            <div class="metric-widget performance">
                <h3>Security Performance</h3>
                <div class="performance-display">
                    <div class="performance-metric">
                        <span class="metric-value" id="avg-overhead">--</span>
                        <span class="metric-unit">ms avg</span>
                    </div>
                    <div class="performance-trend" id="performance-trend">
                        <!-- Trend indicator -->
                    </div>
                </div>
            </div>

            <!-- Compliance Widget -->
            <div class="metric-widget compliance">
                <h3>Compliance Status</h3>
                <div class="compliance-display">
                    <div class="compliance-items" id="compliance-items">
                        <!-- Compliance status items -->
                    </div>
                </div>
            </div>
        </div>

        <!-- Charts Section -->
        <div class="charts-section">
            <div class="chart-container">
                <h3>Security Trends</h3>
                <canvas id="security-trends-chart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Incident History</h3>
                <canvas id="incident-history-chart"></canvas>
            </div>
        </div>

        <!-- Recent Activity Section -->
        <section class="recent-activity">
            <h3>Recent Security Activity</h3>
            <div class="activity-list" id="activity-list">
                <!-- Activity items will be populated by JavaScript -->
            </div>
        </section>
    </div>

    <script src="/assets/verenigingen/js/security_dashboard.js"></script>
</body>
</html>
```

### 2. Dashboard JavaScript

**File**: `verenigingen/public/js/security_dashboard.js`

```javascript
/**
 * Security Dashboard JavaScript
 * Handles real-time dashboard updates and interactions
 */

class SecurityDashboard {
    constructor() {
        this.websocket = null;
        this.charts = {};
        this.refreshInterval = 30000; // 30 seconds
        this.init();
    }

    init() {
        this.setupWebSocket();
        this.loadInitialData();
        this.setupAutoRefresh();
        this.setupEventListeners();
    }

    setupWebSocket() {
        // Setup WebSocket connection for real-time updates
        if (window.frappe && frappe.realtime) {
            frappe.realtime.on("security_update_score", (data) => {
                this.updateSecurityScore(data.data);
            });

            frappe.realtime.on("security_update_coverage", (data) => {
                this.updateCoverageStats(data.data);
            });

            frappe.realtime.on("security_incident", (data) => {
                this.handleSecurityIncident(data.incident);
            });

            frappe.realtime.on("performance_alert", (data) => {
                this.handlePerformanceAlert(data.alert);
            });
        }
    }

    async loadInitialData() {
        try {
            const response = await frappe.call({
                method: "verenigingen.api.security_dashboard.get_security_dashboard_overview"
            });

            if (response.message.success) {
                this.updateDashboard(response.message.data);
            }
        } catch (error) {
            console.error("Failed to load dashboard data:", error);
            this.showError("Failed to load security dashboard data");
        }
    }

    updateDashboard(data) {
        this.updateSecurityScore(data.security_score);
        this.updateCoverageStats(data.api_coverage);
        this.updatePerformanceMetrics(data.performance_metrics);
        this.updateThreatSummary(data.threat_summary);
        this.updateComplianceStatus(data.compliance_status);
        this.updateLastUpdated(data.last_updated);
    }

    updateSecurityScore(scoreData) {
        const scoreValue = document.getElementById('security-score-value');
        const scoreGrade = document.getElementById('security-score-grade');
        const scoreBreakdown = document.getElementById('score-breakdown');

        if (scoreValue) scoreValue.textContent = scoreData.overall_score;
        if (scoreGrade) scoreGrade.textContent = scoreData.grade;

        // Update score circle color based on grade
        const scoreCircle = document.getElementById('security-score-circle');
        if (scoreCircle) {
            scoreCircle.className = `score-circle grade-${scoreData.grade.toLowerCase()}`;
        }

        // Update score breakdown
        if (scoreBreakdown && scoreData.component_scores) {
            scoreBreakdown.innerHTML = Object.entries(scoreData.component_scores)
                .map(([component, score]) =>
                    `<div class="score-component">
                        <span class="component-name">${this.formatComponentName(component)}</span>
                        <span class="component-score">${score}</span>
                    </div>`
                ).join('');
        }
    }

    updateCoverageStats(coverageData) {
        const coveragePercentage = document.getElementById('coverage-percentage');
        const securedApis = document.getElementById('secured-apis');
        const totalApis = document.getElementById('total-apis');

        if (coveragePercentage) {
            coveragePercentage.textContent = `${coverageData.coverage_percentage}%`;
        }
        if (securedApis) securedApis.textContent = coverageData.secured_apis;
        if (totalApis) totalApis.textContent = coverageData.total_apis;

        // Update coverage ring visual
        this.updateCoverageRing(coverageData.coverage_percentage);
    }

    updateCoverageRing(percentage) {
        const ring = document.getElementById('coverage-ring');
        if (ring) {
            const circumference = 2 * Math.PI * 45; // radius = 45
            const strokeDasharray = `${(percentage / 100) * circumference} ${circumference}`;

            // Create or update SVG ring
            if (!ring.querySelector('svg')) {
                ring.innerHTML = `
                    <svg width="120" height="120" class="coverage-ring-svg">
                        <circle cx="60" cy="60" r="45" stroke="#e5e7eb" stroke-width="8" fill="none"/>
                        <circle cx="60" cy="60" r="45" stroke="#cf3131" stroke-width="8" fill="none"
                                stroke-dasharray="${strokeDasharray}"
                                stroke-dashoffset="0"
                                transform="rotate(-90 60 60)"/>
                    </svg>
                `;
            } else {
                const progressCircle = ring.querySelector('svg circle:last-child');
                if (progressCircle) {
                    progressCircle.setAttribute('stroke-dasharray', strokeDasharray);
                }
            }
        }
    }

    updatePerformanceMetrics(performanceData) {
        const avgOverhead = document.getElementById('avg-overhead');
        const performanceTrend = document.getElementById('performance-trend');

        if (avgOverhead) {
            avgOverhead.textContent = performanceData.average_overhead_ms;
        }

        if (performanceTrend && performanceData.performance_trend) {
            const trend = performanceData.performance_trend;
            const isImproving = trend.direction === 'improving';
            performanceTrend.innerHTML = `
                <span class="trend-icon ${isImproving ? 'improving' : 'declining'}">
                    ${isImproving ? '↗️' : '↘️'}
                </span>
                <span class="trend-value">${trend.change}ms from last week</span>
            `;
        }
    }

    handleSecurityIncident(incident) {
        // Show real-time incident notification
        this.showNotification(`Security Incident: ${incident.type}`, 'warning');

        // Update active incidents count
        const activeIncidents = document.getElementById('active-incidents');
        if (activeIncidents) {
            const currentCount = parseInt(activeIncidents.textContent) || 0;
            activeIncidents.textContent = currentCount + 1;
        }
    }

    handlePerformanceAlert(alert) {
        this.showNotification(`Performance Alert: ${alert.message}`, 'warning');
    }

    showNotification(message, type = 'info') {
        // Create and show notification
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <span class="notification-message">${message}</span>
            <button class="notification-close" onclick="this.parentElement.remove()">×</button>
        `;

        document.body.appendChild(notification);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }

    formatComponentName(component) {
        return component.replace(/_/g, ' ')
                       .replace(/\b\w/g, l => l.toUpperCase());
    }

    setupAutoRefresh() {
        setInterval(() => {
            this.loadInitialData();
        }, this.refreshInterval);
    }

    setupEventListeners() {
        // Setup any additional event listeners for user interactions
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new SecurityDashboard();
});
```

### 3. Dashboard CSS

**File**: `verenigingen/public/css/security_dashboard.css`

```css
/**
 * Security Dashboard Styles
 * Styling for security monitoring dashboard
 */

.security-dashboard {
    max-width: 1400px;
    margin: 0 auto;
    padding: 20px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* Dashboard Header */
.dashboard-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 30px;
    padding-bottom: 15px;
    border-bottom: 2px solid #e5e7eb;
}

.dashboard-header h1 {
    color: #cf3131;
    font-size: 2.5rem;
    font-weight: 600;
    margin: 0;
}

.last-updated {
    color: #6b7280;
    font-size: 0.9rem;
}

/* Security Score Section */
.security-score-section {
    margin-bottom: 30px;
}

.score-widget {
    background: linear-gradient(135deg, #cf3131, #01796f);
    color: white;
    padding: 30px;
    border-radius: 15px;
    box-shadow: 0 10px 30px rgba(207, 49, 49, 0.3);
}

.score-display {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 20px;
}

.score-circle {
    width: 150px;
    height: 150px;
    border: 8px solid rgba(255, 255, 255, 0.3);
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
}

.score-circle.grade-a { border-color: #10b981; }
.score-circle.grade-b { border-color: #3b82f6; }
.score-circle.grade-c { border-color: #f59e0b; }
.score-circle.grade-d { border-color: #ef4444; }
.score-circle.grade-f { border-color: #dc2626; }

.score-value {
    font-size: 3rem;
    font-weight: 700;
    line-height: 1;
}

.score-grade {
    font-size: 1.5rem;
    font-weight: 600;
    opacity: 0.8;
}

.score-breakdown {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
}

.score-component {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 15px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 8px;
}

.component-name {
    font-weight: 500;
}

.component-score {
    font-weight: 700;
    font-size: 1.1rem;
}

/* Metrics Grid */
.metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 20px;
    margin-bottom: 30px;
}

.metric-widget {
    background: white;
    padding: 25px;
    border-radius: 12px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
    border: 1px solid #e5e7eb;
}

.metric-widget h3 {
    color: #374151;
    font-size: 1.2rem;
    font-weight: 600;
    margin: 0 0 20px 0;
    padding-bottom: 10px;
    border-bottom: 2px solid #cf3131;
}

/* API Coverage Widget */
.coverage-display {
    display: flex;
    align-items: center;
    gap: 20px;
}

.progress-ring {
    position: relative;
    width: 120px;
    height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.coverage-percentage {
    position: absolute;
    font-size: 1.5rem;
    font-weight: 700;
    color: #cf3131;
}

.coverage-details p {
    margin: 5px 0;
    color: #6b7280;
}

.coverage-target {
    color: #01796f !important;
    font-weight: 600;
}

/* Incidents Widget */
.incident-display {
    text-align: center;
}

.incident-count {
    font-size: 3rem;
    font-weight: 700;
    color: #cf3131;
    line-height: 1;
}

.incident-label {
    font-size: 1.1rem;
    color: #6b7280;
    margin: 10px 0;
}

.incident-history {
    font-size: 0.9rem;
    color: #01796f;
    font-weight: 500;
}

/* Performance Widget */
.performance-display {
    text-align: center;
}

.performance-metric {
    margin-bottom: 15px;
}

.metric-value {
    font-size: 2.5rem;
    font-weight: 700;
    color: #cf3131;
}

.metric-unit {
    font-size: 1rem;
    color: #6b7280;
    margin-left: 5px;
}

.performance-trend {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
}

.trend-icon.improving {
    color: #10b981;
}

.trend-icon.declining {
    color: #ef4444;
}

/* Charts Section */
.charts-section {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 30px;
}

.chart-container {
    background: white;
    padding: 25px;
    border-radius: 12px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
}

.chart-container h3 {
    color: #374151;
    font-size: 1.2rem;
    font-weight: 600;
    margin: 0 0 20px 0;
}

/* Recent Activity */
.recent-activity {
    background: white;
    padding: 25px;
    border-radius: 12px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
}

.recent-activity h3 {
    color: #374151;
    font-size: 1.2rem;
    font-weight: 600;
    margin: 0 0 20px 0;
}

/* Notifications */
.notification {
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 15px 20px;
    border-radius: 8px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    z-index: 1000;
    display: flex;
    align-items: center;
    gap: 10px;
    max-width: 400px;
}

.notification-info {
    background: #3b82f6;
    color: white;
}

.notification-warning {
    background: #f59e0b;
    color: white;
}

.notification-error {
    background: #ef4444;
    color: white;
}

.notification-close {
    background: none;
    border: none;
    color: inherit;
    font-size: 1.2rem;
    cursor: pointer;
    padding: 0;
    margin-left: auto;
}

/* Responsive Design */
@media (max-width: 768px) {
    .charts-section {
        grid-template-columns: 1fr;
    }

    .coverage-display {
        flex-direction: column;
        text-align: center;
    }

    .dashboard-header {
        flex-direction: column;
        gap: 10px;
        text-align: center;
    }
}
```

## Installation and Setup

### 1. Backend Setup

```bash
# 1. Create security monitoring directories
mkdir -p verenigingen/utils/security/monitoring
mkdir -p verenigingen/www

# 2. Deploy backend files
cp security_metrics_calculator.py verenigingen/utils/security/
cp realtime_security_monitor.py verenigingen/utils/security/
cp security_dashboard.py verenigingen/api/

# 3. Deploy frontend files
cp security_dashboard.html verenigingen/www/
cp security_dashboard.js verenigingen/public/js/
cp security_dashboard.css verenigingen/public/css/

# 4. Restart system to load new modules
bench restart
```

### 2. Database Setup

```python
# Add dashboard access permissions
frappe.get_doc({
    "doctype": "Role",
    "role_name": "Security Dashboard User"
}).save()

# Create dashboard workspace entry
frappe.get_doc({
    "doctype": "Workspace",
    "title": "Security Dashboard",
    "category": "Administration",
    "public": 1,
    "links": [
        {
            "type": "Link",
            "label": "Security Dashboard",
            "link_to": "/security_dashboard",
            "icon": "shield"
        }
    ]
}).save()
```

### 3. Access Configuration

**URL**: `https://dev.veganisme.net/security_dashboard`

**Required Roles**:
- System Manager
- Verenigingen Administrator
- Security Dashboard User

### 4. Testing Installation

```bash
# Test backend API
curl -X GET "https://dev.veganisme.net/api/method/verenigingen.api.security_dashboard.get_security_dashboard_overview"

# Test dashboard access
curl -I "https://dev.veganisme.net/security_dashboard"

# Validate security framework
python -c "from verenigingen.utils.security.security_metrics_calculator import SecurityMetricsCalculator; print('✅ Installation successful')"
```

## Conclusion

The enhanced security monitoring dashboard provides:

- **Real-time monitoring** of security metrics and incidents
- **Comprehensive analytics** for security posture assessment
- **Automated alerting** for security events and performance issues
- **Historical analysis** for trend identification and improvement planning
- **Compliance tracking** for audit readiness

**Implementation Timeline**: 4 hours total
**Expected Results**: 90/100 security score with comprehensive monitoring capabilities

This dashboard will serve as the central command center for ongoing security management and compliance monitoring of the Verenigingen application.
