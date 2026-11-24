"""The import of topic scores from the old layout, on small invented files."""

import hashlib
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_30_topics import old_scores as scores
from songs.stage_30_topics.scoring_prompt import PROMPT_SHA256
from songs.stage_30_topics.topic_ids import TOPIC_IDS

LYRIC = "invented line scored-once"
SECRET_URL = "https://scores.example/secret-url"
SONGS_RUN = "20260101T000000Z"
LATEST_RUN = "20260102T000000Z"
SCORE_RUN = "20260103T000000Z"


def digest(number: int) -> str:
    return f"{number:064x}"


def snapshot(folder: Path) -> dict[str, str]:
    """Return the SHA-256 of every file under a folder."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def write_frame(path: Path, rows: list[dict], types: dict[str, str]) -> None:
    """Write one Parquet file with the given column types. Cells may be null."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(types)
    with duckdb.connect() as connection:
        definition = ", ".join(f'"{name}" {types[name]}' for name in names)
        connection.execute(f"CREATE TABLE frame ({definition})")
        marks = ", ".join("?" for _ in names)
        connection.executemany(
            f"INSERT INTO frame VALUES ({marks})",
            [tuple(row.get(name) for name in names) for row in rows],
        )
        target = path.resolve().as_posix().replace("'", "''")
        connection.execute(f"COPY frame TO '{target}' (FORMAT PARQUET)")


def topic_types(**extra: str) -> dict[str, str]:
    types = {"song_id": "VARCHAR", "url": "VARCHAR"}
    types.update({name: "SMALLINT" for name in scores.OLD_TOPIC_COLUMNS})
    types.update(extra)
    return types


def topic_row(song_id: str, first: int | None, **over) -> dict:
    """One old topic row. `first` is column t1. The other topic cells are 0, or empty."""
    row = {"song_id": song_id, "url": SECRET_URL}
    for name in scores.OLD_TOPIC_COLUMNS:
        row[name] = None if first is None else 0
    row["t1"] = first
    return row | over


def provenance_types(**extra: str) -> dict[str, str]:
    types = {
        "song_id": "VARCHAR",
        "lyrics_sha256": "VARCHAR",
        "prompt_sha256": "VARCHAR",
        "instrument_sha256": "VARCHAR",
        "model": "VARCHAR",
        "text_kind": "VARCHAR",
        "measurement_status": "VARCHAR",
        "country": "VARCHAR",
        "url": "VARCHAR",
        "response_ids": "VARCHAR",
    }
    types.update(extra)
    return types


def provenance_row(song_id: str, lyrics_hash: str, **over) -> dict:
    return {
        "song_id": song_id,
        "lyrics_sha256": lyrics_hash,
        "prompt_sha256": digest(100 + int(lyrics_hash[-2:], 16)),
        "instrument_sha256": PROMPT_SHA256,
        "model": "invented-model",
        "text_kind": "song_lyrics",
        "measurement_status": "complete",
        "country": "TGO",
        "url": SECRET_URL,
        "response_ids": "drop-this-column",
    } | over


def song_frame(iso3: str, song_id: str, lyric: str, lyrics_hash: str, run_id: str) -> pd.DataFrame:
    """One invented songs.parquet row. The lyric text is the caller's invented line."""
    values = {
        "string": "invented",
        "boolean": True,
        "int16": 1,
        "int32": 1990,
        "int64": 2**40,
        "float64": 0.5,
    }
    frame = pd.DataFrame(
        {column.name: [values[column.type]] for column in schemas.COUNTRY_SONGS.columns}
    )
    frame["country_iso3"] = iso3
    frame["song_id"] = song_id
    frame["lyrics"] = lyric
    frame["lyrics_sha256"] = lyrics_hash
    frame["route"] = "old_layout"
    frame["run_id"] = run_id
    return frame


def write_songs(data: Path, run_id: str, rows: list[tuple[str, str, str]]) -> None:
    """Write a complete songs folder. Each row is song id, lyric text and lyric hash."""
    folder = paths.country_songs_dir(data, "TGO", run_id)
    folder.mkdir(parents=True)
    frames = [
        song_frame("TGO", song_id, lyric, lyrics_hash, run_id)
        for song_id, lyric, lyrics_hash in rows
    ]
    table = pd.concat(frames, ignore_index=True)
    schemas.write_table(
        schemas.COUNTRY_SONGS, schemas.cast_to_schema(schemas.COUNTRY_SONGS, table), folder
    )
    schemas.write_table(
        schemas.COUNTRY_ARTISTS, schemas.empty_table(schemas.COUNTRY_ARTISTS), folder
    )
    schemas.write_table(schemas.COUNTRY_LINKS, schemas.empty_table(schemas.COUNTRY_LINKS), folder)
    manifests.write_manifest(
        data,
        folder,
        "country_songs",
        country_iso3="TGO",
        run_id=run_id,
        inputs=["lyrics/tgo/"],
    )


def cells(table: schemas.Table, folder: Path) -> list[dict]:
    relation = schemas.read_table(table, folder).order("song_id")
    return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def test_the_command_keeps_the_stored_hash_and_writes_a_manifest(tmp_path, monkeypatch):
    old, data = tmp_path / "old", tmp_path / "data"
    data.mkdir()
    folder = old / "lyrics" / "tgo" / "scores"
    write_frame(
        folder / "topics.parquet",
        [
            topic_row("s1", 10),
            topic_row("s2", 20),
            topic_row("s3", 30),
            topic_row("s4", None, t1=None),
        ],
        topic_types(),
    )
    write_frame(
        folder / "topic_provenance.parquet",
        [
            provenance_row("s1", digest(1)),
            provenance_row("s2", digest(2)),
            provenance_row("s3", digest(3), country="XXX"),
            provenance_row("s4", digest(4), instrument_sha256=digest(14), text_kind="non_song"),
        ],
        provenance_types(),
    )
    # An older provenance and the value files must not be read.
    write_frame(
        folder / "provenance.parquet",
        [provenance_row("s1", digest(1), model="old-model", instrument_sha256=digest(99))],
        provenance_types(),
    )
    (folder / "values.parquet").write_bytes(b"not a parquet file\n")
    (folder / "value_flags.parquet").write_bytes(b"not a parquet file\n")
    (folder / "topic_contract.json").write_text('{"model": "other-model"}\n', encoding="utf-8")
    # The older songs folder agrees with s2. The newest folder does not.
    write_songs(
        data,
        SONGS_RUN,
        [("s1", LYRIC, digest(1)), ("s2", LYRIC, digest(2)), ("s4", LYRIC, digest(4))],
    )
    write_songs(
        data,
        LATEST_RUN,
        [("s1", LYRIC, digest(1)), ("s2", LYRIC, digest(9)), ("s4", LYRIC, digest(4))],
    )
    before = snapshot(folder)
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    monkeypatch.setenv(scores.OLD_DATA_ENV, str(old))
    result = CliRunner().invoke(app, ["lyrics", "import-scores", "tgo"])
    assert result.exit_code == 0, result.output
    assert "4 scores, 1 with no song, 1 with changed text" in result.output
    assert LYRIC not in result.output and SECRET_URL not in result.output
    assert snapshot(folder) == before

    out = paths.latest_country_scores_dir(data, "TGO")
    manifest = manifests.read_manifest(out)
    assert manifest.kind == "country_scores"
    assert manifest.inputs == ["lyrics/tgo/scores/", f"lyrics/TGO/songs/{LATEST_RUN}/"]
    assert manifest.counts == {
        "scores": 4,
        "scores_no_song": 1,
        "scores_text_changed": 1,
        "scores_null_topics": 1,
        "scores_country_differs": 1,
        "scores_other_prompt": 1,
        "scores_song_lyrics": 3,
        "scores_non_song": 1,
        "scores_uncertain": 0,
        "scores_other_text_kind": 0,
    }
    assert "topic_provenance.parquet" in manifest.notes
    assert LYRIC not in manifest.notes and SECRET_URL not in manifest.notes
    assert ":\\" not in manifest.notes and "://" not in manifest.notes

    topics = cells(schemas.SCORE_TOPICS, out)
    provenance = cells(schemas.SCORE_PROVENANCE, out)
    assert [row["song_id"] for row in topics] == ["s1", "s2", "s3", "s4"]
    assert topics[0][TOPIC_IDS[0]] == 10
    assert topics[0][TOPIC_IDS[1]] == 0
    assert all(topics[3][topic_id] is None for topic_id in TOPIC_IDS)
    assert [row["lyrics_sha256"] for row in provenance] == [
        digest(1),
        digest(2),
        digest(3),
        digest(4),
    ]
    assert provenance[1]["lyrics_sha256"] != digest(9)
    assert {row["model"] for row in provenance} == {"invented-model"}
    # The old per-song prompt hash is not kept; the prompt identity is.
    assert [row["prompt_sha256"] for row in provenance] == [PROMPT_SHA256] * 3 + [digest(14)]
    assert [row["status"] for row in provenance] == ["complete"] * 4
    assert [row["scored_utc"] for row in provenance] == [None] * 4
    assert provenance[3]["text_kind"] == "non_song"
    assert [column.name for column in schemas.SCORE_TOPICS.all_columns] == list(topics[0])


def test_topic_provenance_wins_and_the_older_file_is_the_fallback(tmp_path):
    old, data = tmp_path / "old", tmp_path / "data"
    both = old / "lyrics" / "tgo" / "scores"
    write_frame(both / "topics.parquet", [topic_row("s1", 1)], topic_types())
    write_frame(
        both / "topic_provenance.parquet",
        [provenance_row("s1", digest(1), model="topic-model")],
        provenance_types(),
    )
    write_frame(
        both / "provenance.parquet",
        [provenance_row("s1", digest(1), model="old-model")],
        provenance_types(),
    )
    only = old / "lyrics" / "ben" / "scores"
    write_frame(only / "topics.parquet", [topic_row("s1", 7)], topic_types())
    kept = provenance_types()
    del kept["country"]
    write_frame(
        only / "provenance.parquet",
        [provenance_row("s1", digest(7), model="fallback-model")],
        kept,
    )
    for iso3, run_id in (("TGO", SONGS_RUN), ("BEN", SONGS_RUN)):
        folder = paths.country_songs_dir(data, iso3, run_id)
        folder.mkdir(parents=True)
        frame = song_frame(iso3, "s1", LYRIC, digest(1 if iso3 == "TGO" else 7), run_id)
        schemas.write_table(
            schemas.COUNTRY_SONGS, schemas.cast_to_schema(schemas.COUNTRY_SONGS, frame), folder
        )
        schemas.write_table(
            schemas.COUNTRY_ARTISTS, schemas.empty_table(schemas.COUNTRY_ARTISTS), folder
        )
        schemas.write_table(
            schemas.COUNTRY_LINKS, schemas.empty_table(schemas.COUNTRY_LINKS), folder
        )
        manifests.write_manifest(
            data,
            folder,
            "country_songs",
            country_iso3=iso3,
            run_id=run_id,
            inputs=[f"lyrics/{iso3.lower()}/"],
        )

    first = scores.import_scores(old, data, "TGO", run_id=SCORE_RUN)
    second = scores.import_scores(old, data, "BEN", run_id=SCORE_RUN)
    assert cells(schemas.SCORE_PROVENANCE, first["path"])[0]["model"] == "topic-model"
    assert cells(schemas.SCORE_TOPICS, first["path"])[0][TOPIC_IDS[0]] == 1
    assert cells(schemas.SCORE_PROVENANCE, second["path"])[0]["model"] == "fallback-model"
    assert cells(schemas.SCORE_TOPICS, second["path"])[0][TOPIC_IDS[0]] == 7
    assert second["scores_country_differs"] == 0
    assert manifests.read_manifest(second["path"]).notes.count("provenance.parquet") == 1


def test_the_import_stops_when_the_old_files_cannot_prove_a_row(tmp_path, monkeypatch):
    old, data = tmp_path / "old", tmp_path / "data"
    data.mkdir()
    folder = old / "lyrics" / "tgo" / "scores"
    write_frame(folder / "topics.parquet", [topic_row("s1", 1)], topic_types())
    write_frame(
        folder / "topic_provenance.parquet",
        [provenance_row("s1", digest(1), instrument_sha256=None)],
        provenance_types(),
    )
    write_songs(data, SONGS_RUN, [("s1", LYRIC, digest(1))])
    with pytest.raises(ValueError, match="no instrument_sha256: 1 rows"):
        scores.import_scores(old, data, "TGO", run_id=SCORE_RUN)
    assert not (data / "lyrics" / "TGO" / "scores").exists()

    types = provenance_types()
    del types["model"]
    write_frame(folder / "topic_provenance.parquet", [provenance_row("s1", digest(1))], types)
    with pytest.raises(ValueError, match="no column model"):
        scores.import_scores(old, data, "TGO", run_id=SCORE_RUN)

    write_frame(
        folder / "topics.parquet",
        [topic_row("s1", 1), topic_row("s1", 2)],
        topic_types(),
    )
    write_frame(
        folder / "topic_provenance.parquet",
        [provenance_row("s1", digest(1)), provenance_row("s1", digest(1))],
        provenance_types(),
    )
    with pytest.raises(ValueError, match="duplicate song_id"):
        scores.import_scores(old, data, "TGO", run_id=SCORE_RUN)

    write_frame(folder / "topics.parquet", [topic_row("s1", 1)], topic_types())
    write_frame(
        folder / "topic_provenance.parquet",
        [provenance_row("s9", digest(9))],
        provenance_types(),
    )
    with pytest.raises(ValueError, match="no provenance"):
        scores.import_scores(old, data, "TGO", run_id=SCORE_RUN)
    assert paths.latest_country_scores_dir(data, "TGO") is None

    seen = {"n": 0}
    real = scores._stamp

    def changed(path: Path):
        seen["n"] += 1
        size, mtime = real(path)
        if seen["n"] == 3:
            return (size + 1, mtime)
        return (size, mtime)

    write_frame(folder / "topics.parquet", [topic_row("s1", 1)], topic_types())
    write_frame(
        folder / "topic_provenance.parquet",
        [provenance_row("s1", digest(1))],
        provenance_types(),
    )
    monkeypatch.setattr(scores, "_stamp", changed)
    with pytest.raises(ValueError, match="changed while it was read"):
        scores.import_scores(old, data, "TGO", run_id=SCORE_RUN)
    assert not (data / "lyrics" / "TGO" / "scores").exists()


def test_the_import_stops_before_it_writes(tmp_path):
    old, data = tmp_path / "old", tmp_path / "data"
    data.mkdir()
    with pytest.raises(FileNotFoundError, match="topics.parquet"):
        scores.import_scores(old, data, "TGO")
    place = tmp_path / "place"
    place.mkdir()
    with pytest.raises(ValueError, match="read only"):
        scores.import_scores(place, place, "TGO")
    with pytest.raises(ValueError, match="three capital letters"):
        scores.import_scores(old, data, "tgo")
    folder = old / "lyrics" / "tgo" / "scores"
    write_frame(folder / "topics.parquet", [topic_row("s1", 1)], topic_types())
    write_frame(
        folder / "topic_provenance.parquet",
        [provenance_row("s1", digest(1))],
        provenance_types(),
    )
    with pytest.raises(FileNotFoundError, match="no songs folder"):
        scores.import_scores(old, data, "TGO")
    assert not data.joinpath("lyrics", "TGO", "scores").exists()


def test_a_second_import_writes_a_new_folder(tmp_path):
    old, data = tmp_path / "old", tmp_path / "data"
    folder = old / "lyrics" / "tgo" / "scores"
    write_frame(folder / "topics.parquet", [topic_row("s1", 4)], topic_types())
    write_frame(
        folder / "provenance.parquet",
        [provenance_row("s1", digest(4))],
        provenance_types(),
    )
    write_songs(data, SONGS_RUN, [("s1", LYRIC, digest(4))])
    first = scores.import_scores(old, data, "TGO", run_id="20260103T000000Z")
    second = scores.import_scores(old, data, "TGO", run_id="20260104T000000Z")
    assert first["path"] != second["path"]
    assert paths.latest_country_scores_dir(data, "TGO") == second["path"]
    assert manifests.read_manifest(first["path"]).counts["scores"] == 1
    assert manifests.read_manifest(second["path"]).inputs[1] == f"lyrics/TGO/songs/{SONGS_RUN}/"
