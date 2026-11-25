"""The Discogs artists that join the roster of a country at campaign time, on invented tables."""

from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records, schemas
from songs.stage_00_ingest import discogs_roster, dump_match
from songs.stage_00_ingest.review_workbooks import artist_id

RUN = "20260101T000000Z"


def write(table: schemas.Table, folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    names = [column.name for column in table.all_columns]
    schemas.write_table(
        table, schemas.cast_to_schema(table, pd.DataFrame(rows).reindex(columns=names)), folder
    )


def roster(data: Path, iso3: str, artists: list[tuple[str, str | None]]) -> Path:
    """Write a complete songs folder of `iso3` with no song and these (name, Discogs id)."""
    folder = paths.country_songs_dir(data, iso3, RUN)
    write(schemas.COUNTRY_SONGS, folder, [])
    write(
        schemas.COUNTRY_ARTISTS,
        folder,
        [
            {
                "country_iso3": iso3,
                "artist_id": f"{iso3}{number}",
                "artist_name": name,
                "discogs_artist_id": discogs_id,
                "attempted": True,
                "songs": 0,
            }
            for number, (name, discogs_id) in enumerate(artists)
        ],
    )
    write(schemas.COUNTRY_LINKS, folder, [])
    manifests.write_manifest(
        data, folder, "country_songs", country_iso3=iso3, run_id=RUN, inputs=["lyrics/x/"]
    )
    return folder


def write_discogs(folder: Path, artists: list[tuple], releases: dict[int, list[str]]) -> None:
    """Invented Discogs tables.

    `artists` holds (id, name, profile, genre); `releases` gives the release countries
    of the main releases of each artist. Release 1000 * id has the track "Night Song".
    """
    folder.mkdir(parents=True)
    rows = [
        (1000 * number + index, number, country)
        for number, countries in releases.items()
        for index, country in enumerate(countries)
    ]
    genre = {number: kind for number, _, _, kind in artists}
    frames = {
        "artists": pd.DataFrame(
            [row[:3] for row in artists], columns=["artist_id", "name", "profile"]
        ),
        "release_artists": pd.DataFrame(
            [row[:2] for row in rows], columns=["release_id", "artist_id"]
        ),
        "releases": pd.DataFrame(
            [(row[0], None, "1980", row[2]) for row in rows],
            columns=["release_id", "master_id", "released", "country"],
        ).astype({"master_id": "Int64"}),
        "release_genres": pd.DataFrame(
            [(row[0], genre[row[1]]) for row in rows], columns=["release_id", "genre"]
        ),
        "release_tracklist": pd.DataFrame(
            [(1000 * number, 1, "Night Song") for number in releases],
            columns=["release_id", "track_index", "title"],
        ),
        "release_track_artists": pd.DataFrame(
            {"release_id": [], "track_index": [], "artist_id": []}, dtype="int64"
        ),
        "masters": pd.DataFrame({"master_id": [], "year": []}, dtype="int64"),
    }
    for name, frame in frames.items():
        duckdb.from_df(frame).write_parquet(str(folder / f"{name}.parquet"))


def test_only_an_artist_with_strong_home_evidence_and_on_no_roster_joins(tmp_path):
    data, discogs = tmp_path / "data", tmp_path / "discogs"
    roster(data, "ISL", [("Anna Jóns", None)])
    roster(data, "NOR", [("Someone", "5"), ("Elín", None)])
    at_home = ["Iceland"] * 3
    write_discogs(
        discogs,
        [
            (1, "Björk (2)", "Icelandic singer.", "Pop"),
            (2, "Half", None, "Pop"),
            (3, "Stated", "Norwegian singer who lives in Iceland.", "Pop"),
            (4, "Classic", None, "Classical"),
            (5, "Taken", None, "Pop"),
            (6, "Anna Jons", None, "Pop"),
            (7, "Elin", None, "Pop"),
            (8, "One", None, "Pop"),
            (9, "Twin", None, "Pop"),
            (10, "Twin (2)", None, "Pop"),
            (11, "Soviet Star", None, "Pop"),
            (12, "Kyiv Band", None, "Pop"),
        ],
        {
            1: [*at_home, "US"],
            2: ["Iceland", "Iceland", "US", "US"],
            **{number: at_home for number in (3, 4, 5, 6, 7, 9, 10)},
            8: ["Iceland"],
            11: ["USSR"] * 3,
            12: ["Ukraine"] * 3,
        },
    )

    found = discogs_roster.new_artists(data, discogs, "ISL", min_releases=2, min_share=0.7)

    # Half: a share below S. Stated: another country in the profile. Classic: not songs.
    # Taken: an id of a roster. Anna Jons: a name of the roster. Elin: a name with no id
    # on another roster. One: too few releases. Twin: two artists with one name key.
    assert found == {artist_id("ISL", "Björk", "1"): ("Björk", "1")}
    # A release of the USSR is a home release of 16 countries, so it is no evidence.
    assert discogs_roster.new_artists(data, discogs, "UKR", 2, 0.7) == {
        artist_id("UKR", "Kyiv Band", "12"): ("Kyiv Band", "12")
    }
    # The defaults ask for more releases.
    assert discogs_roster.new_artists(data, discogs, "ISL") == {}


def test_a_campaign_adds_the_song_of_a_new_artist_and_the_artist_joins_the_roster(tmp_path):
    data, countries, discogs = tmp_path / "data", tmp_path / "countries", tmp_path / "discogs"
    dump = paths.clean_dump_dir(data, "kasilyrics", "20260102")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            {
                "source": "kasilyrics",
                "source_song_id": song_id,
                "artist_name": "Bjork",
                "source_artist_id": "b",
                "credit_position": 1,
                "song_name": title,
                "lyrics": f"an invented line of text for the tests, song {song_id}",
                "lyrics_sha256": song_id,
            }
            for song_id, title in (("b1", "Night Song"), ("b2", "No Such Track"))
        ],
    )
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    roster(data, "ISL", [("Anna Jóns", "11")])
    releases = discogs_roster.MIN_HOME_RELEASES
    write_discogs(discogs, [(1, "Björk (2)", None, "Pop")], {1: ["Iceland"] * releases})

    (row,) = dump_match.survey(data, "ISL", ["kasilyrics"], discogs)
    assert (row["would_add"], row["would_add_new_artists"]) == (1, 1)

    result = dump_match.import_dump(data, "kasilyrics", "ISL", discogs, countries=countries)

    assert result["songs_added"] == 1
    out = result["path"]
    new = artist_id("ISL", "Björk", "1")
    assert duckdb.sql(
        "SELECT artist_id, artist_name, discogs_artist_id, country_tag, songs "
        f"FROM '{(out / 'artists.parquet').as_posix()}' ORDER BY artist_name"
    ).fetchall() == [
        ("ISL0", "Anna Jóns", "11", None, 0),
        (new, "Björk", "1", discogs_roster.COUNTRY_TAG, 1),
    ]
    assert manifests.read_manifest(out).counts["artists_added_by_discogs_home_rule"] == 1
    (record,) = run_records.read_run_records("ISL", countries)
    assert "1 artists joined the roster by the Discogs home rule" in record.notes
    # On the roster now, the artist is no new artist of a later campaign.
    assert discogs_roster.new_artists(data, discogs, "ISL") == {}
