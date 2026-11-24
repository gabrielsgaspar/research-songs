"""Mark the roster artists that belong to another country, from Discogs evidence.

    in   clean/catalog/discogs/<YYYYMMDD>/   artists, release_artists, release_track_artists,
                                             releases (Parquet, the newest complete folder)
    in   lyrics/<ISO3>/songs/<run id>/       artists.parquet, songs.parquet of the newest
                                             complete folder of each country
    out  clean/quality/artist_country/<YYYYMMDD>/   artist_country.parquet, _MANIFEST.json

Some rosters hold artists of other countries. The table has one row for each roster
artist with a Discogs id (`dump_match.discogs_ids`: the id of the roster, or the id
found by name). The decision is `other_country` only when all three hold, and `keep`
for every other artist:

1. The start of the Discogs profile states another country. The start is the first
   `PROFILE_CHARS` characters, with runs of spaces made one. A statement is a country
   word that describes a role noun within a few words ("Syrian traditional singer"),
   or a country word that follows "from" within 40 characters with no sentence break
   ("from Dublin, Ireland"). A word followed by "-born" or " born" is no statement.
2. No word of a home country is anywhere in that text. A home country is the country
   itself, each country whose Discogs release names are all release names of this
   country in `resources/lyrics/discogs_countries.csv` (the USSR is a home of
   Ukraine), and the countries of `ALSO_HOME`.
3. The artist has a release with a country, fewer than `MAX_HOME_SHARE` of those
   releases are in a home release country (`dump_match.load_home_countries`), and
   the release country with the most releases is not a home release country. When
   two countries have the most releases and one is a home, the home counts.

The country words are in `resources/lyrics/country_words.csv`. A word in capitals or
of three letters or fewer (`UK`, `US`) is matched with its case, and every other word
without case. A longer word wins over a shorter one. The phrases of `IGNORED_PHRASES`
hold a country word and name no country of an artist, so they are made blank first.

The rule reads no lyric text. No person checks a row: the rule is strict so that a
wrong `other_country` is rare, and it misses artists with a short or empty profile.
"""

import csv
import functools
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, schemas
from songs.common.schemas import KEEP, OTHER_COUNTRY
from songs.stage_00_ingest import dump_match

WORDS_FILE = Path("resources") / "lyrics" / "country_words.csv"
WORD_COLUMNS = ("country_iso3", "word")
PROFILE_CHARS = 160
MAX_HOME_SHARE = 0.2
# Country -> more countries that count as its home in the profile text.
ALSO_HOME = {"DDR": ("DEU",)}
# Phrases with a country word that say nothing about the country of an artist.
IGNORED_PHRASES = (
    "New Jersey",
    "British Columbia",
    "Belgian Congo",
    "New Mexico",
    "New England",
    "Indian Ocean",
    "West Indies",
    "West Indian",
    "Latin American",
    "South American",
    "North American",
    "Central American",
)
ROLES = (
    "singer|songwriter|singer-songwriter|vocalist|band|group|duo|trio|quartet|quintet|rapper|MC|"
    "emcee|musician|composer|producer|DJ|artist|pianist|guitarist|drummer|bassist|violinist|"
    "saxophonist|trumpeter|keyboardist|conductor|orchestra|ensemble|choir|project|collective|act|"
    "outfit|actress|actor|performer|lyricist|tenor|soprano|baritone|crooner|instrumentalist|"
    "multi-instrumentalist"
)
_IGNORED = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(phrase) for phrase in IGNORED_PHRASES) + r")(?!\w)",
    re.IGNORECASE,
)


@functools.cache
def load_country_words(root: Path | None = None) -> dict[str, str]:
    """Return the country code of each country word of `WORDS_FILE`.

    Raise ValueError on a bad row, and on a word that comes twice when case is ignored.
    """
    path = (root or paths.resolve_project_root()) / WORDS_FILE
    words: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != WORD_COLUMNS:
            raise ValueError(f"{path.name} must have the columns {', '.join(WORD_COLUMNS)}")
        seen = set()
        for line in reader:
            word = line["word"]
            paths.check_iso3(line["country_iso3"])
            if not word or word != word.strip() or word.casefold() in seen:
                raise ValueError(f"{path.name}: the word {word!r} is empty, padded or listed twice")
            seen.add(word.casefold())
            words[word] = line["country_iso3"]
    return words


@functools.cache
def _patterns(root: Path | None = None) -> tuple[re.Pattern[str], re.Pattern[str], dict[str, str]]:
    """Return the pattern of a country word, the pattern of a statement, and word -> code."""
    words = load_country_words(root)
    word = "|".join(
        re.escape(text) if text.isupper() or len(text) <= 3 else f"(?i:{re.escape(text)})"
        for text in sorted(words, key=lambda text: (-len(text), text))
    )
    stated = (
        rf"(?<!\w)({word})(?![- ]born)(?:[ /,&-]+[\w'’]+){{0,4}}?[ /-]+(?i:{ROLES})(?!\w)"
        rf"|(?i:\bfrom)\s+[^.;()\[\]]{{0,40}}?(?<!\w)({word})(?!\w)"
    )
    codes = {text.casefold(): code for text, code in words.items()}
    return re.compile(rf"(?<!\w)({word})(?!\w)"), re.compile(stated), codes


def home_codes(iso3: str) -> frozenset[str]:
    """Return the countries whose words in a profile say that the artist is at home in `iso3`."""
    home = dump_match.load_home_countries()
    names = home.get(iso3, frozenset())
    inside = {code for code, own in home.items() if own <= names}
    return frozenset({iso3, *inside, *ALSO_HOME.get(iso3, ())})


def profile_evidence(profile: str | None, home: frozenset[str]) -> tuple[str, bool]:
    """Return what the start of a Discogs profile says about the country of the artist.

    The first value is the country that the first statement names, or "" for no
    statement. The second is true when a word of a country in `home` is in the text.
    """
    text = _IGNORED.sub(" ", " ".join((profile or "").split())[:PROFILE_CHARS])
    any_word, statement, codes = _patterns()
    home_word = any(codes[found.group(1).casefold()] in home for found in any_word.finditer(text))
    found = statement.search(text)
    stated = codes[(found.group(1) or found.group(2)).casefold()] if found else ""
    return stated, home_word


def top_country(by_country: dict[str, int], home_names: frozenset[str]) -> str:
    """Return the release country with the most releases, or "" for no release.

    Of two countries with the same number, a home release country wins, then the name.
    """
    if not by_country:
        return ""
    return min(by_country, key=lambda name: (-by_country[name], name not in home_names, name))


def decide(
    stated: str, home_word: bool, releases: int, releases_home: int, top_is_home: bool
) -> str:
    """Return `OTHER_COUNTRY` when the three conditions of the rule hold, or `KEEP`."""
    abroad = releases > 0 and releases_home / releases < MAX_HOME_SHARE and not top_is_home
    return OTHER_COUNTRY if stated and not home_word and abroad else KEEP


def _release_countries(discogs: Path, numbers: list[int]) -> tuple[dict, dict]:
    """Return, for each Discogs artist id, its releases by release country, and its profile."""
    table = {
        name: dump_match._quoted(discogs / f"{name}.parquet")
        for name in ("artists", "release_artists", "release_track_artists", "releases")
    }
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        dump_match._table(connection, "ids", "int64", numbers)
        connection.execute(
            f"""
            CREATE TEMP TABLE credited AS
            SELECT artist_id, release_id FROM {table["release_artists"]}
            WHERE artist_id IN (SELECT value FROM ids)
            UNION
            SELECT artist_id, release_id FROM {table["release_track_artists"]}
            WHERE artist_id IN (SELECT value FROM ids)
            """
        )
        counted = connection.sql(
            f"""
            SELECT c.artist_id, r.country, count(*) FROM credited AS c JOIN (
                SELECT release_id, country FROM {table["releases"]}
                WHERE release_id IN (SELECT release_id FROM credited) AND country IS NOT NULL
            ) AS r USING (release_id) GROUP BY ALL
            """
        ).fetchall()
        profiles = dict(
            connection.sql(
                f"SELECT artist_id, profile FROM {table['artists']} "
                "WHERE artist_id IN (SELECT value FROM ids)"
            ).fetchall()
        )
    by_country: dict[int, dict[str, int]] = {}
    for number, country, releases in counted:
        by_country.setdefault(number, {})[country] = releases
    return by_country, profiles


def country_rows(folder: Path, discogs: Path, iso3: str) -> tuple[list[dict], dict[str, int], int]:
    """Return the rows of the table for one country folder.

    The second value is the songs of the folder by `artist_id`, and the third is the
    number of its roster artists.
    """
    ids = dump_match.discogs_ids(folder.resolve(), discogs.resolve(), iso3)["ids"]
    with duckdb.connect() as connection:
        songs = dict(
            connection.read_parquet(str(folder / schemas.COUNTRY_SONGS.file))
            .aggregate("artist_id, count(*)", "artist_id")
            .fetchall()
        )
        artists = len(connection.read_parquet(str(folder / schemas.COUNTRY_ARTISTS.file)))
    by_country, profiles = _release_countries(discogs, sorted({int(n) for n in ids.values()}))
    home_names = dump_match.load_home_countries().get(iso3, frozenset())
    home = home_codes(iso3)
    rows = []
    for artist_id, number in sorted(ids.items()):
        releases = by_country.get(int(number), {})
        total = sum(releases.values())
        at_home = sum(count for name, count in releases.items() if name in home_names)
        top = top_country(releases, home_names)
        stated, home_word = profile_evidence(profiles.get(int(number)), home)
        rows.append(
            {
                "country_iso3": iso3,
                "artist_id": artist_id,
                "discogs_artist_id": str(number),
                "stated_country": stated,
                "home_word": home_word,
                "releases": total,
                "releases_home": at_home,
                "top_release_country": top,
                "decision": decide(stated, home_word, total, at_home, top in home_names),
            }
        )
    return rows, songs, artists


def check_rosters(data: Path, *, write: bool = False, today: date | None = None) -> dict:
    """Apply the rule to the newest songs folder of every country. Return the counts.

    The function reads the newest complete Discogs catalog folder, one country at a
    time. With `write`, it writes the folder of the day with the table and its
    manifest, and returns it as `folder`. Raise FileNotFoundError when the data folder
    has no Discogs catalog folder, and FileExistsError when the folder of the day exists.

    `counts` holds the rows in (`artists_in`), the rows out (`artists_with_discogs_id`),
    the rows left out (`left_out_no_discogs_id`), the artists with `other_country`,
    those of them that have a song, the songs of all the countries (`songs_in`) and
    the songs of the artists with `other_country`. `by_country` gives, for each
    country with such a song, those songs and all its songs.
    """
    discogs = paths.latest_clean_catalog_dir(data, "discogs")
    if discogs is None:
        raise FileNotFoundError("no complete clean/catalog/discogs/<YYYYMMDD>/ in the data folder")
    out = paths.clean_artist_country_dir(data, today or date.today())
    if write and out.exists():
        raise FileExistsError(f"{out} exists; a version folder is never written over")
    counts = dict.fromkeys(
        (
            "countries",
            "artists_in",
            "artists_with_discogs_id",
            "left_out_no_discogs_id",
            "other_country_artists",
            "other_country_artists_with_songs",
            "songs_in",
            "other_country_songs",
        ),
        0,
    )
    rows, inputs, by_country = [], [paths.data_relative(data, discogs)], {}
    for parent in sorted((data / "lyrics").glob("*")):
        folder = (
            paths.latest_country_songs_dir(data, parent.name)
            if paths.ISO3.fullmatch(parent.name)
            else None
        )
        if folder is None:
            continue
        found, songs, artists = country_rows(folder, discogs, parent.name)
        other = [row["artist_id"] for row in found if row["decision"] == OTHER_COUNTRY]
        other_songs = sum(songs.get(artist_id, 0) for artist_id in other)
        counts["countries"] += 1
        counts["artists_in"] += artists
        counts["artists_with_discogs_id"] += len(found)
        counts["left_out_no_discogs_id"] += artists - len(found)
        counts["other_country_artists"] += len(other)
        counts["other_country_artists_with_songs"] += sum(a in songs for a in other)
        counts["songs_in"] += sum(songs.values())
        counts["other_country_songs"] += other_songs
        if other_songs:
            by_country[parent.name] = (other_songs, sum(songs.values()))
        rows += found
        inputs.append(paths.data_relative(data, folder))
    result = {"counts": counts, "by_country": by_country, "folder": None}
    if write:
        names = [column.name for column in schemas.ARTIST_COUNTRY.columns]
        out.mkdir(parents=True)
        with duckdb.connect() as connection:
            frame = pd.DataFrame(rows, columns=names)
            schemas.write_table(
                schemas.ARTIST_COUNTRY,
                schemas.cast_to_schema(schemas.ARTIST_COUNTRY, frame, connection),
                out,
            )
        manifests.write_manifest(
            data,
            out,
            "clean_artist_country",
            inputs=inputs,
            counts=counts,
            notes=f"The rule of songs.stage_10_clean.artist_country, with the words of "
            f"{WORDS_FILE.as_posix()} and the home countries of "
            f"{dump_match.HOME_FILE.as_posix()}.",
        )
        result["folder"] = out
    return result
