"""Command line entry point: `health-coach <command>`."""

import logging
from typing import Annotated

import typer

from health_coach.config import get_settings

app = typer.Typer(no_args_is_help=True, help="Health coach services and admin commands.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations and roles.")
app.add_typer(db_app, name="db")
sync_app = typer.Typer(no_args_is_help=True, help="Run an ingest job once.")
app.add_typer(sync_app, name="sync")
auth_app = typer.Typer(no_args_is_help=True, help="Connect data sources.")
app.add_typer(auth_app, name="auth")
scores_app = typer.Typer(no_args_is_help=True, help="Compute recovery, strain and sleep scores.")
app.add_typer(scores_app, name="scores")


@app.callback()
def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def mcp() -> None:
    """Run the MCP server (Streamable HTTP)."""
    from health_coach.mcp_server.server import run

    run()


@app.command("fit-mcp")
def fit_mcp() -> None:
    """Run the fit MCP server for openGym (Streamable HTTP)."""
    from health_coach.fit.server import run

    run()


@app.command()
def worker() -> None:
    """Run the scheduler with ingest and analytics jobs."""
    from health_coach.jobs.scheduler import run

    run()


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations up to REVISION."""
    from health_coach.db.admin import upgrade

    upgrade(revision)


@db_app.command("sync-roles")
def db_sync_roles() -> None:
    """Set LOGIN and passwords of the service roles from the configured URLs."""
    from health_coach.db.admin import sync_roles

    for role in sync_roles():
        typer.echo(f"synced {role}")


@auth_app.command("google")
def auth_google() -> None:
    """One-time Google consent; stores the encrypted refresh token."""
    from health_coach.config import get_settings
    from health_coach.db.engine import Role, get_engine
    from health_coach.ingest.google_health import oauth

    settings = get_settings()
    request = oauth.start_consent(settings)
    typer.echo("1. Open this URL in a browser signed in to the Google account of the watch:\n")
    typer.echo(request.url)
    typer.echo(
        "\n2. After approving, the browser lands on a page that does not load "
        f"({settings.google_redirect_uri}...). Copy that whole URL from the address bar."
    )
    redirected = typer.prompt("3. Paste it here")
    scopes = oauth.finish_consent(get_engine(Role.ingest), settings, request, redirected)
    typer.echo("Stored. Granted scopes:\n  " + "\n  ".join(scopes))
    missing = set(settings.google_scopes) - set(scopes)
    if missing:
        typer.echo("Not granted (those data types will fail): " + ", ".join(sorted(missing)))


@auth_app.command("opengym")
def auth_opengym() -> None:
    """Interactively pair with openGym; stores the encrypted token."""
    from health_coach.config import get_settings
    from health_coach.db.engine import Role, get_engine
    from health_coach.ingest.opengym import pair_and_store

    settings = get_settings()
    if not settings.opengym_url:
        raise typer.BadParameter("HC_OPENGYM_URL must be set")
    typer.echo(
        "In the openGym web app, go to Settings -> 'Pair the mobile app' "
        "to get an 8-character code."
    )
    code = typer.prompt("Enter pairing code")
    engine = get_engine(Role.ingest)
    pair_and_store(engine, settings, code)
    typer.echo("Successfully paired with openGym.")


@sync_app.command("opengym")
def sync_opengym(
    catalogue: bool = typer.Option(
        False, "--catalogue", "-c", help="Also refresh the exercise catalogue."
    ),
) -> None:
    """Sync openGym workouts, body weight, and optionally catalogue now."""
    from health_coach.jobs.scheduler import opengym_catalogue, opengym_workouts

    if catalogue:
        opengym_catalogue()
    opengym_workouts()


@sync_app.command("google")
def sync_google(
    days: Annotated[int, typer.Option(help="Days back from today")] = 1,
    data_type: Annotated[
        list[str] | None, typer.Option("--type", help="Only these data types")
    ] = None,
) -> None:
    """Fetch recent Google Health data now."""
    from health_coach.jobs.scheduler import google_health

    google_health(days, tuple(data_type or ()))


@app.command("backfill")
def backfill_cmd(
    source: str = typer.Argument(..., help="google"),
    since: str = typer.Option(..., "--from", help="First day, YYYY-MM-DD"),
    data_type: Annotated[
        list[str] | None, typer.Option("--type", help="Only these data types")
    ] = None,
) -> None:
    """Fetch history from a date. Resumable: rerun after an interruption.

    Intraday heart rate only goes back 30 days whatever the start date."""
    import datetime as dt

    from health_coach.config import get_settings
    from health_coach.db.engine import Role, get_engine
    from health_coach.ingest.google_health.client import GoogleHealthClient
    from health_coach.ingest.google_health.datatypes import BY_NAME, DATA_TYPES
    from health_coach.ingest.google_health.sync import backfill

    if source != "google":
        raise typer.BadParameter("only 'google' is supported")
    unknown = sorted(set(data_type or ()) - set(BY_NAME))
    if unknown:
        raise typer.BadParameter(f"unknown data types: {', '.join(unknown)}")
    specs = [s for s in DATA_TYPES if not data_type or s.name in data_type]
    engine = get_engine(Role.ingest)
    with GoogleHealthClient(engine, get_settings()) as client:
        results = backfill(
            client,
            engine,
            dt.date.fromisoformat(since),
            specs,
            on_error=lambda spec, exc: typer.echo(f"{spec.name}: stopped ({exc}); rerun to resume"),
        )
    for r in results:
        typer.echo(f"{r.data_type}: {r.chunks} chunks, {r.rows} rows mapped")


@app.command("remap")
def remap_cmd(source: str = typer.Argument(..., help="google")) -> None:
    """Re-run mappers over stored raw payloads (after a mapper fix)."""
    from health_coach.db.engine import Role, get_engine
    from health_coach.ingest.google_health.sync import remap

    if source != "google":
        raise typer.BadParameter("only 'google' is supported")
    for data_type, rows in remap(get_engine(Role.ingest)).items():
        typer.echo(f"{data_type}: {rows} rows")


@scores_app.command("backfill")
def scores_backfill(
    days: Annotated[int, typer.Option("--days", "-d", help="Days back from today")] = 60,
) -> None:
    """Recompute daily scores for the last N days."""
    from health_coach.db.engine import Role, get_engine
    from health_coach.jobs.scores import refresh_scores

    engine = get_engine(Role.ingest)
    count = refresh_scores(engine, days_back=days)
    typer.echo(f"scores: {count} days computed")
