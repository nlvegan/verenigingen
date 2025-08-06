# Donation Campaign Management User Guide

## Overview

The Donation Campaign system provides comprehensive tools for planning, executing, and tracking fundraising campaigns within your organization. This enhanced system now includes powerful accounting integration features that streamline financial reporting and project management.

## Key Features

### Campaign Management
- **Flexible Campaign Types**: Support for Annual Giving, Capital Campaigns, Emergency Relief, Project Funding, Endowment, Event, and custom campaign types
- **Goal Setting**: Set monetary and donor count targets with automatic progress tracking
- **Visibility Controls**: Configure public visibility, website display, and donor privacy settings
- **Rich Content**: Add campaign stories, impact statements, images, and videos

### Accounting Integration (NEW)
- **Automatic Dimension Generation**: Unique accounting dimension codes auto-generated from campaign names
- **Project Integration**: Optional ERPNext Project linking for comprehensive activity tracking
- **Financial Reporting**: Consolidated view of campaign income, expenses, and GL entries
- **Donation Inheritance**: All campaign donations automatically inherit accounting dimensions

### Progress Tracking
- **Real-time Updates**: Progress automatically calculated from linked donations
- **Multiple Metrics**: Track monetary progress, donor count, and average donation amounts
- **Completion Percentages**: Visual progress indicators based on your goals

## Getting Started

### Creating a Campaign

1. **Navigate to Donation Campaign**
   - Go to `Vereinigingen > Donation Campaign > New`
   - Or use the quick entry: `Ctrl+G` → type "Donation Campaign"

2. **Basic Information**
   - **Campaign Name**: Enter a descriptive name (this will auto-generate the accounting dimension)
   - **Campaign Type**: Select the appropriate type from the dropdown
   - **Status**: Start with "Draft", change to "Active" when ready to launch
   - **Start/End Dates**: Set your campaign timeline
   - **Description**: Brief summary for quick reference

3. **Set Goals**
   - **Monetary Goal**: Target amount to raise
   - **Donor Goal**: Target number of unique donors
   - **Minimum Donation**: Set a minimum threshold (optional)
   - **Suggested Amounts**: Comma-separated values (e.g., "25,50,100,250")

### Accounting Integration Setup

#### Understanding Accounting Dimensions

When you create a campaign, the system automatically generates a unique **Campaign Dimension Value**. This code:

- **Auto-generates** from your campaign name (e.g., "Spring Appeal 2025" → "SPRING_APPEAL_2025")
- **Ensures uniqueness** across all campaigns
- **Follows accounting standards** (uppercase, alphanumeric, max 50 characters)
- **Links all donations** to this dimension for financial reporting

**Example Dimension Generations:**
```
Campaign Name: "Emergency Relief Fund"
→ Dimension Value: "EMERGENCY_RELIEF_FUND"

Campaign Name: "2025 Capital Campaign - Building Fund"
→ Dimension Value: "2025_CAPITAL_CAMPAIGN_BUILDING_FUND"

Campaign Name: "Special Characters & Symbols!"
→ Dimension Value: "SPECIAL_CHARACTERS_SYMBOLS"
```

#### Creating a Campaign Project (Optional)

For campaigns requiring task management and expense tracking:

1. **After saving your campaign**, click the "Create Project" button
2. **Project Details** are auto-populated:
   - Name: "Campaign: [Your Campaign Name]"
   - Start/End dates from campaign
   - Type: External
   - Status: Open

3. **Project Benefits**:
   - Track campaign-related tasks and milestones
   - Monitor campaign expenses and budgets
   - Generate project reports and timelines
   - Link team assignments to specific campaigns

## Campaign Management Workflows

### Simple Campaign (Accounting Dimensions Only)

**Best for**: Basic fundraising campaigns with straightforward financial tracking

**Setup Process**:
1. Create campaign with basic information
2. Set monetary and donor goals
3. Leave project field empty
4. Launch campaign (status = "Active")

**What You Get**:
- All donations automatically tagged with campaign dimension
- Financial reports filtered by campaign
- GL entries linked to campaign
- Progress tracking and donor analytics

### Complex Campaign (Dimensions + Project)

**Best for**: Multi-phase campaigns, events, or campaigns with significant planning requirements

**Setup Process**:
1. Create campaign with full details
2. Set comprehensive goals and timeline
3. Create linked project via "Create Project" button
4. Add project tasks and milestones
5. Launch campaign

**What You Get**:
- Everything from simple campaign, plus:
- Task management and milestone tracking
- Expense tracking and budget management
- Project timeline and completion metrics
- Team assignment and responsibility tracking

### Campaign Launch Checklist

Before changing status to "Active":
- ✅ Campaign name is final (affects accounting dimension)
- ✅ Goals are set and realistic
- ✅ Start and end dates are confirmed
- ✅ Description and content are complete
- ✅ Visibility settings are configured
- ✅ If using projects, project is created and configured
- ✅ Team members have necessary permissions

## Donation Processing

### How Donations Inherit Campaign Settings

When a donation is linked to your campaign:

1. **Automatic Dimension Inheritance**:
   ```
   Campaign: "Annual Appeal 2025" (Dimension: "ANNUAL_APPEAL_2025")
   → Donation: Automatically tagged with "ANNUAL_APPEAL_2025"
   → Sales Invoice: Includes campaign dimension
   → Journal Entry: Tagged with campaign dimension
   ```

2. **Project Linking**:
   ```
   Campaign with Project: "Event Fundraiser" → "Project: Event Planning"
   → Donation: Linked to both campaign and project
   → Expenses: Can be tracked against the same project
   → Reports: Show campaign ROI including costs
   ```

### Donation Workflow Integration

The system automatically:
- **Updates progress** when donations are processed
- **Calculates metrics** (total raised, donor count, averages)
- **Tags financial entries** with campaign information
- **Maintains donor privacy** based on campaign settings

## Progress Monitoring and Reporting

### Real-Time Dashboard

Access campaign progress through:
- **Campaign List View**: Quick overview of all campaigns
- **Campaign Detail View**: Comprehensive metrics and charts
- **Dashboard Widgets**: Key performance indicators

### Key Metrics Tracked

1. **Financial Progress**:
   - Total amount raised vs. goal
   - Progress percentage
   - Average donation amount
   - Largest and smallest donations

2. **Donor Engagement**:
   - Total number of donors vs. goal
   - Unique donor count
   - Repeat donor percentage
   - New donor acquisition

3. **Campaign Performance**:
   - Donations per day/week/month
   - Peak donation periods
   - Donation source analysis
   - Geographic distribution (if available)

### Reporting Capabilities

#### Campaign-Specific Reports

1. **Donation Summary**:
   - All donations for the campaign
   - Donor information (respecting privacy settings)
   - Payment methods and status
   - Date and amount analysis

2. **Financial Analysis**:
   - Income breakdown by source
   - Campaign expenses (if using projects)
   - Net fundraising effectiveness
   - Cost per donor acquired

3. **Project Reports** (when applicable):
   - Task completion status
   - Expense tracking
   - Budget vs. actual analysis
   - Timeline performance

#### Standard Frappe Reports

Access through Reports menu:
- **Donation Campaign Summary**: Overview of all campaigns
- **Campaign Performance Analysis**: Comparative metrics
- **Accounting Dimension Reports**: Financial breakdown by campaign
- **Project Reports**: Task and expense analysis

## Best Practices

### Campaign Planning

1. **Naming Conventions**:
   - Use clear, consistent naming (affects accounting dimensions)
   - Include year for annual campaigns
   - Avoid special characters or very long names
   - Consider how the name will appear in financial reports

2. **Goal Setting**:
   - Base monetary goals on historical data and capacity
   - Set stretch goals that are ambitious but achievable
   - Consider both donor count and amount targets
   - Plan for different donation levels

3. **Timeline Management**:
   - Allow adequate setup time before launch
   - Plan for key dates and milestones
   - Consider seasonal factors and organizational calendar
   - Build in buffer time for unexpected challenges

### Accounting Integration

1. **Dimension Management**:
   - Review auto-generated dimensions before finalizing
   - Ensure dimensions align with your chart of accounts
   - Coordinate with finance team on naming conventions
   - Document dimension meanings for future reference

2. **Project Integration**:
   - Use projects for campaigns with significant planning requirements
   - Create projects only when task/expense tracking is needed
   - Establish clear project ownership and responsibility
   - Regular project review and updates

3. **Financial Reporting**:
   - Regular review of campaign financial data
   - Reconcile donation totals with accounting entries
   - Monitor campaign ROI and cost-effectiveness
   - Prepare periodic financial summaries

### Donor Management

1. **Privacy and Transparency**:
   - Respect donor anonymity preferences
   - Configure visibility settings appropriately
   - Provide clear information about fund usage
   - Regular communication with donors

2. **Engagement Strategies**:
   - Use progress updates to encourage additional giving
   - Recognize major donors appropriately
   - Share impact stories and outcomes
   - Maintain donor database accuracy

## Configuration Options

### Visibility Settings

- **Is Public**: Campaign appears in public listings
- **Show on Website**: Display on organization website
- **Show Progress Bar**: Visual progress indicator on public pages
- **Allow Anonymous Donations**: Accept donations without donor identification
- **Show Donor List**: Public display of donor names (non-anonymous)
- **Show Recent Donations**: Display recent donation activity

### Suggested Donation Amounts

Configure suggested amounts to guide donor decisions:
- **Format**: Comma-separated values (e.g., "25,50,100,250,500")
- **Strategy**: Include range from small to major gift levels
- **Psychology**: End with amounts slightly above target average
- **Flexibility**: Always allow custom amounts

### Campaign Types

Choose the most appropriate type for reporting and categorization:
- **Annual Giving**: Regular, recurring fundraising campaigns
- **Capital Campaign**: Major facility or equipment fundraising
- **Emergency Relief**: Crisis response and urgent needs
- **Project Funding**: Specific program or initiative funding
- **Endowment**: Long-term investment fund building
- **Event**: Fundraising connected to specific events
- **Other**: Custom campaign types

## Troubleshooting

### Common Issues

1. **Dimension Generation Problems**:
   - **Issue**: Dimension value seems incorrect or too short
   - **Solution**: Manually edit the accounting_dimension_value field before saving
   - **Prevention**: Use clear, alphanumeric campaign names

2. **Project Creation Failures**:
   - **Issue**: "Create Project" button fails
   - **Solution**: Ensure Project DocType is properly installed and configured
   - **Check**: Campaign must have a start_date before project creation

3. **Progress Not Updating**:
   - **Issue**: Donation totals don't reflect in campaign progress
   - **Solution**: Ensure donations are marked as "Paid" and have docstatus = 1
   - **Check**: Campaign name must exactly match in donation records

4. **Permission Issues**:
   - **Issue**: Users cannot access campaign features
   - **Solution**: Verify role assignments and permissions
   - **Check**: Ensure appropriate roles have access to Donation Campaign doctype

### Error Messages and Solutions

| Error Message | Cause | Solution |
|---------------|--------|----------|
| "End date cannot be before start date" | Invalid date range | Correct the start/end date values |
| "Monetary goal must be positive" | Negative goal amount | Enter positive goal values |
| "Project with name already exists" | Duplicate project name | Use a different project name or link existing project |
| "Campaign already has a project linked" | Trying to create second project | Use existing project or remove current link first |
| "Please select a Donor" | Missing donor information | Ensure donor exists or create new donor record |

### Performance Considerations

1. **Large Campaigns**:
   - Progress updates may take longer with many donations
   - Consider using background jobs for very large campaigns
   - Regular cleanup of old campaign data

2. **Reporting Speed**:
   - Financial reports may be slow for campaigns with extensive transactions
   - Use date filters to limit report scope
   - Consider archived campaigns for historical data

## Integration Points

### ERPNext Integration

- **Projects**: Full integration with ERPNext Project management
- **Accounts**: GL entries and financial reporting
- **Sales**: Sales invoice generation for donations
- **Reports**: Standard ERPNext reporting framework

### Website Integration

- **Public Pages**: Campaign display on organization website
- **Donation Forms**: Web form integration for online donations
- **Progress Display**: Real-time progress updates on public pages
- **Social Sharing**: Campaign promotion through social media

### Third-Party Systems

- **Payment Processing**: Integration with payment gateways
- **Email Marketing**: Campaign communication systems
- **Donor Management**: External CRM system integration
- **Financial Systems**: eBoekhouden and other accounting platforms

## Migration Guide

### Existing Campaigns

If you have existing campaigns without accounting integration:

1. **Automatic Updates**:
   - Existing campaigns will auto-generate dimension values on next save
   - No data loss or disruption to existing functionality
   - Progress tracking continues normally

2. **Optional Enhancements**:
   - Review and adjust auto-generated dimension values
   - Create projects for campaigns that would benefit
   - Update campaign content and settings

3. **Best Practices**:
   - Review all campaign names for consistency
   - Plan project creation for complex campaigns
   - Update team training on new features

### Data Integrity

- All existing donation links remain intact
- Historical reporting continues to function
- New features are additive, not replacement
- Rollback capabilities maintained

## Advanced Features

### Custom Dimension Values

While the system auto-generates dimension values, you can customize them:

1. **Manual Override**: Edit the "Campaign Dimension Value" field before saving
2. **Naming Standards**: Follow your organization's accounting conventions
3. **Length Limits**: Maximum 50 characters, alphanumeric and underscore/hyphen only
4. **Uniqueness**: System ensures no duplicate dimension values

### Batch Operations

For multiple campaigns:

1. **Bulk Creation**: Use data import tools for multiple campaigns
2. **Mass Updates**: Update multiple campaign settings simultaneously
3. **Reporting**: Generate comparative reports across campaigns

### API Integration

Developers can access campaign data programmatically:

```python
# Get campaign progress
campaign = frappe.get_doc("Donation Campaign", "campaign_name")
progress = campaign.get_project_summary()

# Get financial data
accounting_data = campaign.get_accounting_entries(from_date, to_date)

# Create campaign programmatically
campaign = frappe.new_doc("Donation Campaign")
campaign.campaign_name = "API Created Campaign"
campaign.campaign_type = "Project Funding"
campaign.start_date = "2025-01-01"
campaign.insert()
```

## Conclusion

The enhanced Donation Campaign system provides a comprehensive platform for fundraising management with seamless accounting integration. Whether you're running simple donation drives or complex multi-phase campaigns, the system adapts to your needs while maintaining accurate financial tracking and reporting.

For technical implementation details, see the [Technical Documentation](/docs/technical/accounting-integration.md).

For system administration guidance, see the [Admin Guide](/docs/ADMIN_GUIDE.md).
