#!/usr/bin/env python3
"""
Workspace Management Commands for Verenigingen

Unified command interface for all workspace operations including validation,
analysis, fixing, and debugging.

Usage:
    bench --site [site] workspace validate [workspace-name] [options]
    bench --site [site] workspace analyze [workspace-name]
    bench --site [site] workspace fix [workspace-name] [options]
    bench --site [site] workspace diagnose [workspace-name]
    bench --site [site] workspace list [options]

Examples:
    bench --site dev.veganisme.net workspace validate Verenigingen --comprehensive
    bench --site dev.veganisme.net workspace analyze Verenigingen
    bench --site dev.veganisme.net workspace fix Verenigingen --dry-run
    bench --site dev.veganisme.net workspace diagnose Verenigingen
    bench --site dev.veganisme.net workspace list --health-check
"""

import click
import frappe
from frappe.commands import pass_context


@click.group()
def workspace():
    """Workspace management commands for validation, analysis, and fixing"""
    pass


@workspace.command("validate")
@click.argument("workspace_name")
@click.option(
    "--comprehensive", is_flag=True, help="Run comprehensive validation including all existing validators"
)
@click.option("--links-only", is_flag=True, help="Validate only workspace links")
@click.option("--structure-only", is_flag=True, help="Validate only content structure")
@click.option("--quiet", is_flag=True, help="Show only errors and warnings")
@pass_context
def validate_workspace(context, workspace_name, comprehensive, links_only, structure_only, quiet):
    """Validate workspace configuration and structure"""

    frappe.init(site=context.sites[0])
    frappe.connect()

    try:
        if not quiet:
            click.echo(f"🔍 Validating workspace: {workspace_name}")
            click.echo("=" * 50)

        all_passed = True

        # Structure validation (new tools)
        if not links_only:
            if not quiet:
                click.echo("📊 Content Structure Analysis")
                click.echo("-" * 30)

            from verenigingen.utils.workspace_analyzer import analyze_workspace

            analysis = analyze_workspace(workspace_name)

            if not analysis["is_synchronized"]:
                all_passed = False
                click.echo("❌ Content/Database structure mismatch detected")
                if analysis["content_only"]:
                    click.echo(f"   Cards in content but no Card Break: {analysis['content_only']}")
                if analysis["db_only"]:
                    click.echo(f"   Card Breaks but no content card: {analysis['db_only']}")
            else:
                if not quiet:
                    click.echo("✅ Content structure synchronized")

        # Link validation (new tools)
        if not structure_only:
            if not quiet:
                click.echo("\n🔗 Link Target Validation")
                click.echo("-" * 30)

            from verenigingen.utils.workspace_link_validator import validate_workspace_links

            link_results = validate_workspace_links(workspace_name)

            invalid_links = [r for r in link_results if not r["valid"]]
            if invalid_links:
                all_passed = False
                click.echo(f"❌ {len(invalid_links)} invalid links found")
                for link in invalid_links:
                    click.echo(f"   {link['label']}: {link['error']}")
            else:
                if not quiet:
                    click.echo("✅ All links valid")

        # Comprehensive validation (existing tools)
        if comprehensive:
            if not quiet:
                click.echo("\n🏗️ Comprehensive System Validation")
                click.echo("-" * 30)

            try:
                from verenigingen.api.workspace_validator_enhanced import EnhancedWorkspaceValidator

                validator = EnhancedWorkspaceValidator()
                result = validator.validate_all_workspaces()

                if result.get("errors"):
                    all_passed = False
                    click.echo(f"❌ {len(result['errors'])} system errors found")
                    for error in result["errors"]:
                        click.echo(f"   {error}")
                else:
                    if not quiet:
                        click.echo("✅ System validation passed")

            except ImportError:
                click.echo("⚠️  Enhanced validator not available")

        # Summary
        if not quiet:
            click.echo(f"\n{'✅ VALIDATION PASSED' if all_passed else '❌ VALIDATION FAILED'}")

        if not all_passed:
            raise click.ClickException("Workspace validation failed")

    except Exception as e:
        if "Workspace validation failed" not in str(e):
            click.echo(f"❌ Validation error: {str(e)}")
        raise
    finally:
        frappe.destroy()


@workspace.command("analyze")
@click.argument("workspace_name")
@click.option("--detailed", is_flag=True, help="Show detailed analysis including link breakdown")
@pass_context
def analyze_workspace(context, workspace_name, detailed):
    """Analyze workspace structure and identify issues"""

    frappe.init(site=context.sites[0])
    frappe.connect()

    try:
        from verenigingen.utils.workspace_analyzer import print_analysis

        click.echo(f"📊 Analyzing workspace: {workspace_name}")
        click.echo("=" * 50)

        result = print_analysis(workspace_name)

        if detailed and not result["is_synchronized"]:
            click.echo("\n🔍 Detailed Analysis")
            click.echo("-" * 20)

            # Show specific Card Break contents
            from verenigingen.utils.workspace_analyzer import get_card_links

            for card_name in result["db_only"]:
                try:
                    links = get_card_links(workspace_name, card_name)
                    click.echo(f"\n📁 {card_name} ({len(links)} links):")
                    for link in links:
                        click.echo(f"   → {link['label']} ({link['link_type']}: {link['link_to']})")
                except Exception as e:
                    click.echo(f"   ❌ Error getting links: {str(e)}")

    except Exception as e:
        click.echo(f"❌ Analysis error: {str(e)}")
        raise
    finally:
        frappe.destroy()


@workspace.command("fix")
@click.argument("workspace_name")
@click.option("--dry-run", is_flag=True, help="Show what would be fixed without making changes")
@click.option("--backup", is_flag=True, default=True, help="Create backup before fixing (default: true)")
@click.option("--content-only", is_flag=True, help="Fix only content structure issues")
@click.option("--links-only", is_flag=True, help="Fix only link issues")
@pass_context
def fix_workspace(context, workspace_name, dry_run, backup, content_only, links_only):
    """Fix workspace issues automatically"""

    frappe.init(site=context.sites[0])
    frappe.connect()

    try:
        click.echo(f"🔧 {'Analyzing' if dry_run else 'Fixing'} workspace: {workspace_name}")
        click.echo("=" * 50)

        if backup and not dry_run:
            from verenigingen.utils.workspace_content_fixer import create_content_backup

            backup_file = create_content_backup(workspace_name)
            click.echo(f"📦 Backup created: {backup_file}")

        fixed_any = False

        # Fix content structure issues
        if not links_only:
            click.echo("\n🔧 Content Structure Fixes")
            click.echo("-" * 30)

            from verenigingen.utils.workspace_content_fixer import fix_workspace_content

            if fix_workspace_content(workspace_name, dry_run=dry_run):
                fixed_any = True

        # Note: Link fixes would require more sophisticated logic
        if not content_only and not dry_run:
            click.echo("\n⚠️  Link fixes require manual intervention")
            click.echo("   Use 'workspace validate --links-only' to identify specific issues")

        if dry_run:
            click.echo("\n🚫 Dry run complete - no changes made")
        elif fixed_any:
            click.echo("\n✅ Workspace fixes applied")
            click.echo("   Run 'bench clear-cache' to refresh workspace rendering")
        else:
            click.echo("\n✅ No fixes needed")

    except Exception as e:
        click.echo(f"❌ Fix error: {str(e)}")
        raise
    finally:
        frappe.destroy()


@workspace.command("diagnose")
@click.argument("workspace_name")
@pass_context
def diagnose_workspace(context, workspace_name):
    """Run comprehensive workspace diagnostics"""

    frappe.init(site=context.sites[0])
    frappe.connect()

    try:
        # Use the existing comprehensive diagnostic tool
        from scripts.workspace_debugging_toolkit import diagnose

        diagnose(workspace_name)

    except Exception as e:
        click.echo(f"❌ Diagnostic error: {str(e)}")
        raise
    finally:
        frappe.destroy()


@workspace.command("list")
@click.option("--health-check", is_flag=True, help="Show health status for each workspace")
@click.option("--module", help="Filter by module")
@pass_context
def list_workspaces(context, health_check, module):
    """List all workspaces with optional health check"""

    frappe.init(site=context.sites[0])
    frappe.connect()

    try:
        if health_check:
            from scripts.workspace_debugging_toolkit import quick_health_check

            quick_health_check()
        else:
            from scripts.workspace_debugging_toolkit import list_all_workspaces

            workspaces = list_all_workspaces()

            if module:
                filtered = [ws for ws in workspaces if ws.module == module]
                click.echo(f"\nFiltered to module '{module}': {len(filtered)} workspaces")

    except Exception as e:
        click.echo(f"❌ List error: {str(e)}")
        raise
    finally:
        frappe.destroy()


# Register commands with Frappe
commands = [workspace]
