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

score_app = typer.Typer(
    no_args_is_help=True,
    help="Topic scoring through the Batch API: prepare, submit (a person only) and collect.",
)
app.add_typer(score_app, name="score")
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
        Path | None,
        typer.Option(
            help="Folder of Discogs tables. The default is the newest clean/catalog/discogs/."
        ),
    ] = None,
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
    label = None
    if discogs is not None:
        old = os.environ.get("SONGS_OLD_DATA_ROOT", "").strip()
        folder = discogs.resolve()
        label = (
            f"{folder.relative_to(Path(old).resolve()).as_posix()}/ in the old data folder"
            if old and folder.is_relative_to(Path(old).resolve())
            else folder.name
        )
    try:
        result = dump_match.import_dump(data_root(), source, code, discogs, discogs_label=label)
    except FileNotFoundError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        f"wrote {result['path']} ({result['songs_added']} songs added, "
        f"{result['songs']} songs in the country, {result['links']} links)"
    )
    for name, value in result["rejected"].items():
        if value:
            typer.echo(f"not added, {name}: {value}")


@lyrics_app.command("collect")
def lyrics_collect(
    source: Annotated[str, typer.Argument(help="Source key of the site, lower case.")],
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    delay: Annotated[
        float, typer.Option(help="Seconds between requests. The command uses 2 or more.")
    ] = 2.0,
    artist_limit: Annotated[
        int | None, typer.Option("--artist-limit", help="Read at most this number of artists.")
    ] = None,
    song_limit: Annotated[
        int | None, typer.Option("--song-limit", help="Read at most this number of songs.")
    ] = None,
    reason: Annotated[
        str | None,
        typer.Option(help="Why the site is collected again. Needed to repeat a complete run."),
    ] = None,
) -> None:
    """Collect the pages of a lyric site into a new folder raw/<source>/<YYYYMMDD>/.

    The command sends requests to the site. It obeys robots.txt, waits between requests
    and writes one run record with the route live. It adds no song to the country: build
    the dump and import it with the two commands that it prints.
    """
    from songs.common.paths import data_root
    from songs.stage_00_ingest import dainutekstai

    code = _country(iso3)
    if source != dainutekstai.SOURCE:
        typer.echo(
            f"error: no collector for {source}; one exists for {dainutekstai.SOURCE}", err=True
        )
        raise typer.Exit(1)
    typer.echo(run_records.format_history(run_records.read_run_records(code)))
    data = data_root()
    try:
        result = dainutekstai.collect(
            data,
            code,
            delay=delay,
            artist_limit=artist_limit,
            song_limit=song_limit,
            reason=reason,
        )
    except (FileExistsError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        f"{result['state']}: {result['requests_sent']} pages requested, "
        f"{result['songs_written']} songs written"
    )
    for name, number in result["songs_left_out"].items():
        typer.echo(f"left out, {name}: {number}")
    for gap in result["known_gaps"]:
        typer.echo(f"note: {gap}")
    if result["path"]:
        typer.echo(f"wrote {result['path']}. Next:")
        typer.echo(f'uv run songs dumps build {source} "{data / result["path"]}" {result["path"]}')
        typer.echo(f"uv run songs lyrics import-dump {source} {code}")


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
        f"wrote {result['path']} ({result['songs_out']} songs, "
        f"{result['rows_out']} song credit rows, {result['artists_out']} artists, "
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
        typer.Option(
            help="Folder of Discogs tables. The default is the newest clean/catalog/discogs/."
        ),
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
        latest_clean_catalog_dir,
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
    typer.echo(f"matched by the lead of a featuring credit: {result['matched_by_split']}")
    for name, pairs in result["examples"].items():
        typer.echo(f"examples of {name}:")
        for artist, title in pairs:
            typer.echo(f"  {artist} - {title}")
    discogs = discogs or latest_clean_catalog_dir(data, "discogs")
    if discogs is None:
        return
    found = match_discogs(result["songs"], country, discogs, code)
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


CountriesArgument = Annotated[
    list[str], typer.Argument(help="Country codes, three capital letters each.")
]
YearsOption = Annotated[
    str | None, typer.Option("--years", help="A year or a range of years: 1965 or 1960-1969.")
]


def _years(text: str | None) -> tuple[int, int] | None:
    """Return the first and the last year of `1960-1969` or `1965`, or None for no option."""
    if text is None:
        return None
    import re

    found = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", text.strip())
    first, last = (int(found[1]), int(found[2] or found[1])) if found else (1, 0)
    if first > last:
        raise typer.BadParameter(f"--years is a year or a range such as 1960-1969, got {text!r}")
    return first, last


def _in_years(by_year: dict[int, int], years: tuple[int, int]) -> int:
    return sum(number for year, number in by_year.items() if years[0] <= year <= years[1])


def _decades(counts: dict[int, int]) -> str:
    return ", ".join(f"{decade}s: {number}" for decade, number in counts.items()) or "none"


@data_app.command("pull")
def data_pull(
    countries: CountriesArgument,
    no_catalog: Annotated[
        bool,
        typer.Option("--no-catalog", help="Leave out the Discogs catalog (17 GB, about 2 hours)."),
    ] = False,
) -> None:
    """Download the newest folders that a campaign for the countries needs.

    For each country: its songs, its scores and the dump of each of its sources. Then
    the Discogs catalog. A folder that is complete on this disk is not downloaded again.
    """
    from songs.common.paths import data_root
    from songs.stage_00_ingest.campaign_run import pull_parents

    parents = pull_parents([_country(code) for code in countries], catalog=not no_catalog)
    storage, transport, bucket = _bucket()
    try:
        done = storage.pull_newest(transport, bucket, data_root(), parents)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    for parent, (outcome, folder) in done.items():
        typer.echo(f"{folder or parent}: {outcome}")


@data_app.command("sync")
def data_sync(
    write: Annotated[
        bool, typer.Option("--write", help="Upload. Without it, the command only prints.")
    ] = False,
) -> None:
    """Print a Markdown report of the complete local folders that the bucket lacks.

    With --write, the command uploads them, inputs first. A songs folder goes only when
    its run record is in countries/<ISO3>/runs/ and the country has no open campaign.
    The report also names each derived folder that is stale. The command builds nothing.
    """
    from songs.common import sync
    from songs.common.paths import data_root

    storage, transport, bucket = _bucket()
    try:
        result = sync.sync(transport, bucket, data_root(), write=write)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(sync.report(data_root(), result, write=write))
    if result["missing_inputs"]:
        raise typer.Exit(1)


@lyrics_app.command("publish")
def lyrics_publish(countries: CountriesArgument) -> None:
    """Upload the songs folders of the countries that the bucket lacks, with their inputs.

    The inputs of a folder go first. Each uploaded folder is checked against its manifest.
    A folder is not uploaded when one of its inputs is a version folder that is neither on
    this disk nor in the bucket; the command then exits with 1 after the other uploads.
    """
    from songs.common.paths import data_root

    parents = [f"lyrics/{_country(code)}/songs/" for code in countries]
    storage, transport, bucket = _bucket()
    try:
        result = storage.publish(transport, bucket, data_root(), parents)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    for folder in result["uploaded"]:
        typer.echo(f"uploaded: {folder}")
    for folder in result["present"]:
        typer.echo(f"in the bucket already: {folder}")
    for folder, name in result["old_inputs"]:
        typer.echo(f"note: {folder} has the input {name} from the old data folder")
    for folder, name in result["missing_inputs"]:
        typer.echo(f"problem: {folder} names the input {name}; it is not in the bucket")
    for folder in result["skipped"]:
        typer.echo(f"not uploaded: {folder}")
    typer.echo(
        f"{len(result['uploaded'])} uploaded, {len(result['present'])} in the bucket already, "
        f"{len(result['skipped'])} not uploaded"
    )
    if result["skipped"]:
        raise typer.Exit(1)


@lyrics_app.command("audit")
def lyrics_audit() -> None:
    """Compare the run records with the songs folders of the bucket. It takes about 3 minutes.

    The command prints each run record with no complete songs folder in the bucket, and
    each complete songs folder with no run record. It exits with 1 when it finds one.
    """
    from songs.stage_00_ingest.campaign_run import expected_songs_folders

    storage, transport, bucket = _bucket()
    expected = expected_songs_folders(run_records.read_run_records())
    try:
        result = storage.audit_songs(transport, bucket, expected)
    except storage.StorageError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    for code, run_id in result["not_in_bucket"]:
        typer.echo(f"record with no folder in the bucket: lyrics/{code}/songs/{run_id}/")
    for code, run_id in result["no_record"]:
        typer.echo(f"folder in the bucket with no record: lyrics/{code}/songs/{run_id}/")
    typer.echo(
        f"{len(expected)} records, {len(result['not_in_bucket'])} with no folder, "
        f"{len(result['no_record'])} folders with no record"
    )
    if result["not_in_bucket"] or result["no_record"]:
        raise typer.Exit(1)


@lyrics_app.command("survey")
def lyrics_survey(countries: CountriesArgument, years: YearsOption = None) -> None:
    """Estimate what an import of each dump on this disk adds to each country. Read-only.

    One line for each country and source: the songs that the import would add, the
    seconds, and the songs by decade. Then one total line.
    """
    from songs.common.paths import data_root
    from songs.stage_00_ingest import dump_match

    span = _years(years)
    total = inside = 0
    for code in [_country(code) for code in countries]:
        sources = [source.id for source in lyric_sources.sources_for(code)]
        try:
            rows = dump_match.survey(data_root(), code, sources)
        except FileNotFoundError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(1) from error
        for row in rows:
            if row["dump"] is None:
                typer.echo(f"{code} {row['source']}: no dump on this disk")
                continue
            total += row["would_add"]
            line = (
                f"{code} {row['source']}: would add {row['would_add']} of {row['songs_in']} songs, "
                f"{row['seconds']} s; {_decades(dump_match.by_decade(row['by_year']))}; "
                f"no year: {row['no_year']}"
            )
            if span:
                inside += _in_years(row["by_year"], span)
                line += f"; {span[0]}-{span[1]}: {_in_years(row['by_year'], span)}"
            typer.echo(line)
    # A song can be in two dumps, so the total is an upper limit.
    typer.echo(
        f"total: would add up to {total} songs"
        + (f", {inside} in {span[0]}-{span[1]}" if span else "")
    )


@lyrics_app.command("gaps")
def lyrics_gaps(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    years: YearsOption = None,
) -> None:
    """Show, by decade, the songs that a country holds and the Discogs tracks that it lacks.

    A wanted track is a track of a roster artist with a Discogs id that has no song in
    the country. Read-only.
    """
    from songs.common.paths import data_root
    from songs.stage_00_ingest import dump_match

    code, span = _country(iso3), _years(years)
    try:
        result = dump_match.gaps(data_root(), code)
    except FileNotFoundError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    held = dump_match.by_decade(result["held_by_year"])
    wanted = dump_match.by_decade(result["wanted_by_year"])
    typer.echo(f"{code} {result['songs_folder']}")
    typer.echo("decade\tsongs held\ttracks wanted")
    for decade in sorted(set(held) | set(wanted)):
        typer.echo(f"{decade}s\t{held.get(decade, 0)}\t{wanted.get(decade, 0)}")
    typer.echo(f"no year\t{result['held_no_year']}\t{result['wanted_no_year']}")
    typer.echo(f"total\t{result['songs']}\t{result['wanted']}")
    if span:
        typer.echo(
            f"{span[0]}-{span[1]}\t{_in_years(result['held_by_year'], span)}"
            f"\t{_in_years(result['wanted_by_year'], span)}"
        )
    typer.echo(
        f"artists with no Discogs id: {result['artists_no_discogs_id']} of {result['artists']}"
    )


@lyrics_app.command("roster-check")
def lyrics_roster_check(
    write: Annotated[
        bool, typer.Option("--write", help="Write the table. Without it, the command only prints.")
    ] = False,
) -> None:
    """Mark the roster artists of every country that belong to another country.

    The rule reads the Discogs profile and the release countries of each roster artist
    with a Discogs id. It takes about 10 minutes. With --write, the command writes
    clean/quality/artist_country/<YYYYMMDD>/ in the data folder.
    """
    from songs.common.paths import data_root
    from songs.stage_10_clean import artist_country

    try:
        result = artist_country.check_rosters(data_root(), write=write)
    except (FileNotFoundError, FileExistsError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    counts = result["counts"]
    typer.echo(f"countries: {counts['countries']}")
    typer.echo(f"roster artists in: {counts['artists_in']}")
    typer.echo(f"with a Discogs id (rows out): {counts['artists_with_discogs_id']}")
    typer.echo(f"left out, no Discogs id: {counts['left_out_no_discogs_id']}")
    typer.echo(
        f"other_country: {counts['other_country_artists']} artists, "
        f"{counts['other_country_artists_with_songs']} of them with songs"
    )
    share = 100 * counts["other_country_songs"] / max(counts["songs_in"], 1)
    typer.echo(
        f"songs of those artists: {counts['other_country_songs']} of {counts['songs_in']} "
        f"({share:.2f}%)"
    )
    typer.echo("country	songs of those artists	songs	share")
    by_share = sorted(result["by_country"].items(), key=lambda item: -item[1][0] / item[1][1])
    for code, (other, songs) in by_share[:15]:
        typer.echo(f"{code}	{other}	{songs}	{100 * other / songs:.1f}%")
    typer.echo(f"wrote {result['folder']}" if write else "dry run: nothing written")


@lyrics_app.command("copy-check")
def lyrics_copy_check(
    write: Annotated[
        bool, typer.Option("--write", help="Write the table. Without it, the command only prints.")
    ] = False,
) -> None:
    """Mark the campaign songs of every country whose text is a copy of another song.

    The rule compares the letters and digits of each text. It takes about 3 minutes.
    With --write, the command writes clean/quality/text_copies/<YYYYMMDD>/ in the data folder.
    """
    from songs.common.paths import data_root
    from songs.common.schemas import SAME_ARTIST_START, SAME_TEXT
    from songs.stage_10_clean import text_copies

    try:
        result = text_copies.check_copies(data_root(), write=write)
    except FileExistsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    counts = result["counts"]
    typer.echo(f"countries: {counts['countries']}")
    typer.echo(f"songs in: {counts['songs_in']}, campaign songs: {counts['campaign_songs']}")
    typer.echo(f"left out, text with no key: {counts['songs_no_key']}")
    typer.echo(f"copies (rows out): {counts['copies']}")
    for reason in (SAME_TEXT, SAME_ARTIST_START):
        typer.echo(f"  {reason}: {counts[reason]}")
    typer.echo("country	copies	campaign songs	songs	share of campaign songs")
    by_share = sorted(result["by_country"].items(), key=lambda item: -item[1][0] / item[1][1])
    for code, (copies, campaign, songs) in by_share[:15]:
        typer.echo(f"{code}	{copies}	{campaign}	{songs}	{100 * copies / campaign:.1f}%")
    typer.echo(f"wrote {result['folder']}" if write else "dry run: nothing written")


@campaign_app.command("run")
def campaign_run_command(
    countries: CountriesArgument,
    goal: Annotated[str, typer.Option(help="What the campaign must reach, in one sentence.")],
    min_songs: Annotated[
        int,
        typer.Option(
            "--min-songs",
            help="Open no campaign when the estimates of all dumps of the country sum to "
            "fewer songs. The sum is an upper limit: two dumps can hold the same song.",
        ),
    ] = 25,
    years: YearsOption = None,
) -> None:
    """Run a campaign on the dumps of this disk for each country, one after the other.

    For each country: estimate each dump. When the dumps together would add --min-songs
    songs or more, import every dump that adds a song, and print the report. The campaign
    stays open. --years goes to the goal and the report;
    it does not limit the import. A country that fails does not stop the others.
    """
    from songs.common.paths import data_root
    from songs.stage_00_ingest import campaign_run

    span = _years(years)
    if span:
        goal = f"{goal} (years {span[0]}-{span[1]})"
    failed = []
    for code in [_country(code) for code in countries]:
        try:
            result = campaign_run.run_country(data_root(), code, goal=goal, min_songs=min_songs)
        except Exception as error:
            # One country that fails must not stop the others; the exit code reports it.
            failed.append(code)
            typer.echo(f"error: {code}: {type(error).__name__}: {error}", err=True)
            result = getattr(error, "ladder", None)
        if result is None:
            continue
        typer.echo(
            f"{code}: campaign {result['campaign_id'] or 'not opened'}, "
            f"songs {result['songs_before']} -> {result['songs_after']}"
        )
        for row in result["imported"]:
            typer.echo(
                f"  imported {row['source']}: {row['songs_added']} songs, "
                f"{row['seconds']} s, {row['folder']}"
            )
        absent = sum(row["would_add"] is None for row in result["skipped"])
        for row in result["skipped"]:
            if row["would_add"] is not None:
                typer.echo(
                    f"  skipped {row['source']}: {row['reason']} (would add {row['would_add']})"
                )
        if absent:
            typer.echo(f"  sources with no dump on this disk: {absent}")
        if result["campaign_id"]:
            typer.echo(campaign_run.report(data_root(), code, result["campaign_id"], years=span))
    if failed:
        typer.echo(f"failed: {', '.join(failed)}", err=True)
        raise typer.Exit(1)


@campaign_app.command("report")
def campaign_report(
    iso3: Annotated[str, typer.Argument(help="Country code, three capital letters.")],
    campaign: Annotated[
        str | None, typer.Option(help="Campaign id. The default is the newest campaign.")
    ] = None,
    years: YearsOption = None,
) -> None:
    """Print the report of a campaign of a country as Markdown, built from its records."""
    from songs.common.paths import data_root
    from songs.stage_00_ingest import campaign_run

    try:
        text = campaign_run.report(data_root(), _country(iso3), campaign, years=_years(years))
    except (FileNotFoundError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(text)


@score_app.command("prepare")
def score_prepare(
    countries: Annotated[list[str], typer.Argument(help="Country codes, three letters each.")],
    max_requests: Annotated[
        int, typer.Option(help="Most requests in the batch. The other songs wait.")
    ] = 1_000,
) -> None:
    """Write the batch file of the eligible songs that have no current score. Sends nothing."""
    from songs.common.paths import data_root
    from songs.stage_30_topics import scoring_run

    plan = scoring_run.prepare(data_root(), countries, max_requests)
    for code, counts in plan["countries"].items():
        typer.echo(
            f"{code}: "
            + ", ".join(f"{key} {value}" for key, value in counts.items() if isinstance(value, int))
        )
    estimate = plan["estimate"]
    if not plan["requests"]:
        typer.echo("nothing to score; no run was written")
        return
    typer.echo(
        f"run {plan['run_id']}: {plan['requests']} requests, about {estimate['usd']} USD "
        f"({estimate['input_tokens']} input and {estimate['output_tokens']} output tokens)"
    )


@score_app.command("submit")
def score_submit(
    run_id: Annotated[str, typer.Argument(help="Run id that `songs score prepare` printed.")],
    max_usd: Annotated[float, typer.Option(help="Stop when the estimate is above this.")],
) -> None:
    """Upload the batch file of a prepared run and start the batch. This costs money."""
    from songs.common.paths import data_root
    from songs.stage_30_topics import scoring_run

    plan = scoring_run.read_plan(data_root(), run_id)
    typer.echo(f"run {run_id}: {plan['requests']} requests, about {plan['estimate']['usd']} USD")
    if typer.prompt("Type the run id to send the batch", default="") != run_id:
        raise typer.Exit(1)
    batch = scoring_run.submit(data_root(), run_id, max_usd)
    typer.echo(f"started batch {batch['batch_id']}")


@score_app.command("collect")
def score_collect(
    run_id: Annotated[str, typer.Argument(help="Run id of a submitted run.")],
) -> None:
    """Read the answers of a submitted run and write one scores folder for each country."""
    from songs.common.paths import data_root
    from songs.stage_30_topics import scoring_run

    result = scoring_run.collect(data_root(), run_id)
    typer.echo(f"batch {result['status']}")
    for folder in result["written"]:
        typer.echo(f"wrote {folder}")
    for code, counts in result.get("counts", {}).items():
        typer.echo(f"{code}: " + ", ".join(f"{key} {value}" for key, value in counts.items()))
