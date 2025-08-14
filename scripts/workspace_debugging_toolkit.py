#!/usr/bin/env python3
"""
Workspace Debugging Toolkit
Comprehensive toolkit for diagnosing and fixing workspace issues

Usage examples:
    # Analyze workspace structure
    bench --site [site] execute "scripts.workspace_debugging_toolkit.analyze" --args "['Verenigingen']"
    
    # Validate all links
    bench --site [site] execute "scripts.workspace_debugging_toolkit.validate" --args "['Verenigingen']"
    
    # Full diagnostic
    bench --site [site] execute "scripts.workspace_debugging_toolkit.diagnose" --args "['Verenigingen']"
"""

import frappe

def analyze(workspace_name):
    """Quick analysis of workspace structure"""
    from verenigingen.utils.workspace_analyzer import print_analysis
    return print_analysis(workspace_name)

def validate(workspace_name):
    """Validate workspace links"""
    from verenigingen.utils.workspace_link_validator import print_link_validation
    return print_link_validation(workspace_name)

def diagnose(workspace_name):
    """Full diagnostic of workspace"""
    print(f"🔍 Full Diagnostic: {workspace_name}")
    print("=" * 50)
    
    # 1. Basic workspace info
    workspace = frappe.get_doc('Workspace', workspace_name)
    print(f"Workspace: {workspace.label}")
    print(f"Module: {workspace.module}")
    print(f"Public: {workspace.public}")
    print(f"Hidden: {workspace.is_hidden}")
    print()
    
    # 2. Structure analysis
    print("📊 STRUCTURE ANALYSIS")
    print("-" * 20)
    analyze(workspace_name)
    
    # 3. Link validation
    print("🔗 LINK VALIDATION")
    print("-" * 20)
    validate(workspace_name)
    
    # 4. Content statistics
    import json
    content = json.loads(workspace.content)
    
    print("📈 CONTENT STATISTICS")
    print("-" * 20)
    print(f"Total content items: {len(content)}")
    
    item_types = {}
    for item in content:
        item_type = item.get('type', 'unknown')
        item_types[item_type] = item_types.get(item_type, 0) + 1
    
    for item_type, count in item_types.items():
        print(f"  {item_type}: {count}")
    print()
    
    # 5. Database statistics
    print("🗄️  DATABASE STATISTICS")
    print("-" * 20)
    
    link_stats = frappe.db.sql("""
        SELECT type, COUNT(*) as count
        FROM `tabWorkspace Link`
        WHERE parent = %s
        GROUP BY type
        ORDER BY type
    """, workspace_name, as_dict=True)
    
    for stat in link_stats:
        print(f"  {stat.type}: {stat.count}")
    print()
    
    return True

def fix_content(workspace_name, dry_run=True):
    """Fix workspace content issues"""
    from verenigingen.utils.workspace_content_fixer import fix_workspace_content
    return fix_workspace_content(workspace_name, dry_run)

def backup_content(workspace_name):
    """Create backup of workspace content"""
    from verenigingen.utils.workspace_content_fixer import create_content_backup
    return create_content_backup(workspace_name)

def list_all_workspaces():
    """List all workspaces with basic info"""
    workspaces = frappe.get_all('Workspace', 
        fields=['name', 'label', 'module', 'public', 'is_hidden'],
        order_by='module, label'
    )
    
    print("📋 ALL WORKSPACES")
    print("=" * 50)
    
    current_module = None
    for ws in workspaces:
        if ws.module != current_module:
            current_module = ws.module
            print(f"\n📁 {current_module or 'No Module'}")
            print("-" * 30)
        
        status_icons = []
        if not ws.public:
            status_icons.append("🔒")
        if ws.is_hidden:
            status_icons.append("👁️‍🗨️")
        
        status = " ".join(status_icons) if status_icons else "🌐"
        print(f"  {status} {ws.label} ({ws.name})")
    
    print(f"\nTotal workspaces: {len(workspaces)}")
    return workspaces

def quick_health_check():
    """Quick health check of all workspaces"""
    print("🏥 WORKSPACE HEALTH CHECK")
    print("=" * 50)
    
    workspaces = frappe.get_all('Workspace', fields=['name', 'label'])
    
    total_issues = 0
    
    for ws in workspaces:
        try:
            from verenigingen.utils.workspace_analyzer import analyze_workspace
            from verenigingen.utils.workspace_link_validator import validate_workspace_links
            
            # Quick analysis
            analysis = analyze_workspace(ws.name)
            validation = validate_workspace_links(ws.name)
            
            issues = []
            if not analysis['is_synchronized']:
                issues.append("sync")
            
            invalid_links = [v for v in validation if not v['valid']]
            if invalid_links:
                issues.append(f"{len(invalid_links)} invalid links")
            
            if issues:
                print(f"⚠️  {ws.label}: {', '.join(issues)}")
                total_issues += len(issues)
            else:
                print(f"✅ {ws.label}")
                
        except Exception as e:
            print(f"❌ {ws.label}: Error - {str(e)}")
            total_issues += 1
    
    print(f"\nTotal issues found: {total_issues}")
    return total_issues == 0