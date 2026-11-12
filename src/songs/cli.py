"""The `songs` command. Each stage adds its commands here as its code arrives."""

from typing import Annotated

import typer

from songs.common import run_records

app = typer.Typer(no_args_is_help=True, help="Song lyrics research dataset.")
lyrics_app = typer.Typer(no_args_is_help=True, help="Lyric collection by country.")
app.add_typer(lyrics_app, name="lyrics")


@app.callback()
def main() -> None:
    """Song lyrics research dataset."""


@lyrics_app.command("history")
def lyrics_history(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    route: Annotated[str | None, typer.Option(help="Show only this route.")] = None,
) -> None:
    """Show the collection runs already recorded for a country. Read this before a new run."""
    code = iso3.upper()
    if not run_records.ISO3.fullmatch(code):
        raise typer.BadParameter(f"not a three-letter country code: {iso3}")
    if route is not None and route not in run_records.ROUTES:
        raise typer.BadParameter(f"route must be one of: {', '.join(run_records.ROUTES)}")
    records = [
        record
        for record in run_records.read_run_records(code)
        if route is None or record.route == route
    ]
    typer.echo(run_records.format_history(records))


@lyrics_app.command("coverage")
def lyrics_coverage(
    write: Annotated[bool, typer.Option("--write", help="Write the coverage page.")] = False,
) -> None:
    """Print the coverage table for all countries, or write docs/status/coverage.md."""
    if write:
        typer.echo(f"wrote {run_records.write_coverage()}")
    else:
        typer.echo(run_records.render_coverage(run_records.read_run_records()))
