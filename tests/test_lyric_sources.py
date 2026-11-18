"""The lyric source registry, on invented entries, and its hold on run records."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import lyric_sources as s
from songs.common import run_records
from songs.common.run_records import RunRecord

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = """
[[language]]
code = "pt"
name = "Portuguese"
countries = ["BRA", "PRT"]
"""
SOURCES = """
[[source]]
id = "world_site"
name = "World Site"
kind = "live_site"
scope = "global"
url = "https://world.example"
stored_path = ""
routes = ["live"]
access = "allowed"
request_delay_seconds = 1.5
checked = true

[[source]]
id = "lusophone_dump"
name = "Lusophone Dump"
kind = "bulk_dump"
scope = "languages"
languages = ["pt"]
url = ""
stored_path = "raw/lusophone_dump/20260101/"
routes = ["dump_name"]
access = "not_applicable"
checked = false

[[source]]
id = "kenya_archive"
name = "Kenya Archive"
kind = "site_archive"
scope = "countries"
countries = ["KEN"]
url = "https://kenya.example"
stored_path = ""
routes = ["archive"]
access = "blocked"
checked = true
notes = "A | in a note"
"""


def make_root(tmp_path, sources=SOURCES, languages=LANGUAGES):
    (tmp_path / "resources").mkdir()
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / s.SOURCES_FILE).write_text(sources, encoding="utf-8")
    (tmp_path / s.LANGUAGES_FILE).write_text(languages, encoding="utf-8")
    return tmp_path


def record(source, **changes):
    values = {
        "iso3": "BRA",
        "run_id": "20260131T120000Z",
        "route": "dump_name",
        "source": source,
        "state": "complete",
        "started_utc": "2026-01-31T12:00:00Z",
        "ended_utc": "2026-01-31T13:00:00Z",
        "code_commit": "0" * 40,
    }
    return RunRecord(**{**values, **changes})


def test_a_country_gets_its_sources_with_held_copies_first(tmp_path):
    root = make_root(tmp_path)
    assert [x.id for x in s.sources_for("BRA", root)] == ["lusophone_dump", "world_site"]
    assert [x.id for x in s.sources_for("KEN", root)] == ["kenya_archive", "world_site"]
    assert [x.id for x in s.sources_for("JPN", root)] == ["world_site"]
    text = s.format_sources_for(
        "BRA", s.sources_for("BRA", root), [record("lusophone_dump", rows_added=7)]
    )
    assert text.splitlines() == [
        "BRA: 2 sources apply, 1 already ran, 1 never ran.",
        "lusophone_dump (bulk_dump, requests not_applicable, entry not checked): 1 runs",
        "    2026-01-31 dump_name: complete, 7 rows",
        "world_site (live_site, requests allowed, delay 1.5 s): never ran",
    ]


def test_the_page_lists_each_kind_and_each_country(tmp_path):
    root = make_root(tmp_path)
    page = s.render_lyric_sources_markdown(
        s.load_lyric_sources(root), s.load_language_countries(root)
    )
    assert "## Kind: bulk_dump" in page and "## Kind: manual" not in page
    assert "| BRA | `lusophone_dump` |" in page and "| KEN | `kenya_archive` |" in page
    assert "These sources serve every country: `world_site`." in page
    assert "A \\| in a note" in page


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('id = "world_site"', 'id = "World Site"', "lower case"),
        ('id = "world_site"', 'id = "kenya_archive"', "appears twice"),
        ('kind = "live_site"', 'kind = "website"', "kind must be"),
        ('scope = "global"', 'scope = "world"', "scope must be"),
        ('scope = "global"', 'scope = "countries"', "needs \\['countries'\\]"),
        ('languages = ["pt"]', 'countries = ["BRA"]', "needs \\['languages'\\]"),
        ('languages = ["pt"]', 'languages = ["xx"]', "language in"),
        ('countries = ["KEN"]', 'countries = ["Kenya"]', "three capital letters"),
        ('routes = ["live"]', 'routes = ["scrape"]', "routes must name"),
        ('routes = ["archive"]', "routes = []", "routes must name"),
        ('access = "blocked"', 'access = "maybe"', "access must be"),
        ('stored_path = "raw/lusophone_dump/20260101/"', 'stored_path = "C:/dumps"', "stored_path"),
        ('stored_path = "raw/lusophone_dump/20260101/"', 'stored_path = "gs://b/x"', "stored_path"),
        ("checked = false\n", "", "missing \\['checked'\\]"),
        ("checked = false", "checked = false\nowner = 1", "unknown \\['owner'\\]"),
    ],
)
def test_a_bad_sources_file_is_refused(tmp_path, old, new, message):
    assert SOURCES.count(old) == 1
    root = make_root(tmp_path, sources=SOURCES.replace(old, new))
    with pytest.raises(ValueError, match=message):
        s.load_lyric_sources(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('code = "pt"', 'code = "por"', "two lower-case letters"),
        ('countries = ["BRA", "PRT"]', "countries = []", "at least one"),
        ('name = "Portuguese"', 'name = "Portuguese"\nofficial = true', "nothing else"),
    ],
)
def test_a_bad_languages_file_is_refused(tmp_path, old, new, message):
    root = make_root(tmp_path, languages=LANGUAGES.replace(old, new))
    with pytest.raises(ValueError, match=message):
        s.load_language_countries(root)


def test_a_run_record_may_name_only_a_registered_source(tmp_path):
    with pytest.raises(ValueError, match="is not in resources/lyric_sources.toml"):
        run_records.write_run_record(record("site_nobody_entered"), tmp_path)
    with pytest.raises(ValueError, match="is not in resources/lyric_sources.toml"):
        with run_records.record_run("BRA", "live", "site_nobody_entered", countries=tmp_path):
            raise AssertionError("the run must not start")
    assert not list(tmp_path.rglob("*.json"))


def test_every_committed_run_record_names_a_registered_source():
    ids = s.source_ids()
    assert {"review_workbook", "old_pipeline"} <= ids
    bad = [f"{r.iso3}/{r.file_name}" for r in run_records.read_run_records() if r.source not in ids]
    assert not bad, f"add these sources to {s.SOURCES_FILE.as_posix()}: {bad}"


def test_the_command_lists_the_sources_of_a_country(tmp_path, monkeypatch):
    monkeypatch.setattr(run_records, "countries_dir", lambda: tmp_path)
    result = CliRunner().invoke(app, ["lyrics", "sources", "eth"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert result.output.startswith("ETH: ")
    assert "never ran" in result.output
    assert CliRunner().invoke(app, ["lyrics", "sources", "Ethiopia"]).exit_code != 0


def test_generated_page_is_current():
    on_disk = (ROOT / s.SOURCES_PAGE).read_text(encoding="utf-8")
    page = s.render_lyric_sources_markdown(s.load_lyric_sources(), s.load_language_countries())
    assert on_disk == page, (
        "docs/standards/lyric_sources.md is out of date. "
        "Run: python -m songs.common.lyric_sources --write"
    )
