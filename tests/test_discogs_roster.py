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


def write_dump(data: Path, names: dict[str, int], source: str = "genius") -> Path:
    """Write a dump folder in which each credited name has the given number of songs."""
    dump = paths.clean_dump_dir(data, source, "20260102")
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            {
                "source": source,
                "source_song_id": f"{name}-{index}",
                "artist_name": name,
                "source_artist_id": name,
                "credit_position": 1,
                "song_name": f"Title {index}",
                "lyrics": "an invented line of text for the tests",
                "lyrics_sha256": f"{name}-{index}",
            }
            for name, songs in names.items()
            for index in range(songs)
        ],
    )
    return dump


def test_loose_key_drops_brackets_joining_words_and_spaces_in_python_and_in_sql():
    names = ["Alexis y Fido", "Alexis & Fido", "Siggi (The Voice)", "Y la Banda", "Ana e Bia"]
    assert [discogs_roster.loose_key(name) for name in names] == [
        "alexisfido",
        "alexisfido",
        "siggi",
        "labanda",
        "anabia",
    ]
    # A Discogs homonym mark stays: it names another artist.
    assert discogs_roster.loose_key("Sandro (25)") == "sandro25"
    query = f"SELECT {discogs_roster._LOOSE_SQL} FROM (SELECT ? AS key)"
    with duckdb.connect() as connection:
        for name in names:
            key = dump_match.name_key(name.split(" (")[0])
            found = connection.execute(query, [key]).fetchall()
            assert found == [(discogs_roster.loose_key(name),)]


def test_a_dump_name_on_no_roster_gets_a_discogs_artist_by_profile_or_by_top_country(tmp_path):
    data, discogs = tmp_path / "data", tmp_path / "discogs"
    roster(data, "ISL", [("Anna Jons", None), ("Stated (2)", None)])
    norway = [("Elin & Co", "50"), ("Other Spelling", "21"), ("Topper", None), ("Shared", None)]
    roster(data, "NOR", norway)
    many = discogs_roster.MIN_DUMP_SONGS
    names = ["Stated", "Topper", "Shared", "Abroad", "Anna Jons", "Elin y Co", "Jon and Gunna"]
    names += ["Siggi (The Voice)", "Classic", "Various", "Held Name", "Nora"]
    dump = write_dump(
        data, {name: many for name in names} | {"Few": many - 1, "Jon y Gunna": many + 2}
    )
    write_discogs(
        discogs,
        [
            (1, "Stated", "Icelandic singer.", "Pop"),
            (2, "Topper", None, "Pop"),
            (3, "Abroad", None, "Pop"),
            (4, "Few", None, "Pop"),
            (6, "Anna Jons", None, "Pop"),
            (7, "Elin & Co", None, "Pop"),
            (8, "Jon & Gunna", None, "Pop"),
            (9, "Siggi", None, "Pop"),
            (10, "Classic", None, "Classical"),
            (194, "Various", None, "Pop"),
            (21, "Held Name", None, "Pop"),
            (22, "Nora", "Norwegian singer.", "Pop"),
            (23, "Shared", None, "Pop"),
        ],
        {
            1: ["US"],
            2: ["Iceland"] * 3 + ["US"],
            23: ["Iceland"] * 3 + ["Norway"],
            3: ["Iceland", "Iceland", "US", "US", "US"],
            **{number: ["Iceland"] * 3 for number in (4, 6, 7, 8, 9, 10, 194, 21)},
            22: ["US"],
        },
    )
    rosters = discogs_roster._rosters(data)

    found = discogs_roster.dump_artists(discogs, "ISL", dump, rosters)

    # Stated: T1 with no home release; "Stated (2)" of the roster is another artist.
    # Topper: T2, and on another roster with no id. Shared: on the roster of Norway with
    # no id, and with a release in Norway, so that artist can get the id by name.
    # Jon y Gunna: the loose key, and of two names of one Discogs artist the name with
    # more songs. Siggi: brackets dropped. Abroad: its top country is US. Few: too few
    # songs. Anna Jons: a key of the roster of the country. Elin y Co: a loose key of a
    # roster artist with an id. Classic: not songs. Various: no performer. Held Name:
    # its Discogs id is on a roster. Nora: the profile states Norway.
    assert found == {
        artist_id("ISL", "Stated", "1"): ("Stated", "1"),
        artist_id("ISL", "Topper", "2"): ("Topper", "2"),
        artist_id("ISL", "Jon y Gunna", "8"): ("Jon y Gunna", "8"),
        artist_id("ISL", "Siggi (The Voice)", "9"): ("Siggi (The Voice)", "9"),
    }
    assert discogs_roster.dump_artists(discogs, "NOR", dump, rosters) == {
        artist_id("NOR", "Nora", "22"): ("Nora", "22")
    }


def test_of_several_candidates_only_a_dominant_one_wins(tmp_path):
    data, discogs = tmp_path / "data", tmp_path / "discogs"
    roster(data, "ISL", [])
    many = discogs_roster.MIN_DUMP_SONGS
    dump = write_dump(data, {"Duo": many, "Pair": many, "Same": many})
    write_discogs(
        discogs,
        [
            (1, "Duo", None, "Pop"),
            (2, "Duo (2)", "Norwegian band.", "Pop"),
            (3, "Pair", None, "Pop"),
            (4, "Pair (2)", "Norwegian band.", "Pop"),
            (5, "Same", "Icelandic band.", "Pop"),
            (6, "Same (2)", None, "Pop"),
        ],
        {1: ["Iceland"] * 5, 2: ["Norway"], 3: ["Iceland"] * 4, 4: ["Norway"], 6: ["Iceland"] * 3},
    )
    rosters = discogs_roster._rosters(data)

    # Duo: 5 home releases against 1. Pair: 4 against 1 is below 5 times. Same: the
    # Discogs artist that states Iceland has no release, and 3 against 0 wins.
    assert discogs_roster.dump_artists(discogs, "ISL", dump, rosters) == {
        artist_id("ISL", "Duo", "1"): ("Duo", "1"),
        artist_id("ISL", "Same", "6"): ("Same", "6"),
    }
    assert discogs_roster.dump_artists(discogs, "NOR", dump, rosters) == {}


def test_new_artists_adds_the_dump_rule_only_with_a_dump_and_the_home_rule_wins(tmp_path):
    data, discogs = tmp_path / "data", tmp_path / "discogs"
    roster(data, "ISL", [])
    many = discogs_roster.MIN_DUMP_SONGS
    dump = write_dump(data, {"Bjork": many, "Topper": many})
    home = ["Iceland"] * discogs_roster.MIN_HOME_RELEASES
    write_discogs(
        discogs, [(1, "Björk", None, "Pop"), (2, "Topper", None, "Pop")], {1: home, 2: home[:3]}
    )

    assert discogs_roster.new_artists(data, discogs, "ISL") == {
        artist_id("ISL", "Björk", "1"): ("Björk", "1")
    }
    assert discogs_roster.new_artists(data, discogs, "ISL", dump=dump) == {
        artist_id("ISL", "Björk", "1"): ("Björk", "1"),
        artist_id("ISL", "Topper", "2"): ("Topper", "2"),
    }


def test_a_dump_name_spelled_another_way_finds_its_discogs_artist(tmp_path):
    data, discogs = tmp_path / "data", tmp_path / "discogs"
    roster(data, "ISL", [])
    many = discogs_roster.MIN_DUMP_SONGS
    dump = write_dump(data, {"Sherali Jo'rayev": many, "Ali Valiyev": many, "Ali Valiyeva": many})
    write_discogs(
        discogs,
        [
            (1, "Sherali Juraev", "Icelandic singer.", "Pop"),
            (2, "Ali Valiev", None, "Pop"),
            (3, "Ali Valiev (2)", None, "Pop"),
        ],
        {1: ["US"], 2: ["Iceland"] * 3, 3: ["Iceland"] * 3},
    )

    # Sherali: one spelling key on each side. Ali Valiyev: two Discogs artists share its
    # spelling key and have the same evidence, so neither wins.
    assert discogs_roster.dump_artists(discogs, "ISL", dump, discogs_roster._rosters(data)) == {
        artist_id("ISL", "Sherali Jo'rayev", "1"): ("Sherali Jo'rayev", "1")
    }


def test_a_roster_the_dump_does_not_serve_and_a_shared_home_stop_no_artist(tmp_path):
    data, discogs = tmp_path / "data", tmp_path / "discogs"
    roster(data, "CZE", [("Hana Singer", None)])
    roster(data, "DEU", [("Olympic", "1")])
    roster(data, "SVK", [])
    many = discogs_roster.MIN_DUMP_SONGS
    names = {"Olympic": many, "Hana Singer": many}
    write_discogs(
        discogs,
        [
            (1, "Olympic", "German electronic act.", "Electronic"),
            (2, "Olympic (2)", "Czech rock group.", "Rock"),
            (3, "Hana Singer", "Slovak singer.", "Pop"),
        ],
        {1: ["Germany"], 2: ["Czechoslovakia"] * 3, 3: ["Czechoslovakia"] * 3},
    )
    rosters = discogs_roster._rosters(data)

    # karaoketexty serves CZE and SVK: the German roster holds no name of it. A global
    # dump keeps the old rule, so "Olympic" of the German roster stops the band.
    czech = write_dump(data, names, "karaoketexty")
    assert discogs_roster.dump_artists(discogs, "CZE", czech, rosters) == {
        artist_id("CZE", "Olympic", "2"): ("Olympic", "2")
    }
    assert discogs_roster.dump_artists(discogs, "CZE", write_dump(data, names), rosters) == {}
    # Hana Singer is on the Czech roster with no id; her releases are in Czechoslovakia,
    # a home of CZE and of SVK, so she joins the roster of SVK.
    assert discogs_roster.dump_artists(discogs, "SVK", czech, rosters) == {
        artist_id("SVK", "Hana Singer", "3"): ("Hana Singer", "3")
    }


def test_an_artist_that_the_tracked_list_gives_another_country_is_on_no_roster(tmp_path):
    data, root = tmp_path / "data", tmp_path / "root"
    roster(data, "CZE", [("Band", "7"), ("Other", None)])
    (root / "resources" / "lyrics").mkdir(parents=True)
    # roster() names the first artist of CZE "CZE0".
    (root / "resources" / "lyrics" / "artist_countries.csv").write_text(
        "artist_id,country_iso3\nCZE0,SVK\n", encoding="utf-8"
    )
    assert discogs_roster._rosters(data, root) == {"CZE": [("Other", None)]}
