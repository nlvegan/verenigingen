"""
Workspace Maintenance Commands

Provides command-line tools for workspace health maintenance and migration support.
"""

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("workspace-maintenance")
@click.option("--all-workspaces", is_flag=True, help="Run maintenance on all workspaces")
@click.option("--post-migration", is_flag=True, help="Run post-migration workspace health checks")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@pass_context
def workspace_maintenance(context, all_workspaces, post_migration, dry_run):
    """Run workspace maintenance operations"""

    site = get_site(context)

    with frappe.init_site(site):
        frappe.connect()

        try:
            if post_migration:
                run_post_migration_check(dry_run)
            elif all_workspaces:
                run_all_workspaces_maintenance(dry_run)
            else:
                click.echo("Please specify an operation:")
                click.echo("  --all-workspaces    Fix all workspace health issues")
                click.echo("  --post-migration    Run post-migration health checks")
                click.echo("  --dry-run          Show what would be done")

        except Exception as e:
            click.echo(f"❌ Error: {str(e)}", err=True)
        finally:
            frappe.destroy()


def run_post_migration_check(dry_run):
    """Run post-migration workspace health checks"""
    click.echo("🔍 Running post-migration workspace health checks...")

    if dry_run:
        click.echo("🔍 DRY RUN - No changes will be made")

    try:
        from verenigingen.utils.post_migration_hooks import run_post_migration_workspace_health

        if not dry_run:
            run_post_migration_workspace_health()
        else:
            # Show workspaces that would be checked
            from verenigingen.utils.post_migration_hooks import get_potentially_affected_workspaces

            workspaces = get_potentially_affected_workspaces()

            click.echo(f"📊 Would check {len(workspaces)} workspaces:")
            for workspace in workspaces:
                click.echo(f"  - {workspace}")

    except Exception as e:
        click.echo(f"❌ Post-migration check failed: {str(e)}")


def run_all_workspaces_maintenance(dry_run):
    """Run comprehensive workspace maintenance"""
    click.echo("🔧 Running comprehensive workspace maintenance...")

    if dry_run:
        click.echo("🔍 DRY RUN - No changes will be made")

    try:
        if not dry_run:
            # Import and run the migration patch
            from verenigingen.patches.v2_1.workspace_health_migration import execute

            execute()
        else:
            # Show what workspaces would be processed
            from verenigingen.patches.v2_1.workspace_health_migration import get_application_workspaces

            workspaces = get_application_workspaces()

            click.echo(f"📊 Would process {len(workspaces)} application workspaces:")
            for workspace in workspaces:
                click.echo(f"  - {workspace}")

    except Exception as e:
        click.echo(f"❌ Workspace maintenance failed: {str(e)}")


# Register command
commands = [workspace_maintenance]
