"""Command-line interface commands for Makro Ortodonti."""

import click
from flask.cli import AppGroup

db_cli = AppGroup("db-tools", help="Database management and seeding commands.")


@db_cli.command("seed")
def seed_db_command():
    """Seed the database with initial catalog, exchange rates, and admin user."""
    from app.models.database import (
        init_db,
        seed_sample_data,
        migrate_patients_to_parties,
        link_invoices_to_parties,
    )
    click.echo("Initializing database tables...")
    init_db()
    click.echo("Seeding catalog and sample data...")
    generated_password = seed_sample_data()
    if generated_password:
        click.echo("=" * 60)
        click.echo(f"  Admin şifresi (bir daha gösterilmeyecek): {generated_password}")
        click.echo("=" * 60)
    migrated = migrate_patients_to_parties()
    linked = link_invoices_to_parties()
    if migrated:
        click.echo(f"Migrated {migrated} patients to Party records.")
    if linked:
        click.echo(f"Linked {linked} invoices to Party records.")
    click.echo("Database seeding completed successfully.")


def register_cli_commands(app):
    """Register custom CLI commands with the Flask application."""
    app.cli.add_command(db_cli)
