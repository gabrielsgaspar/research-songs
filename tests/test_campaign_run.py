"""The campaign ladder and its report, on small invented tables."""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from songs.common import campaigns, manifests, paths, run_records, schemas
from songs.stage_00_ingest import campaign_run, dump_match
from songs.stage_00_ingest.campaign_run import NO_DUMP, UNDER, report, run_country

RUN = "20260101T000000Z"
ANNA = "Anna Jons"


def write(table: schemas.Table, folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    names = [column.name for column in table.all_columns]
    schemas.write_table(
        table, schemas.cast_to_schema(table, pd.DataFrame(rows).reindex(columns=names)), folder
    )


def write_dump(data: Path, source: str, songs: list[tuple[str, str, str]]) -> None:
    """Write a complete dump of `source`: one credit of Anna Jons for each (id, title, hash)."""
    folder = paths.clean_dump_dir(data, source, "20260102")
    rows = [
        {
            "source": source,
            "source_song_id": song_id,
            "artist_name": ANNA,
            "source_artist_id": ANNA,
            "credit_position": 1,
            "song_name": title,
            "lyrics": "invented line",
            "lyrics_sha256": sha,
        }
        for song_id, title, sha in songs
    ]
    write(schemas.DUMP_SONGS, folder, rows)
    name = {"source": source, "source_artist_id": ANNA, "artist_name": ANNA, "name_type": "primary"}
    write(schemas.DUMP_ARTIST_NAMES, folder, [name])
    manifests.write_manifest(data, folder, "clean_dump", source=source, inputs=["raw/x/20260101/"])


def make_data(data: Path) -> None:
    """Write ISL with 2 songs, the Discogs catalog, and the dumps of `lrclib` and `genius`.

    `lrclib` would add 3 songs and `genius` 2. One song of `genius` has the lyric
    text of a song of `lrclib`, so `genius` adds 1 song after the import of `lrclib`.
    """
    country = paths.country_songs_dir(data, "ISL", RUN)
    song = {
        "country_iso3": "ISL",
        "artist_id": "a1",
        "artist_name": ANNA,
        "source": "invented",
        "lyrics": "invented line",
        "route": "old_layout",
        "run_id": RUN,
    }
    write(
        schemas.COUNTRY_SONGS,
        country,
        [
            song | {"song_id": "s1", "song_name": "Old Song", "lyrics_sha256": "h1"},
            song | {"song_id": "s2", "song_name": "Sol sol", "lyrics_sha256": "other"},
        ],
    )
    roster = {
        "country_iso3": "ISL",
        "artist_id": "a1",
        "artist_name": "Anna Jóns",
        "discogs_artist_id": "11",
        "attempted": True,
        "songs": 2,
    }
    write(schemas.COUNTRY_ARTISTS, country, [roster])
    write(schemas.COUNTRY_LINKS, country, [])
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )

    catalog = paths.clean_catalog_dir(data, "discogs", "20260101")
    catalog.mkdir(parents=True)
    tables = {
        "release_artists": "SELECT * FROM (VALUES (100, 11), (200, 11)) "
        "AS t(release_id, artist_id)",
        "release_track_artists": "SELECT * FROM (VALUES (300, 2, 11)) "
        "AS t(release_id, track_index, artist_id)",
        "release_tracklist": "SELECT * FROM (VALUES (100, 3, 'Duet (Radio Edit)'), "
        "(200, 2, 'Riverside'), (200, 3, 'A New Song'), (300, 2, 'Night Train')) "
        "AS t(release_id, track_index, title)",
        "releases": "SELECT * FROM (VALUES (100, 50, '1999-05-00'), (200, NULL, '1995'), "
        "(300, NULL, '2001')) AS t(release_id, master_id, released)",
        "masters": "SELECT * FROM (VALUES (50, 1997)) AS t(master_id, year)",
    }
    for name, sql in tables.items():
        duckdb.sql(sql).write_parquet(str(catalog / f"{name}.parquet"))
    manifests.write_manifest(
        data, catalog, "clean_catalog", source="discogs", inputs=["raw/discogs/20260101/"]
    )

    write_dump(
        data,
        "lrclib",
        [("d3", "A New Song", "h3"), ("d7", "Duet", "h7"), ("e1", "Riverside", "h9")],
    )
    write_dump(data, "genius", [("g3", "A New Song", "h3"), ("g1", "Night Train", "h10")])


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    make_data(tmp_path / "data")
    return tmp_path / "data", tmp_path / "countries"


def test_under_the_threshold_nothing_is_opened_or_written(folders, tmp_path):
    data, countries = folders

    def outside() -> list[Path]:
        return sorted(path for path in tmp_path.rglob("*") if "cache" not in path.parts)

    before = outside()

    result = run_country(data, "ISL", goal="More songs", countries=countries)

    assert outside() == before
    assert (result["campaign_id"], result["imported"]) == (None, [])
    assert (result["songs_before"], result["songs_after"]) == (2, 2)
    skipped = {row["source"]: (row["reason"], row["would_add"]) for row in result["skipped"]}
    assert skipped["lrclib"] == (UNDER, 3)
    assert skipped["genius"] == (UNDER, 2)
    assert skipped["musik_is"] == (NO_DUMP, None)
    assert len(result["survey"]) == len(result["skipped"])


def test_two_sources_import_in_estimate_order_and_the_second_is_estimated_again(folders):
    data, countries = folders

    result = run_country(data, "ISL", goal="More songs", min_songs=1, countries=countries)

    estimates = {row["source"]: row.get("would_add") for row in result["survey"]}
    assert (estimates["lrclib"], estimates["genius"]) == (3, 2)
    assert [(row["source"], row["songs_added"]) for row in result["imported"]] == [
        ("lrclib", 3),
        ("genius", 1),
    ]
    assert (result["songs_before"], result["songs_after"]) == (2, 6)
    assert run_records.open_campaign_id("ISL", countries) == result["campaign_id"]
    (campaign,) = campaigns.read_campaigns("ISL", countries)
    assert (campaign.goal, campaign.songs_before, campaign.is_open) == ("More songs", 2, True)
    records = run_records.read_run_records("ISL", countries)
    assert [record.source for record in records] == ["lrclib", "genius"]
    assert {record.campaign_id for record in records} == {result["campaign_id"]}
    newest = paths.latest_country_songs_dir(data, "ISL")
    assert result["imported"][-1]["folder"] == paths.data_relative(data, newest)
    assert all(row["reason"] == NO_DUMP for row in result["skipped"])


def test_a_source_that_falls_under_the_threshold_after_an_import_is_skipped(folders):
    data, countries = folders

    result = run_country(data, "ISL", goal="More songs", min_songs=2, countries=countries)

    assert [row["source"] for row in result["imported"]] == ["lrclib"]
    assert {"source": "genius", "reason": UNDER, "would_add": 1} in result["skipped"]
    assert result["songs_after"] == 5


def test_an_open_campaign_or_a_country_with_no_songs_is_refused(folders):
    data, countries = folders
    with pytest.raises(FileNotFoundError, match="no songs folder of NOR"):
        run_country(data, "NOR", goal="More songs", countries=countries)
    campaigns.open_campaign("ISL", "An earlier goal", countries=countries)
    with pytest.raises(FileExistsError, match="has an open campaign"):
        run_country(data, "ISL", goal="More songs", min_songs=1, countries=countries)
    assert run_records.read_run_records("ISL", countries) == []


def test_a_failing_import_leaves_the_campaign_open_and_a_failed_run_record(folders, monkeypatch):
    data, countries = folders

    def fail(*args, **kwargs):
        raise RuntimeError("invented failure")

    monkeypatch.setattr(dump_match, "_added_frames", fail)
    with pytest.raises(RuntimeError, match="invented failure"):
        run_country(data, "ISL", goal="More songs", min_songs=1, countries=countries)

    assert run_records.open_campaign_id("ISL", countries) is not None
    (record,) = run_records.read_run_records("ISL", countries)
    assert (record.source, record.state) == ("lrclib", "failed")
    assert paths.latest_country_songs_dir(data, "ISL").name == RUN


def cells(text: str, first: str) -> list[str]:
    """Return the cells of the table row of `text` whose first cell is `first`."""
    (line,) = [line for line in text.splitlines() if line.startswith(f"| {first} |")]
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_the_report_totals_equal_the_manifests_and_the_decades_sum_to_them(folders):
    data, countries = folders
    result = run_country(data, "ISL", goal="More songs", min_songs=1, countries=countries)

    text = report(data, "ISL", years=(1995, 1995), countries=countries)

    after = paths.latest_country_songs_dir(data, "ISL")
    assert f"- Songs before: 2 songs (`lyrics/ISL/songs/{RUN}/`)" in text
    assert f"- Songs after: 6 songs (`lyrics/ISL/songs/{after.name}/`)" in text
    assert manifests.read_manifest(after).counts["songs"] == 6
    assert "- State: open" in text
    assert cells(text, "lrclib")[1:6] == ["dump_name", "complete", "3", "3", "3"]
    assert cells(text, "genius")[1:6] == ["dump_name", "complete", "2", "1", "1"]
    assert "- held: 1 songs" in text
    assert cells(text, "1990s") == ["1990s", "0", "3", "3"]
    assert cells(text, "2000s") == ["2000s", "0", "1", "1"]
    assert cells(text, "no year") == ["no year", "2", "2", "0"]
    rows = [cells(text, name) for name in ("1990s", "2000s", "no year")]
    assert [str(sum(int(row[i]) for row in rows)) for i in (1, 2, 3)] == cells(text, "all")[1:]
    assert "Years 1995 to 1995: 0 songs before, 2 songs after, 2 songs added." in text
    assert "No scores folder" in text
    assert "invented line" not in text and ANNA not in text and str(data.parent) not in text
    assert text == report(
        data, "ISL", result["campaign_id"], years=(1995, 1995), countries=countries
    )

    scores = paths.country_scores_dir(data, "ISL", "20260103T000000Z")
    row = {"country_iso3": "ISL", "song_id": "s1", "lyrics_sha256": "h1"}
    write(schemas.SCORE_TOPICS, scores, [row])
    schemas.write_table(
        schemas.SCORE_PROVENANCE, schemas.empty_table(schemas.SCORE_PROVENANCE), scores
    )
    manifests.write_manifest(
        data,
        scores,
        "country_scores",
        country_iso3="ISL",
        run_id="20260103T000000Z",
        inputs=[f"lyrics/ISL/songs/{RUN}/"],
    )
    campaigns.close_campaign(
        "ISL", "complete", "Try the site archives.", songs_after=6, countries=countries
    )
    text = report(data, "ISL", countries=countries)
    assert "5 songs wait for scoring" in text
    assert "- State: complete, closed on " in text
    assert "- Next time: Try the site archives." in text
    with pytest.raises(FileNotFoundError, match="no campaign"):
        report(data, "ISL", "20200101T000000Z", countries=countries)


def test_the_wait_ends_when_the_second_of_the_run_id_is_over(monkeypatch):
    ids = iter(["20260101T000000Z", "20260101T000000Z", "20260101T000001Z"])
    naps = []
    monkeypatch.setattr(campaign_run.run_records, "new_run_id", lambda: next(ids))
    monkeypatch.setattr(campaign_run.time, "sleep", naps.append)
    campaign_run._wait_past("20260101T000000Z")
    assert len(naps) == 2
