# Membership Analytics Technical Implementation Guide

## Architecture Overview

The Membership Analytics system is built using the Frappe Framework and consists of several interconnected components:

### Core Components

1. **Page Module** (`membership_analytics/`)
   - `membership_analytics.py`: Core analytics calculations and API endpoints
   - `membership_analytics.js`: Frontend controller and UI logic
   - `membership_analytics.html`: Dashboard template
   - `predictive_analytics.py`: Machine learning and forecasting functions

2. **DocTypes**
   - `Membership Goal`: Goal tracking and achievement calculation
   - `Membership Analytics Snapshot`: Historical data storage
   - `Analytics Alert Rule`: Automated monitoring configuration
   - `Analytics Alert Log`: Alert history tracking
   - `Analytics Alert Recipient`: Alert recipient configuration (child table)
   - `Analytics Alert Action`: Automated action configuration (child table)

3. **Scheduled Jobs**
   - Daily snapshot creation
   - Hourly alert checking

## Key Implementation Details

### 1. Data Aggregation

#### SQL Query Optimization
```python
# Example: Efficient member count with filtering
def get_member_count(filters):
    conditions = build_filter_conditions(filters)
    return frappe.db.sql("""
        SELECT COUNT(DISTINCT m.name) as count
        FROM `tabMember` m
        WHERE m.status = 'Active' {conditions}
    """.format(conditions=conditions))[0][0]
```

#### Filter Building
The `build_filter_conditions()` function dynamically constructs SQL WHERE clauses:
```python
def build_filter_conditions(filters):
    conditions = []

    if filters.get("chapter"):
        conditions.append(f"current_chapter_display = '{filters['chapter']}'")

    if filters.get("age_group"):
        age_condition = get_age_group_condition(filters["age_group"])
        conditions.append(age_condition)

    return " AND " + " AND ".join(conditions) if conditions else ""
```

### 2. Predictive Analytics Implementation

#### Polynomial Regression for Forecasting
```python
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

def forecast_member_growth(months_ahead=12):
    # Get historical data
    historical_data = get_historical_member_counts()

    # Prepare data for regression
    X = np.array(range(len(historical_data))).reshape(-1, 1)
    y = np.array([d.count for d in historical_data])

    # Apply polynomial features for better fit
    poly = PolynomialFeatures(degree=2)
    X_poly = poly.fit_transform(X)

    # Train model
    model = LinearRegression()
    model.fit(X_poly, y)

    # Generate predictions
    future_X = np.array(range(len(historical_data),
                             len(historical_data) + months_ahead)).reshape(-1, 1)
    future_X_poly = poly.transform(future_X)
    predictions = model.predict(future_X_poly)

    return predictions
```

#### Risk Scoring Algorithm
```python
def calculate_member_risk_score(member):
    risk_factors = {
        "payment_failed": 0.3,
        "no_recent_activity": 0.2,
        "membership_expiring": 0.2,
        "no_engagement": 0.15,
        "complaint_filed": 0.15
    }

    score = 0
    factors = []

    if has_payment_failures(member):
        score += risk_factors["payment_failed"]
        factors.append("Payment failures")

    if days_since_last_activity(member) > 90:
        score += risk_factors["no_recent_activity"]
        factors.append("No recent activity")

    return min(score, 0.95), factors
```

### 3. Real-time Chart Rendering

#### Frappe Charts Integration
```javascript
render_growth_chart(data) {
    const chartData = {
        labels: data.map(d => d.period),
        datasets: [{
            name: "New Members",
            values: data.map(d => d.new_members),
            chartType: 'bar'
        }, {
            name: "Net Growth",
            values: data.map(d => d.net_growth),
            chartType: 'line'
        }]
    };

    this.charts.growth = new frappe.Chart("#growth-trend-chart", {
        data: chartData,
        type: 'axis-mixed',
        height: 300,
        colors: ['#5e64ff', '#2ecc71']
    });
}
```

### 4. Alert System Architecture

#### Alert Checking Flow
1. Scheduler triggers `check_all_active_alerts()` hourly
2. Each alert rule checks if it should run based on frequency
3. Metric value is calculated
4. Condition is evaluated
5. If triggered, actions are executed:
   - Notifications sent
   - Tasks created
   - Webhooks called
   - Custom scripts executed

#### Custom Script Execution
```python
def execute_custom_script(self, alert_data):
    context = {
        "alert_data": alert_data,
        "frappe": frappe,
        "rule": self
    }
    exec(self.custom_script, context)
```

### 5. Performance Optimizations

#### Caching Strategy
- Dashboard data is calculated on-demand
- Client-side caching for static filters
- Snapshot data used for historical comparisons

#### Query Optimization
- Proper indexes on frequently queried fields:
  ```sql
  CREATE INDEX idx_member_status_since ON `tabMember` (status, member_since);
  CREATE INDEX idx_membership_status_type ON `tabMembership` (status, membership_type);
  ```

#### Batch Processing
- Snapshots created in batches
- Alert checks use efficient bulk queries

### 6. Security Implementation

#### API Whitelist
All exposed functions use the `@frappe.whitelist()` decorator:
```python
@frappe.whitelist()
def get_dashboard_data(year=None, period="year", compare_previous=False, filters=None):
    # Permission check
    if not has_analytics_permission():
        frappe.throw(_("Insufficient permissions"))

    # Input validation
    if filters and isinstance(filters, str):
        filters = json.loads(filters)

    # Process request...
```

#### Permission Checks
```python
def has_analytics_permission():
    allowed_roles = [
        "Verenigingen Administrator",
        "Verenigingen Manager",
        "National Board Member"
    ]
    return bool(set(frappe.get_roles()) & set(allowed_roles))
```

### 7. Data Export Implementation

#### Excel Export with Multiple Sheets
```python
def export_to_excel(data):
    from frappe.utils.xlsxutils import make_xlsx

    sheets = {
        "Summary": prepare_summary_sheet(data),
        "Growth Trend": prepare_growth_sheet(data),
        "Segmentation": prepare_segmentation_sheet(data),
        "Cohort Analysis": prepare_cohort_sheet(data)
    }

    xlsx_data = make_xlsx(sheets, "Membership Analytics")

    frappe.response['filename'] = f'membership_analytics_{frappe.utils.today()}.xlsx'
    frappe.response['filecontent'] = xlsx_data.getvalue()
    frappe.response['type'] = 'binary'
```

### 8. Frontend State Management

#### Filter State Management
```javascript
class MembershipAnalytics {
    constructor(page) {
        this.filters = {
            year: new Date().getFullYear(),
            period: 'year',
            compare_previous: false,
            chapter: null,
            region: null,
            membership_type: null,
            age_group: null,
            payment_method: null
        };
    }

    refresh_dashboard() {
        frappe.call({
            method: 'get_dashboard_data',
            args: { filters: this.filters },
            callback: (r) => this.render_dashboard(r.message)
        });
    }
}
```

## Testing Strategy

### Unit Tests
1. **Permission Tests** (`test_membership_analytics_permissions.py`)
   - Role-based access control
   - Data isolation
   - API security

2. **Functionality Tests** (`test_membership_analytics_functionality.py`)
   - Calculation accuracy
   - Data aggregation
   - Export functionality
   - Alert system

### Test Data Generation
```python
def create_test_members(count=50):
    for i in range(count):
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": f"Test{i}",
            "last_name": "Member",
            "status": "Active",
            "member_since": add_months(getdate(), -random.randint(0, 36)),
            "birth_date": add_years(getdate(), -random.randint(20, 70)),
            "payment_method": random.choice(["Bank Transfer", "Direct Debit"])
        })
        member.insert(ignore_permissions=True)
```

## Deployment Considerations

### Database Migrations
Add to `patches.txt`:
```
verenigingen.patches.v1_0.add_membership_analytics
```

### Scheduler Configuration
Add to `hooks.py`:
```python
scheduler_events = {
    "daily": [
        "membership_analytics_snapshot.create_scheduled_snapshots"
    ],
    "hourly": [
        "analytics_alert_rule.check_all_active_alerts"
    ]
}
```

### Performance Monitoring
- Monitor query execution time
- Track snapshot creation duration
- Alert check performance
- Export generation time

## Extending the System

### Adding New Metrics
1. Add metric to `Analytics Alert Rule` options
2. Implement calculation in `get_metric_value()`
3. Add to dashboard if needed
4. Update documentation

### Custom Visualizations
1. Add chart container in HTML
2. Implement data preparation in Python
3. Add rendering logic in JavaScript
4. Update export functions

### Integration Points
- Webhook payload standardization
- API endpoint documentation
- Authentication headers
- Rate limiting considerations

## Troubleshooting Guide

### Common Issues

#### "No data available"
- Check member records exist
- Verify date calculations
- Confirm permissions
- Check filter conditions

#### Performance Issues
```sql
-- Check slow queries
SHOW PROCESSLIST;

-- Analyze query execution
EXPLAIN SELECT ...;

-- Add missing indexes
CREATE INDEX idx_name ON table(column);
```

#### Alert Not Triggering
1. Verify `is_active` is true
2. Check `last_checked` timestamp
3. Validate metric calculation
4. Test condition logic
5. Review error logs

## Code Quality Standards

### Python
- Type hints where applicable
- Docstrings for all functions
- Error handling with specific exceptions
- Input validation
- SQL injection prevention

### JavaScript
- ES6+ syntax
- Proper error handling
- Consistent naming conventions
- Avoid global variables
- Use Frappe's built-in utilities

### SQL
- Parameterized queries
- Proper indexing
- Avoid N+1 queries
- Use JOINs efficiently
- Consider query complexity

## Maintenance Procedures

### Regular Tasks
1. **Monthly**
   - Review alert configurations
   - Check snapshot sizes
   - Validate calculations

2. **Quarterly**
   - Archive old snapshots
   - Optimize database
   - Review permissions

3. **Annually**
   - Update forecasting models
   - Review metric definitions
   - Performance audit
