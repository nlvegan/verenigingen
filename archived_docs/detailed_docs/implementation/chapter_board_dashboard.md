# Chapter Board Dashboard Implementation

## Overview

The Chapter Board Dashboard provides real-time metrics and visual analytics for board members to monitor their chapter's performance and member data.

## Dashboard Details

- **Name**: Chapter Board Dashboard
- **Module**: Verenigingen
- **Type**: Standard Dashboard
- **Access**: Board members only

## Components

### Number Cards
Real-time metric cards displaying:
- Active Members
- New Members (This Month)
- Pending Applications
- Active Volunteers
- Monthly Expenses
- Chapter Health Score

### Charts
Visual analytics including:
- Member Growth Trend
- Member Distribution by Type
- Volunteer Activity
- Financial Overview

## Access Control

- **Role-based**: Only users with board member roles in chapters have access
- **Chapter-specific**: Board members see data only for their assigned chapters
- **Multi-chapter support**: Board members in multiple chapters can view consolidated data

## URLs and Navigation

### Direct Access
- Desktop/Mobile: `https://[site]/app/dashboard-view/Chapter%20Board%20Dashboard`
- API Endpoint: `/api/method/verenigingen.api.chapter_dashboard.get_dashboard_data`

### Navigation Steps
1. Login to the system
2. Navigate to Desk → Dashboards
3. Click on "Chapter Board Dashboard"

### Alternative Access
- Use the direct URL: `/app/dashboard-view/Chapter%20Board%20Dashboard`
- Access via mobile app with same URL

## Features

1. **Real-time Metrics**: Live updating number cards with current chapter statistics
2. **Visual Analytics**: Interactive charts for trend analysis and data visualization
3. **Board Member Access Control**: Automatic filtering based on user's board member status
4. **Multi-chapter Support**: Consolidated view for board members serving multiple chapters
5. **Native Frappe UI**: Integrated with Frappe's dashboard framework
6. **Mobile Responsive**: Fully functional on mobile devices
7. **Auto-refresh**: Data updates automatically without page reload

## Technical Implementation

### Backend Components
- `verenigingen/api/chapter_dashboard.py`: Dashboard data API
- `verenigingen/utils/dashboard_permissions.py`: Access control logic
- `verenigingen/hooks.py`: Dashboard registration

### Frontend Components
- Frappe Dashboard framework
- Number Card widgets
- Chart widgets with real-time data binding

### Security
- Server-side permission checks
- Chapter-based data isolation
- Role verification on each request

## Maintenance

### Adding New Metrics
1. Create new Number Card in Dashboard Builder
2. Add corresponding data method in `chapter_dashboard.py`
3. Update permission checks if needed

### Modifying Charts
1. Edit chart configuration in Dashboard Builder
2. Update data source methods
3. Test with sample data

### Performance Optimization
- Cached queries for frequently accessed data
- Indexed database fields for chapter relationships
- Efficient aggregation queries

## Troubleshooting

### Common Issues

1. **Dashboard Not Visible**
   - Verify user has board member role
   - Check chapter assignment
   - Clear browser cache

2. **Data Not Loading**
   - Check API endpoint accessibility
   - Verify database permissions
   - Review error logs

3. **Incorrect Data**
   - Validate chapter filters
   - Check date range parameters
   - Verify aggregation logic

### Debug Commands
```python
# Check user's board access
frappe.get_list("Chapter Member", filters={"member": member_id, "role": ["like", "%Board%"]})

# Verify dashboard exists
frappe.get_doc("Dashboard", "Chapter Board Dashboard")

# Test data API
frappe.call("verenigingen.api.chapter_dashboard.get_dashboard_data")
```

## Related Documentation
- [Chapter Management](../features/chapter_management.md)
- [Board Member Roles](../features/board_roles.md)
- [Dashboard Permissions](../security/dashboard_permissions.md)
