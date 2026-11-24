"""Find the Discogs artists that join the roster of a country at campaign time.

    in   <Discogs folder>                 artists, release_artists, releases, release_genres
    in   lyrics/<ISO3>/songs/<run id>/    artists.parquet of the newest complete folder of
                                          every country

A roster holds only the artists that a collection found. A large artist of a country
can be on no roster, and then no dump song of it can be added. `new_artists` returns
the Discogs artists that a campaign of the country treats as roster artists. Each one
holds all of these:

1. At least `MIN_HOME_RELEASES` releases credit it as a main artist (`release_artists`)
   and have a release country that is a home of the country and of no other country
   (`dump_match.load_home_countries`). A release of the USSR is no home release of
   Ukraine, because the USSR is a home of 16 countries.
2. Of its main releases with a release country, at least `MIN_HOME_SHARE` are home
   releases. With a share above one half, no artist has two home countries.
3. The start of its Discogs profile states no country outside the home of the country
   (`artist_country.profile_evidence`).
4. It is not an entry of `NOT_ARTISTS`, such as "Various", and fewer than
   `MAX_NOT_SONG_SHARE` of its main releases have a genre of `NOT_SONG_GENRES`.
5. No roster of a country holds its Discogs id. No roster artist of the country has
   its name key, and no roster artist without a Discogs id of another country has it:
   such an artist can get the id by name (`dump_match.discogs_ids`). No other artist
   of the result has its name key.

The name of the artist is its Discogs name without the homonym mark " (2)", and its
id is `review_workbooks.artist_id` of its Discogs id. The campaign matches the dump
songs of these artists like those of any roster artist with a Discogs id. Only an
artist that gets a song joins the roster of the new folder, with the country tag
`COUNTRY_TAG`.
"""

import functools
import re
from collections import Counter
from pathlib import Path

import duckdb

from songs.common import paths, schemas
from songs.stage_00_ingest import dump_match, review_workbooks
from songs.stage_10_clean import artist_country

MIN_HOME_RELEASES = 5
MIN_HOME_SHARE = 0.8
NOT_SONG_GENRES = ("Classical", "Non-Music")
MAX_NOT_SONG_SHARE = 0.5
# Discogs entries that name no performer: Various, Unknown Artist, No Artist, Traditional,
# Anonymous, Unknown.
NOT_ARTISTS = (194, 355, 118760, 151641, 967691, 20327)
COUNTRY_TAG = "discogs_home_releases"


@functools.lru_cache(maxsize=8)
def home_artists(
    discogs: Path,
    iso3: str,
    min_releases: int = MIN_HOME_RELEASES,
    min_share: float = MIN_HOME_SHARE,
) -> dict[int, tuple[str, str, int, int]]:
    """Return the Discogs artists that hold rules 1 to 4 for `iso3`.

    The value is the name, the name key, the home releases and the main releases
    with a release country. A Discogs folder that lacks a table gives no artist.
    """
    tables = ("artists", "release_artists", "releases", "release_genres")
    homes = dump_match.load_home_countries()
    shared = set().union(*(names for code, names in homes.items() if code != iso3))
    home = homes.get(iso3, frozenset()) - shared
    if not home or not all((discogs / f"{name}.parquet").is_file() for name in tables):
        return {}
    table = {name: dump_match._quoted(discogs / f"{name}.parquet") for name in tables}
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        connection.execute("SET threads = 2")
        dump_match._table(connection, "home", "str", sorted(home))
        dump_match._table(connection, "not_artists", "int64", list(NOT_ARTISTS))
        connection.execute(
            f"""
            CREATE TEMP TABLE at_home AS
            SELECT artist_id, count(DISTINCT release_id) AS home_releases
            FROM {table["release_artists"]}
            WHERE release_id IN (
                SELECT release_id FROM {table["releases"]} WHERE country IN (SELECT value FROM home)
            ) AND artist_id NOT IN (SELECT value FROM not_artists)
            GROUP BY artist_id HAVING count(DISTINCT release_id) >= {int(min_releases)}
            """
        )
        connection.execute(
            f"""
            CREATE TEMP TABLE main AS
            SELECT DISTINCT a.artist_id, a.release_id, r.country <> '' AS has_country
            FROM {table["release_artists"]} AS a
            JOIN {table["releases"]} AS r USING (release_id)
            WHERE a.artist_id IN (SELECT artist_id FROM at_home)
            """
        )
        rows = connection.execute(
            f"""
            SELECT h.artist_id, a.name, a.profile, h.home_releases, m.with_country
            FROM at_home AS h
            JOIN (
                SELECT artist_id, count_if(has_country) AS with_country, count(*) AS releases
                FROM main GROUP BY artist_id
            ) AS m USING (artist_id)
            JOIN {table["artists"]} AS a USING (artist_id)
            LEFT JOIN (
                SELECT artist_id, count(DISTINCT release_id) AS not_song FROM main
                WHERE release_id IN (
                    SELECT release_id FROM {table["release_genres"]}
                    WHERE genre IN {NOT_SONG_GENRES}
                ) GROUP BY artist_id
            ) AS g USING (artist_id)
            WHERE h.home_releases >= {float(min_share)} * m.with_country
                AND coalesce(g.not_song, 0) < {float(MAX_NOT_SONG_SHARE)} * m.releases
            """
        ).fetchall()
    codes = artist_country.home_codes(iso3)
    found = {}
    for number, name, profile, at_home, with_country in rows:
        bare = re.sub(dump_match._HOMONYM, "", name or "")
        stated, _ = artist_country.profile_evidence(profile, codes, (bare,))
        if stated in ("", *codes):
            found[number] = (bare, dump_match.name_key(bare), at_home, with_country)
    return found


def _rosters(data: Path) -> dict[str, list[tuple[str, str | None]]]:
    """Return the name key and the Discogs id of each roster artist, for each country."""
    rosters = {}
    with duckdb.connect() as connection:
        for parent in sorted((data / "lyrics").glob("*")):
            folder = (
                paths.latest_country_songs_dir(data, parent.name)
                if paths.ISO3.fullmatch(parent.name)
                else None
            )
            if folder is not None:
                rosters[parent.name] = [
                    (dump_match.name_key(name), number)
                    for name, number in schemas.read_table(
                        schemas.COUNTRY_ARTISTS, folder, connection
                    )
                    .project("artist_name, discogs_artist_id")
                    .fetchall()
                ]
    return rosters


def new_artists(
    data: Path,
    discogs: Path,
    iso3: str,
    min_releases: int = MIN_HOME_RELEASES,
    min_share: float = MIN_HOME_SHARE,
) -> dict[str, tuple[str, str]]:
    """Return the artists of the rule for `iso3`: artist id -> (artist name, Discogs id).

    The order is by Discogs id.
    """
    found = home_artists(discogs.resolve(), paths.check_iso3(iso3), min_releases, min_share)
    if not found:
        return {}
    taken_ids, taken_keys = set(), set()
    for code, roster in _rosters(data).items():
        taken_ids |= {str(number) for _, number in roster if number}
        taken_keys |= {key for key, number in roster if code == iso3 or not number}
    counts = Counter(row[1] for row in found.values())
    taken_keys |= {key for key, count in counts.items() if count > 1}
    return {
        review_workbooks.artist_id(iso3, name, str(number)): (name, str(number))
        for number, (name, key, _, _) in sorted(found.items())
        if key and str(number) not in taken_ids and key not in taken_keys
    }
