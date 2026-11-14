"""The `songs` command. Each stage adds its commands here as its code arrives."""

from typing import Annotated

import typer

from songs.common import run_records
from songs.common.config import load_env_file
from songs.common.paths import resolve_project_root

app = typer.Typer(no_args_is_help=True, help="Song lyrics research dataset.")
lyrics_app = typer.Typer(no_args_is_help=True, help="Lyric collection by country.")
app.add_typer(lyrics_app, name="lyrics")


panel_app = typer.Typer(no_args_is_help=True, help="Country-year panels.")
app.add_typer(panel_app, name="panel")

data_app = typer.Typer(
    no_args_is_help=True, help="Copy version folders between the data folder and the bucket."
)
app.add_typer(data_app, name="data")
FolderArgument = Annotated[
    str,
    typer.Argument(
        help="Version folder relative to the data folder, e.g. clean/countries/20261114/"
    ),
]


@app.callback()
def main() -> None:
    """Song lyrics research dataset."""
    # Settings such as SONGS_DATA_ROOT may live in `.env`; a set variable keeps its value.
    load_env_file(resolve_project_root() / ".env")


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


@lyrics_app.command("import-review")
def lyrics_import_review(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
) -> None:
    """Add the songs of the reviewed workbook of a country to the songs of the country.

    The command writes a new folder lyrics/<ISO3>/songs/<run id>/ in the data folder, with
    the full tables of the country and a manifest. It never changes an earlier folder.
    """
    code = iso3.upper()
    if not run_records.ISO3.fullmatch(code):
        raise typer.BadParameter(f"not a three-letter country code: {iso3}")
    # Imported here so that the other lyrics commands do not load the data libraries.
    from songs.common.paths import data_root
    from songs.stage_00_ingest import review_workbooks

    result = review_workbooks.import_workbook(data_root(), code)
    typer.echo(
        f"wrote {result['path']} ({result['songs_added']} songs added, "
        f"{result['songs_replaced']} replaced, {result['songs']} songs in the country)"
    )
    for gap in result["gaps"]:
        typer.echo(f"note: {gap}")


@lyrics_app.command("coverage")
def lyrics_coverage(
    write: Annotated[bool, typer.Option("--write", help="Write the coverage page.")] = False,
) -> None:
    """Print the coverage table for all countries, or write docs/status/coverage.md."""
    if write:
        typer.echo(f"wrote {run_records.write_coverage()}")
    else:
        typer.echo(run_records.render_coverage(run_records.read_run_records()))


@panel_app.command("countries")
def panel_countries(
    allow_missing: Annotated[
        bool,
        typer.Option(
            "--allow-missing", help="Build with empty columns for inputs that are absent."
        ),
    ] = False,
) -> None:
    """Build the country-year panel and write it to a new dated folder in the data folder.

    The folder is clean/countries/<YYYYMMDD>/. It holds countries.parquet and a manifest
    that names every input file.
    """
    # Imported here so that the lyrics commands do not load the data libraries.
    from songs.common.paths import data_root
    from songs.stage_50_analysis import countries_panel

    result = countries_panel.build(data_root(), allow_missing=allow_missing)
    typer.echo(f"wrote {result['path']} ({result['rows']} rows)")
    typer.echo(f"wrote {result['manifest']}")
    if result["absent_inputs"]:
        typer.echo(f"absent inputs, their columns are empty: {result['absent_inputs']}")
    for table, codes in result["codes_outside_registry"].items():
        typer.echo(f"{table}: codes outside the registry, left out: {codes}")


def _bucket():
    """Return the storage module, a gcloud transport and the bucket name."""
    # Imported here so that the other commands do not load the data libraries.
    from songs.common import storage
    from songs.common.config import load_config

    return storage, storage.GcloudTransport(), load_config().require("gcs_bucket")


@data_app.command("upload")
def data_upload(folder: FolderArgument) -> None:
    """Copy one complete version folder to the bucket, create-only, with the manifest last.

    The command prints one line for each object: name, bytes, generation.
    """
    from songs.common.paths import data_root

    storage, transport, bucket = _bucket()
    try:
        storage.upload_folder(transport, bucket, data_root(), folder, echo=typer.echo)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error


@data_app.command("download")
def data_download(folder: FolderArgument) -> None:
    """Copy one complete version folder from the bucket to the data folder, manifest last."""
    from songs.common.paths import data_root

    storage, transport, bucket = _bucket()
    try:
        storage.download_folder(transport, bucket, data_root(), folder, echo=typer.echo)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error


@data_app.command("check")
def data_check(folder: FolderArgument) -> None:
    """Check a folder in the bucket against its manifest, from the listing only."""
    storage, transport, bucket = _bucket()
    try:
        problems = storage.check_folder(transport, bucket, folder)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)
    typer.echo(f"{storage.version_folder(folder)}: every object matches the manifest")
