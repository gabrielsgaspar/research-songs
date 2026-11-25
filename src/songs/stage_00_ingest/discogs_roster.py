"""Find the Discogs artists that join the roster of a country at campaign time.

    in   <Discogs folder>                 artists, release_artists, releases, release_genres
    in   lyrics/<ISO3>/songs/<run id>/    artists.parquet of the newest complete folder of
                                          every country
    in   clean/dumps/<source>/<YYYYMMDD>/ songs.parquet of the dump: the credited names
                                          and the song ids, never the lyric text

A roster holds only the artists that a collection found. A large artist of a country
can be on no roster, and then no dump song of it can be added. `new_artists` returns
the Discogs artists that a campaign of the country treats as roster artists. They come
from two rules: the home rule (`home_artists`) and the dump rule (`dump_artists`).

The home rule takes each Discogs artist that holds all of these:

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

The name of such an artist is its Discogs name without the homonym mark " (2)".

The dump rule starts from the dump of the campaign. A credited name with at least
`MIN_DUMP_SONGS` songs in the dump looks for a Discogs artist, unless its name key or
its loose key (`loose_key`) is a key of a roster artist of the country, or of a roster
artist with a Discogs id of another country: that artist may hold the songs. A key of
a roster artist with no Discogs id of another country stops the name only when the
winning Discogs artist has a release in a home of that country, because then that
artist can get the id by name (`dump_match.discogs_ids`). The
candidates are the Discogs artists with the same name key or the same loose key. A
candidate that is in `NOT_ARTISTS`, whose id a roster holds, whose name key is the key
of a roster artist with a Discogs id, or that has `MAX_NOT_SONG_SHARE` or more of its
main releases in `NOT_SONG_GENRES` is left out. Each other candidate gets at most one
country:

- T1: the start of its profile states the country (`artist_country.profile_evidence`).
  The statement must name the country itself: `artist_country.home_codes` counts USA
  as a home of PRI, and then American stars would join PRI.
- T2: the profile states no country, its top release country (`artist_country.top_country`)
  is a home of one country only, and at least `MIN_EVIDENCE_RELEASES` of its main
  releases are homes of that country only.

A candidate counts with its home releases. When only one candidate has a country, it
wins. When several have one, the candidate with at least `DOMINANCE` times the home
releases of the next wins, if it has `MIN_EVIDENCE_RELEASES` or more. Otherwise the
name gets no artist. The name joins the country only when the winner has that
country. The name of such an artist is the most common credited spelling of the
dump, so that the dump songs match it. When two names win the same Discogs artist,
the name with more songs keeps it. On 2026-11-25, on the musica dump, a sample of 80
artists of this rule in 8 countries had 69 right, 11 doubtful and 1 wrong. Wrong
artists are mostly T2 artists with a career in a large market, such as a Guatemalan
band with most releases in Mexico. A test that asked T2 artists for a first release
at home removed 3 of 6 known wrong artists (about 140 songs), and also about 10
artists that looked right (about 350 songs), so the rule does not ask for it.

Each artist of the result has the id `review_workbooks.artist_id` of its Discogs id,
and an artist of the home rule wins over the same Discogs artist of the dump rule.
The campaign matches the dump songs of these artists like those of any roster artist
with a Discogs id. Only an artist that gets a song joins the roster of the new folder,
with the country tag `COUNTRY_TAG`.
"""

import functools
import re
from collections import Counter, defaultdict
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
MIN_DUMP_SONGS = 10
MIN_EVIDENCE_RELEASES = 3
DOMINANCE = 5
# The words that join two performers in a loose key ("&" is no letter, so the name key drops it).
_LOOSE_WORDS = r"(^| )(y|and|e|et)( |$)"
_LOOSE_SQL = f"replace(regexp_replace(key, '{_LOOSE_WORDS}', ' ', 'g'), ' ', '')"


def loose_key(name: str | None) -> str:
    """Return the loose key of a name: the name key without brackets, joining words and spaces.

    "Alexis y Fido", "Alexis & Fido" and "José Luis Rodríguez (El Puma)" give
    "alexisfido", "alexisfido" and "joseluisrodriguez". A bracket with only a number
    stays: "Sandro (25)" is the Discogs name of another artist than "Sandro", and
    rosters keep such names. `_LOOSE_SQL` does the same from a name key in SQL.
    """
    key = dump_match.name_key(re.sub(r"[(\[](?!\d+[)\]])[^)\]]*[)\]]", " ", name or ""))
    return re.sub(_LOOSE_WORDS, " ", key).replace(" ", "")


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
    """Return the name and the Discogs id of each roster artist, for each country."""
    rosters = {}
    with duckdb.connect() as connection:
        for parent in sorted((data / "lyrics").glob("*")):
            folder = (
                paths.latest_country_songs_dir(data, parent.name)
                if paths.ISO3.fullmatch(parent.name)
                else None
            )
            if folder is not None:
                rosters[parent.name] = (
                    schemas.read_table(schemas.COUNTRY_ARTISTS, folder, connection)
                    .project("artist_name, discogs_artist_id")
                    .fetchall()
                )
    return rosters


def _dump_names(dump: Path) -> dict[str, tuple[str, int]]:
    """Return the most common spelling and the songs of each name key of the dump.

    Only a key with `MIN_DUMP_SONGS` or more songs is in the result. Only the credited
    names and the song ids are read.
    """
    with duckdb.connect() as connection:
        connection.create_function(
            "name_key", dump_match.name_key, ["VARCHAR"], "VARCHAR", null_handling="special"
        )
        connection.execute(
            "CREATE TEMP TABLE credits AS SELECT DISTINCT source_song_id, artist_name "
            f"FROM {dump_match._quoted(dump / 'songs.parquet')}"
        )
        connection.execute(
            "CREATE TEMP TABLE keyed AS SELECT artist_name, name_key(artist_name) AS key "
            "FROM (SELECT DISTINCT artist_name FROM credits)"
        )
        rows = connection.sql(
            f"""
            SELECT key, mode(artist_name), count(DISTINCT source_song_id)
            FROM credits JOIN keyed USING (artist_name)
            WHERE key <> '' GROUP BY key
            HAVING count(DISTINCT source_song_id) >= {int(MIN_DUMP_SONGS)}
            """
        ).fetchall()
    return {key: (name, songs) for key, name, songs in rows}


def _country_of(
    profile: str | None, bare: str, by_country: dict[str, int], alone: dict[str, frozenset[str]]
) -> tuple[str, int]:
    """Return the country of a candidate (T1 or T2) and its home releases there, or ("", 0).

    `alone` gives, for each country, the release countries that are a home of it only.
    """
    stated, _ = artist_country.profile_evidence(profile, frozenset(), (bare,))
    if stated:
        return stated, sum(n for name, n in by_country.items() if name in alone.get(stated, ()))
    top = artist_country.top_country({k: v for k, v in by_country.items() if k}, frozenset())
    code = next((code for code, names in alone.items() if top in names), "")
    home = sum(n for name, n in by_country.items() if name in alone.get(code, ()))
    return (code, home) if code and home >= MIN_EVIDENCE_RELEASES else ("", 0)


def dump_artists(
    discogs: Path, iso3: str, dump: Path, rosters: dict[str, list[tuple[str, str | None]]]
) -> dict[str, tuple[str, str]]:
    """Return the artists of the dump rule for `iso3`: artist id -> (credited name, Discogs id).

    `rosters` is the name and the Discogs id of each roster artist, for each country
    (`_rosters`). A dump name finds a Discogs artist by its name key, its loose key, or
    its `dump_match.spelling_key` when no other free dump name has that spelling key.
    The order is by Discogs id.
    """
    held, taken_ids, keys_with_id = set(), set(), set()
    no_id: dict[str, set[str]] = defaultdict(set)
    for code, roster in rosters.items():
        for name, number in roster:
            if code == iso3 or number:
                held |= {dump_match.name_key(name), loose_key(name)}
            else:
                no_id[dump_match.name_key(name)].add(code)
                no_id[loose_key(name)].add(code)
            if number:
                taken_ids.add(str(number))
                keys_with_id.add(dump_match.name_key(name))
    free = {
        key: (name, songs, loose_key(name))
        for key, (name, songs) in _dump_names(dump).items()
        if key not in held and loose_key(name) not in held
    }
    if not free or not (discogs / "artists.parquet").is_file():
        return {}
    by_loose, by_spelling = defaultdict(set), defaultdict(set)
    for key, (name, _, loose) in free.items():
        if loose:
            by_loose[loose].add(key)
        by_spelling[dump_match.spelling_key(name)].add(key)
    by_spelling = {key: keys for key, keys in by_spelling.items() if key and len(keys) == 1}
    table = {
        name: dump_match._quoted(discogs / f"{name}.parquet")
        for name in ("artists", "release_artists", "releases", "release_genres")
    }
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        dump_match._table(connection, "free_keys", "str", sorted(free))
        dump_match._table(connection, "free_loose", "str", sorted(by_loose))
        candidates = connection.sql(
            f"""
            SELECT artist_id, name, key, {_LOOSE_SQL} AS loose
            FROM {dump_match._discogs_keys(connection, discogs)}
            WHERE key IN (SELECT value FROM free_keys)
                OR {_LOOSE_SQL} IN (SELECT value FROM free_loose)
            """
        ).fetchall()
        dump_match._table(connection, "free_spelling", "str", sorted(by_spelling))
        for number, name in connection.sql(
            f"SELECT artist_id, name FROM {dump_match._discogs_spellings(connection, discogs)} "
            "WHERE spelling IN (SELECT value FROM free_spelling)"
        ).fetchall():
            bare = re.sub(dump_match._HOMONYM, "", name or "")
            candidates.append((number, name, dump_match.name_key(bare), loose_key(bare)))
        wanted = sorted(
            {number for number, *_ in candidates}
            - set(NOT_ARTISTS)
            - {int(number) for number in taken_ids if number.isdigit()}
        )
        dump_match._table(connection, "wanted", "int64", wanted)
        connection.execute(
            f"""
            CREATE TEMP TABLE main AS
            SELECT DISTINCT a.artist_id, a.release_id, coalesce(r.country, '') AS country
            FROM {table["release_artists"]} AS a JOIN {table["releases"]} AS r USING (release_id)
            WHERE a.artist_id IN (SELECT value FROM wanted)
            """
        )
        by_country: dict[int, dict[str, int]] = defaultdict(dict)
        for number, country, count in connection.sql(
            "SELECT artist_id, country, count(*) FROM main GROUP BY ALL"
        ).fetchall():
            by_country[number][country] = count
        not_song = dict(
            connection.sql(
                f"""
                SELECT artist_id, count(DISTINCT release_id) FROM main WHERE release_id IN (
                    SELECT release_id FROM {table["release_genres"]}
                    WHERE genre IN {NOT_SONG_GENRES}
                ) GROUP BY artist_id
                """
            ).fetchall()
        )
        profiles = dict(
            connection.sql(
                f"SELECT artist_id, profile FROM {table['artists']} "
                "WHERE artist_id IN (SELECT value FROM wanted)"
            ).fetchall()
        )
    homes = dump_match.load_home_countries()
    shared = Counter(name for names in homes.values() for name in names)
    alone = {code: frozenset(n for n in names if shared[n] == 1) for code, names in homes.items()}
    scored: dict[str, set[tuple[int, str, int]]] = defaultdict(set)
    allowed = set(wanted)
    for number, name, key, loose in candidates:
        releases = sum(by_country[number].values())
        if (
            number not in allowed
            or key in keys_with_id
            or releases
            and not_song.get(number, 0) >= MAX_NOT_SONG_SHARE * releases
        ):
            continue
        bare = re.sub(dump_match._HOMONYM, "", name or "")
        code, home = _country_of(profiles.get(number), bare, by_country[number], alone)
        if code:
            spelled = by_spelling.get(dump_match.spelling_key(bare), set())
            for free_key in ({key} & free.keys()) | by_loose.get(loose, set()) | spelled:
                scored[free_key].add((home, code, number))
    chosen: dict[int, tuple[str, int]] = {}
    for free_key, found in scored.items():
        ranked = sorted(found, reverse=True)
        home, code, number = ranked[0]
        if len(ranked) > 1 and (home < MIN_EVIDENCE_RELEASES or home < DOMINANCE * ranked[1][0]):
            continue
        name, songs, loose = free[free_key]
        others = no_id.get(free_key, set()) | no_id.get(loose, set())
        if any(set(by_country[number]) & homes.get(other, set()) for other in others):
            continue
        if code == iso3 and songs > chosen.get(number, ("", 0))[1]:
            chosen[number] = (name, songs)
    return {
        review_workbooks.artist_id(iso3, name, str(number)): (name, str(number))
        for number, (name, _) in sorted(chosen.items())
    }


def new_artists(
    data: Path,
    discogs: Path,
    iso3: str,
    min_releases: int = MIN_HOME_RELEASES,
    min_share: float = MIN_HOME_SHARE,
    dump: Path | None = None,
) -> dict[str, tuple[str, str]]:
    """Return the artists of the rules for `iso3`: artist id -> (artist name, Discogs id).

    The artists of the home rule come first, by Discogs id. With the folder of a `dump`,
    the artists of the dump rule follow, by Discogs id, unless the home rule has the
    same Discogs artist.
    """
    iso3 = paths.check_iso3(iso3)
    found = home_artists(discogs.resolve(), iso3, min_releases, min_share)
    rosters = _rosters(data) if found or dump is not None else {}
    taken_ids, taken_keys = set(), set()
    for code, roster in rosters.items():
        keyed = [(dump_match.name_key(name), number) for name, number in roster]
        taken_ids |= {str(number) for _, number in keyed if number}
        taken_keys |= {key for key, number in keyed if code == iso3 or not number}
    counts = Counter(row[1] for row in found.values())
    taken_keys |= {key for key, count in counts.items() if count > 1}
    result = {
        review_workbooks.artist_id(iso3, name, str(number)): (name, str(number))
        for number, (name, key, _, _) in sorted(found.items())
        if key and str(number) not in taken_ids and key not in taken_keys
    }
    if dump is not None:
        result |= {
            artist: pair
            for artist, pair in dump_artists(discogs.resolve(), iso3, dump, rosters).items()
            if artist not in result
        }
    return result
