"""The campaign ladder for one country, and the report of a campaign.

`run_country` does the steps that need no person and no request: it estimates what
each lyric dump would add to the country, opens a campaign when at least one dump
is worth an import, and imports those dumps, the largest estimate first. Code
decides on each song; no model reads a song. The campaign stays open: a person or
an agent reads the result and closes it with what to try next.

`report` returns Markdown for a pull request, from the campaign record, the run
records of the campaign and the songs folders of the country. It holds counts only.
"""

import time
from collections import Counter
from pathlib import Path

import duckdb

from songs.common import campaigns, lyric_sources, manifests, paths, run_records, schemas
from songs.stage_00_ingest import dump_match

MIN_SONGS = 25
NO_DUMP = "no dump"
UNDER = "under the threshold"
NOTHING = "nothing to add"


def _songs(folder: Path) -> int:
    """Return the number of rows of `songs.parquet`, as the manifest of the folder states it."""
    files = manifests.read_manifest(folder).files
    return next(entry["rows"] for entry in files if entry["path"] == schemas.COUNTRY_SONGS.file)


def _wait_past(run_id: str) -> None:
    """Wait until the UTC second of `run_id` is over, so that the next run id is later."""
    while run_records.new_run_id() <= run_id:
        time.sleep(0.05)


def run_country(
    data: Path,
    iso3: str,
    *,
    goal: str,
    min_songs: int = MIN_SONGS,
    discogs: Path | None = None,
    countries: Path | None = None,
) -> dict:
    """Run the dump ladder for one country. Return what was estimated, imported and skipped.

    The sources are those of `lyric_sources.sources_for`. The threshold is on the
    country: when the newest dumps of all sources would add fewer than `min_songs`
    songs in total, the function opens no campaign and writes nothing, and
    `campaign_id` is None. Otherwise every source that would add 1 song or more is
    imported, the largest estimate first. After the first import, each source is
    estimated again on the new songs folder, because an earlier import can take its
    tracks; a source with nothing left is skipped. The campaign stays open.

    Raise FileExistsError when the country has an open campaign, and
    FileNotFoundError when it has no songs folder. An import that fails stops the
    ladder: its run record has the state `failed`, the campaign stays open, and
    the error is raised again.
    """
    paths.check_iso3(iso3)
    current = run_records.open_campaign_id(iso3, countries)
    if current:
        raise FileExistsError(
            f"{iso3} has an open campaign, {current}. Close it before a new ladder."
        )
    newest = paths.latest_country_songs_dir(data, iso3)
    if newest is None:
        raise FileNotFoundError(f"no songs folder of {iso3}")
    before = _songs(newest)
    sources = [source.id for source in lyric_sources.sources_for(iso3)]
    survey = dump_match.survey(data, iso3, sources, discogs)
    opens = sum(row.get("would_add", 0) for row in survey) >= min_songs
    skipped = [
        {"source": row["source"], "reason": NO_DUMP, "would_add": None}
        if row["dump"] is None
        else {
            "source": row["source"],
            "reason": NOTHING if opens else UNDER,
            "would_add": row["would_add"],
        }
        for row in survey
        if row["dump"] is None or not opens or not row["would_add"]
    ]
    # sorted() keeps the order of the survey for equal estimates.
    todo = sorted(
        (row for row in survey if opens and row.get("would_add")),
        key=lambda row: -row["would_add"],
    )
    result = {
        "campaign_id": None,
        "songs_before": before,
        "songs_after": before,
        "survey": survey,
        "imported": [],
        "skipped": skipped,
    }
    if not todo:
        return result

    _wait_past(newest.name)
    result["campaign_id"] = campaigns.open_campaign(
        iso3, goal, songs_before=before, countries=countries
    ).campaign_id
    for position, row in enumerate(todo):
        source = row["source"]
        if position:
            (again,) = dump_match.survey(data, iso3, [source], discogs)
            if not again["would_add"]:
                skipped.append({"source": source, "reason": NOTHING, "would_add": 0})
                continue
        _wait_past(paths.latest_country_songs_dir(data, iso3).name)
        start = time.monotonic()
        done = dump_match.import_dump(data, source, iso3, discogs, countries=countries)
        result["imported"].append(
            {
                "source": source,
                "songs_added": done["songs_added"],
                "folder": paths.data_relative(data, done["path"]),
                "seconds": round(time.monotonic() - start, 1),
            }
        )
        result["songs_after"] = done["songs"]
    return result


def _by_year(folder: Path) -> Counter:
    """Return the songs of a country folder counted by year. The key None is "no year"."""
    with duckdb.connect() as connection:
        songs = schemas.read_table(schemas.COUNTRY_SONGS, folder, connection, fill_absent=True)
        return Counter(dict(songs.aggregate("year, count(*)").fetchall()))


def _not_scored(data: Path, iso3: str, folder: Path) -> int | None:
    """Return the songs of `folder` with no score of the same lyric text, or None for no scores."""
    scores = paths.latest_country_scores_dir(data, iso3)
    if scores is None:
        return None
    with duckdb.connect() as connection:
        songs = schemas.read_table(schemas.COUNTRY_SONGS, folder, connection, fill_absent=True)
        scored = schemas.read_table(schemas.SCORE_TOPICS, scores, connection)
        songs.project("song_id, lyrics_sha256").create_view("songs")
        scored.project("song_id, lyrics_sha256").create_view("scored")
        return connection.sql(
            "SELECT count(*) FROM songs ANTI JOIN scored USING (song_id, lyrics_sha256)"
        ).fetchall()[0][0]


def _number(value: int | None) -> str:
    return "not recorded" if value is None else str(value)


def report(
    data: Path,
    iso3: str,
    campaign_id: str | None = None,
    *,
    years: tuple[int, int] | None = None,
    countries: Path | None = None,
) -> str:
    """Return the report of one campaign as Markdown. The default is the last campaign.

    "Before" is the newest complete songs folder that is older than the campaign,
    and "after" is the folder of the last complete run of the campaign. A campaign
    with no complete run has the same folder for both. `years` adds one line for
    that range of years, both ends included. The report holds counts only: no lyric
    text, no artist name and no path outside the data folder.
    """
    found = campaigns.read_campaigns(iso3, countries)
    if campaign_id is not None:
        found = [campaign for campaign in found if campaign.campaign_id == campaign_id]
    if not found:
        raise FileNotFoundError(f"{iso3} has no campaign {campaign_id or ''}".strip())
    campaign = found[-1]
    runs = [
        record
        for record in run_records.read_run_records(iso3, countries)
        if record.campaign_id == campaign.campaign_id
    ]
    parent = paths.country_songs_dir(data, iso3, campaign.campaign_id).parent
    earlier = [
        folder
        for folder in sorted(parent.glob("*"))
        if paths.RUN_ID.fullmatch(folder.name)
        and folder.name < campaign.campaign_id
        and (folder / paths.MANIFEST_NAME).is_file()
    ]
    if not earlier:
        raise FileNotFoundError(f"no songs folder of {iso3} is older than the campaign")
    before = earlier[-1]
    complete = [record for record in runs if record.state == "complete"]
    after = paths.country_songs_dir(data, iso3, complete[-1].run_id) if complete else before
    if not (after / paths.MANIFEST_NAME).is_file():
        raise FileNotFoundError(f"{paths.data_relative(data, after)} is not on this disk")

    songs_before, songs_after = _songs(before), _songs(after)
    state = (
        "open" if campaign.is_open else f"{campaign.outcome}, closed on {campaign.closed_utc[:10]}"
    )
    lines = [
        f"# Campaign {campaign.campaign_id} for {iso3}",
        "",
        f"- Goal: {campaign.goal}",
        f"- State: {state}",
        f"- Songs before: {songs_before} songs (`{paths.data_relative(data, before)}`)",
        f"- Songs after: {songs_after} songs (`{paths.data_relative(data, after)}`)",
        f"- Songs added: {songs_after - songs_before} songs",
    ]
    if campaign.next_time:
        lines.append(f"- Next time: {campaign.next_time}")

    lines += [
        "",
        "## Runs",
        "",
        "| Source | Route | State | Songs attempted | Songs accepted | Rows added | Duration |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {run.source} | {run.route} | {run.state} | {_number(run.songs_attempted)} "
        f"| {_number(run.songs_accepted)} | {_number(run.rows_added)} "
        f"| {run_records.duration_text(run) or 'not recorded'} |"
        for run in runs
    ] or ["| none | - | - | - | - | - | - |"]

    rejected: Counter = Counter()
    for run in runs:
        rejected.update(run.songs_rejected or {})
    lines += ["", "## Songs not added, by reason", ""]
    lines += [
        f"- {reason}: {number} songs" for reason, number in rejected.most_common() if number
    ] or ["- none recorded"]

    year_before, year_after = _by_year(before), _by_year(after)
    no_year = (year_before.pop(None, 0), year_after.pop(None, 0))
    decade_before = dump_match.by_decade(year_before)
    decade_after = dump_match.by_decade(year_after)
    lines += [
        "",
        "## Songs by decade",
        "",
        "| Decade | Songs before | Songs after | Songs added |",
        "| --- | --- | --- | --- |",
    ]
    for decade in sorted(set(decade_before) | set(decade_after)):
        old, new = decade_before.get(decade, 0), decade_after.get(decade, 0)
        lines.append(f"| {decade}s | {old} | {new} | {new - old} |")
    lines.append(f"| no year | {no_year[0]} | {no_year[1]} | {no_year[1] - no_year[0]} |")
    lines.append(f"| all | {songs_before} | {songs_after} | {songs_after - songs_before} |")
    if years is not None:
        first, last = years
        old = sum(number for year, number in year_before.items() if first <= year <= last)
        new = sum(number for year, number in year_after.items() if first <= year <= last)
        lines += [
            "",
            f"Years {first} to {last}: {old} songs before, {new} songs after, "
            f"{new - old} songs added.",
        ]

    waiting = _not_scored(data, iso3, after)
    lines += [
        "",
        "## Scoring",
        "",
        "No scores folder: no song of the country has a score."
        if waiting is None
        else f"{waiting} songs wait for scoring: they have no score of their lyric text.",
    ]
    return "\n".join(lines) + "\n"
