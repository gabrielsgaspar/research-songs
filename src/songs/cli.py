"""The `songs` command. Each stage adds its commands here as its code arrives."""

from pathlib import Path
from typing import Annotated

import typer

from songs.common import campaigns, lyric_sources, run_records
from songs.common.config import load_env_file
from songs.common.paths import resolve_project_root

app = typer.Typer(no_args_is_help=True, help="Song lyrics research dataset.")
lyrics_app = typer.Typer(no_args_is_help=True, help="Lyric collection by country.")
app.add_typer(lyrics_app, name="lyrics")


campaign_app = typer.Typer(no_args_is_help=True, help="Campaigns: a goal and its runs.")
lyrics_app.add_typer(campaign_app, name="campaign")

panel_app = typer.Typer(no_args_is_help=True, help="Country-year panels.")
app.add_typer(panel_app, name="panel")

analysis_app = typer.Typer(no_args_is_help=True, help="Analysis releases.")
app.add_typer(analysis_app, name="analysis")

dumps_app = typer.Typer(no_args_is_help=True, help="Lyric dumps in the uniform format.")
app.add_typer(dumps_app, name="dumps")

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


@lyrics_app.command("sources")
def lyrics_sources(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
) -> None:
    """List the lyric sources that can serve a country, and the runs that already used each.

    Copies that we hold come first, because a run on them sends no requests.
    """
    code = iso3.upper()
    if not run_records.ISO3.fullmatch(code):
        raise typer.BadParameter(f"not a three-letter country code: {iso3}")
    typer.echo(
        lyric_sources.format_sources_for(
            code, lyric_sources.sources_for(code), run_records.read_run_records(code)
        )
    )


def _country(iso3: str) -> str:
    code = iso3.upper()
    if not run_records.ISO3.fullmatch(code):
        raise typer.BadParameter(f"not a three-letter country code: {iso3}")
    return code


def _songs_now(code: str) -> int | None:
    """Return the number of songs in the newest songs folder of a country, or None."""
    from songs.common import manifests
    from songs.common.paths import data_root, latest_country_songs_dir

    try:
        folder = latest_country_songs_dir(data_root(), code)
        return manifests.read_manifest(folder).counts.get("songs") if folder else None
    except OSError, ValueError:
        return None


SongsOption = Annotated[
    int | None,
    typer.Option(
        "--songs", help="Songs of the country now. The default reads the newest songs folder."
    ),
]


@campaign_app.command("open")
def campaign_open(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    goal: Annotated[str, typer.Option(help="What the campaign must reach, in one sentence.")],
    songs: SongsOption = None,
) -> None:
    """Open a campaign for a country. Each later run of the country joins it."""
    code = _country(iso3)
    try:
        campaign = campaigns.open_campaign(
            code, goal, songs_before=_songs_now(code) if songs is None else songs
        )
    except (FileExistsError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"opened campaign {campaign.campaign_id} for {code}")
    typer.echo(_plan(code))


@campaign_app.command("close")
def campaign_close(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    outcome: Annotated[str, typer.Option(help="complete, stopped or abandoned.")],
    next_time: Annotated[str, typer.Option("--next-time", help="What the next campaign must try.")],
    reason: Annotated[
        str, typer.Option(help="Why the campaign stopped. Needed for stopped and abandoned.")
    ] = "",
    songs: SongsOption = None,
) -> None:
    """Close the open campaign of a country, with what the next campaign must try."""
    code = _country(iso3)
    try:
        campaign = campaigns.close_campaign(
            code,
            outcome,
            next_time,
            reason=reason,
            songs_after=_songs_now(code) if songs is None else songs,
        )
    except (FileNotFoundError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(campaigns.format_campaigns([campaign], run_records.read_run_records(code)))


@campaign_app.command("list")
def campaign_list(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
) -> None:
    """Show the campaigns of a country, each with its runs."""
    code = _country(iso3)
    typer.echo(
        campaigns.format_campaigns(
            campaigns.read_campaigns(code), run_records.read_run_records(code)
        )
    )


def _plan(code: str) -> str:
    return campaigns.format_plan(
        code,
        lyric_sources.sources_for(code),
        run_records.read_run_records(code),
        campaigns.read_campaigns(code),
    )


@lyrics_app.command("plan")
def lyrics_plan(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
) -> None:
    """Show what a new campaign for a country must read first.

    For each source that can serve the country: never ran, or the settings and the
    results of its last run. Then what the last closed campaign said to try next.
    """
    typer.echo(_plan(_country(iso3)))


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


@lyrics_app.command("import-old")
def lyrics_import_old(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    old_data: Annotated[
        Path,
        typer.Option(
            "--old-data",
            envvar="SONGS_OLD_DATA_ROOT",
            help="Data folder of the old pipeline. The command only reads it.",
        ),
    ],
    reason: Annotated[
        str | None,
        typer.Option(help="Why the country is imported again. Needed for a second import."),
    ] = None,
) -> None:
    """Import the state of a country from the files of the old pipeline.

    The command writes a new folder lyrics/<ISO3>/songs/<run id>/ in the data folder, with
    the full tables of the country and a manifest. It never changes an earlier folder.
    """
    code = iso3.upper()
    if not run_records.ISO3.fullmatch(code):
        raise typer.BadParameter(f"not a three-letter country code: {iso3}")
    typer.echo(run_records.format_history(run_records.read_run_records(code)))
    # Imported here so that the other lyrics commands do not load the data libraries.
    from songs.common.paths import data_root
    from songs.stage_00_ingest import old_layout

    result = old_layout.import_country(old_data, data_root(), code, reason=reason)
    typer.echo(
        f"wrote {result['path']} ({result['songs']} songs, {result['artists']} artists, "
        f"{result['links']} links)"
    )
    for name, value in result.items():
        if "_dropped_" in name and value:
            typer.echo(f"note: {name}: {value} rows")


@lyrics_app.command("import-dump")
def lyrics_import_dump(
    source: Annotated[str, typer.Argument(help="Source key of the dump, lower case.")],
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    discogs: Annotated[
        Path, typer.Option(help="Folder of Discogs tables. The command only reads it.")
    ],
) -> None:
    """Add the songs of the newest dump that match a Discogs track of their roster artist.

    The command writes a new folder lyrics/<ISO3>/songs/<run id>/ in the data folder, with
    the full tables of the country and a manifest, and one run record with the route
    dump_name. Only exact and loose title matches are added. It never changes an earlier
    folder.
    """
    import os

    from songs.common.paths import data_root
    from songs.stage_00_ingest import dump_match

    code = _country(iso3)
    typer.echo(run_records.format_history(run_records.read_run_records(code)))
    old = os.environ.get("SONGS_OLD_DATA_ROOT", "").strip()
    folder = discogs.resolve()
    label = (
        f"{folder.relative_to(Path(old).resolve()).as_posix()}/ in the old data folder"
        if old and folder.is_relative_to(Path(old).resolve())
        else folder.name
    )
    result = dump_match.import_dump(data_root(), source, code, discogs, discogs_label=label)
    typer.echo(
        f"wrote {result['path']} ({result['songs_added']} songs added, "
        f"{result['songs']} songs in the country, {result['links']} links)"
    )
    for name, value in result["rejected"].items():
        if value:
            typer.echo(f"not added, {name}: {value}")


@lyrics_app.command("import-scores")
def lyrics_import_scores(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    old_data: Annotated[
        Path,
        typer.Option(
            "--old-data",
            envvar="SONGS_OLD_DATA_ROOT",
            help="Data folder of the old pipeline. The command only reads it.",
        ),
    ],
) -> None:
    """Import the topic scores of a country from the files of the old pipeline.

    The command writes a new folder lyrics/<ISO3>/scores/<run id>/ in the data folder.
    The scores join the newest songs folder of the country. The command calls no model.
    """
    code = iso3.upper()
    if not run_records.ISO3.fullmatch(code):
        raise typer.BadParameter(f"not a three-letter country code: {iso3}")
    from songs.common.paths import data_root
    from songs.stage_30_topics import old_scores

    result = old_scores.import_scores(old_data, data_root(), code)
    folder = result["path"].relative_to(data_root()).as_posix()
    typer.echo(
        f"wrote {folder}/ ({result['scores']} scores, "
        f"{result['scores_no_song']} with no song, "
        f"{result['scores_text_changed']} with changed text)"
    )


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


@analysis_app.command("release")
def analysis_release() -> None:
    """Build the analysis release and write it to a new dated folder in the data folder.

    The folder is analysis/<YYYYMMDD>/. It holds country_year.parquet, songs.parquet and a
    manifest that names every input folder and counts the songs in, out and left out.
    """
    # Imported here so that the lyrics commands do not load the data libraries.
    from songs.common.paths import data_root
    from songs.stage_50_analysis import release

    result = release.build(data_root())
    typer.echo(f"wrote {result['folder']}")
    for name, number in result["counts"].items():
        typer.echo(f"{name}: {number}")


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


@dumps_app.command("build")
def dumps_build(
    source: Annotated[str, typer.Argument(help="Source key, lower case.")],
    folder: Annotated[
        Path, typer.Argument(help="Folder of the old dump. The command only reads it.")
    ],
    raw_input: Annotated[
        str,
        typer.Argument(help="raw/<source>/<YYYYMMDD>/ relative to the data folder."),
    ],
    family: Annotated[
        str | None,
        typer.Option(help="Format family. The command detects the family when this is omitted."),
    ] = None,
    day: Annotated[
        str | None,
        typer.Option(help="Build date as YYYYMMDD. The default is today, in UTC."),
    ] = None,
    incomplete: Annotated[
        bool,
        typer.Option("--incomplete", help="Mark the crawl as incomplete in the manifest."),
    ] = False,
) -> None:
    """Read one old dump and write clean/dumps/<source>/<YYYYMMDD>/.

    The date of the folder is the date of the build. The command reads the folder you name.
    It does not choose a snapshot.
    """
    from songs.common.paths import data_root
    from songs.stage_00_ingest.dumps import DumpError, build_dump

    try:
        result = build_dump(
            source,
            folder,
            raw_input,
            data_root(),
            family=family,
            day=day,
            incomplete=incomplete,
        )
    except DumpError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    if result["skipped"]:
        typer.echo(f"skipped {result['source']}: {result['reason']}")
        return
    typer.echo(
        f"wrote {result['path']} ({result['rows_out']} songs, {result['artists_out']} artists, "
        f"family {result['family']})"
    )
    for reason, count in result["dropped"].items():
        typer.echo(f"dropped {reason}: {count}")
    if result["credits_not_performer"]:
        typer.echo(f"credits left out, not a performer: {result['credits_not_performer']}")
    if result["incomplete"]:
        typer.echo("note: the crawl is incomplete")


@dumps_app.command("match")
def dumps_match(
    source: Annotated[str, typer.Argument(help="Source key of the dump, lower case.")],
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    discogs: Annotated[
        Path | None,
        typer.Option(help="Folder of Discogs tables. Also look for the roster_new songs there."),
    ] = None,
) -> None:
    """Compare the newest dump of a source with the newest songs folder of a country.

    The command only reads. It prints the count of each class, the songs left out with
    their reasons, and up to 10 artist and title pairs of each new class. With
    --discogs, it also prints the count of each Discogs class, up to 10 exact and loose
    matches, and every close match. No lyric text.
    """
    from songs.common.paths import (
        data_relative,
        data_root,
        latest_clean_dump_dir,
        latest_country_songs_dir,
    )
    from songs.stage_00_ingest.dump_match import DISCOGS_CLASSES, match_discogs, match_dump

    code = _country(iso3)
    data = data_root()
    dump, country = latest_clean_dump_dir(data, source), latest_country_songs_dir(data, code)
    if dump is None or country is None:
        typer.echo(f"error: no dump of {source} or no songs folder of {code}", err=True)
        raise typer.Exit(1)
    result = match_dump(dump, country)
    typer.echo(f"dump {data_relative(data, dump)} against {data_relative(data, country)}")
    typer.echo(f"credit rows in: {result['credit_rows_in']}")
    typer.echo(f"songs in: {result['songs_in']}, songs out: {result['songs_out']}")
    for name, number in result["counts"].items():
        typer.echo(f"  {name}: {number}")
    for name, number in result["left_out"].items():
        typer.echo(f"left out, {name}: {number}")
    typer.echo(
        f"roster_new with more than one roster artist: {result['roster_new_more_than_one_artist']}"
    )
    for name, pairs in result["examples"].items():
        typer.echo(f"examples of {name}:")
        for artist, title in pairs:
            typer.echo(f"  {artist} - {title}")
    if discogs is None:
        return
    found = match_discogs(result["songs"], country, discogs)
    typer.echo(f"roster_new songs looked up in Discogs: {len(found)}")
    for name in DISCOGS_CLASSES:
        typer.echo(f"  {name}: {sum(row['discogs_class'] == name for row in found)}")
    songs = {song["source_song_id"]: song for song in result["songs"]}
    for name, limit in (("exact", 10), ("loose", 10), ("close", None)):
        typer.echo(f"Discogs matches, {name} (artist | dump title | Discogs title | release):")
        for row in [row for row in found if row["discogs_class"] == name][:limit]:
            song = songs[row["source_song_id"]]
            typer.echo(
                f"  {song['artist_name']} | {song['song_name']} | {row['discogs_title']} | "
                f"{row['discogs_release_id']}"
            )
