"""
Workspace Health Command Interface

Provides simple command-line interface for workspace health management.
"""

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("workspace-health")
@click.argument("workspace-name")
@click.option("--diagnose-only", is_flag=True, default=False, help="Run diagnostics without applying fixes")
@click.option("--no-backup", is_flag=True, default=False, help="Skip creating backup before fixes")
@click.option("--quick-fix", is_flag=True, default=False, help="Apply quick fix for content sync only")
@pass_context
def workspace_health(context, workspace_name, diagnose_only, no_backup, quick_fix):
    """Check and fix workspace health issues"""

    site = get_site(context)

    with frappe.init_site(site):
        frappe.connect()

        try:
            if quick_fix:
                from verenigingen.api.workspace_health import quick_fix as do_quick_fix

                result = do_quick_fix(workspace_name)
                print_result(result, "Quick Fix")

            elif diagnose_only:
                from verenigingen.api.workspace_health import health_check

                result = health_check(workspace_name)
                print_result(result, "Health Check")

            else:
                from verenigingen.api.workspace_health import diagnose_and_fix

                result = diagnose_and_fix(
                    workspace_name=workspace_name, auto_fix=True, create_backup=not no_backup
                )
                print_result(result, "Diagnose & Fix")

        except Exception as e:
            click.echo(f"❌ Error: {str(e)}", err=True)
        finally:
            frappe.destroy()


def print_result(result: dict, operation: str):
    """Print formatted result"""
    click.echo(f"\n🔍 {operation} Results:")
    click.echo("=" * 50)

    if result.get("success"):
        click.echo(f"📊 {result.get('summary', 'Operation completed')}")

        if result.get("backup_path"):
            click.echo(f"💾 Backup created: {result['backup_path']}")

        if result.get("issues"):
            click.echo(f"\n⚠️  Issues Found ({len(result['issues'])}):")
            for i, issue in enumerate(result["issues"], 1):
                severity_icon = {"critical": "🚨", "high": "⚠️", "medium": "⚡", "low": "ℹ️"}.get(
                    issue["severity"], "❓"
                )
                click.echo(f"  {i}. {severity_icon} {issue['description']}")

        if result.get("fixes"):
            click.echo(f"\n✅ Fixes Applied ({len(result['fixes'])}):")
            for i, fix in enumerate(result["fixes"], 1):
                click.echo(f"  {i}. {fix['description']}")

        if not result.get("issues") and not result.get("fixes"):
            click.echo("✅ No issues found - workspace is healthy!")

    else:
        click.echo(f"❌ {result.get('error', 'Unknown error')}")
        if result.get("backup_path"):
            click.echo(f"💾 Backup available: {result['backup_path']}")

    click.echo()


# Register command
commands = [workspace_health]
