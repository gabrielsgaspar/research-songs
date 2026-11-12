import shutil

import pytest

from songs.common import data_sources as d


def test_the_file_loads_and_names_the_chosen_sources():
    sources = d.load_sources()
    assert len({source.id for source in sources}) == len(sources)
    assert d.canonical("GDP per capita").id == "gdp_maddison"
    assert d.canonical("Democracy").id == "democracy_anrr"
    assert d.canonical("Fertility").id == "fertility_hfd"
    assert d.canonical("Income inequality (Gini)").id == "gini_wdi"
    with pytest.raises(KeyError):
        d.canonical("United States recessions")  # supplementary only


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('status = "robustness"', 'status = "canonical"', "more than one canonical"),
        (
            'status = "canonical"\ncolumns = ["gini"]',
            'status = "main"\ncolumns = ["gini"]',
            "status",
        ),
        ('id = "gdp_pwt"', 'id = "gdp_maddison"', "appears twice"),
        ('version = "11.0"\n', "", "missing"),
        ('raw_path = "raw/un_wpp/2024/"', 'raw_path = "C:/data/un_wpp"', "raw_path"),
    ],
)
def test_a_bad_file_is_refused(tmp_path, old, new, message):
    text = (d.resolve_project_root() / d.SOURCES_FILE).read_text(encoding="utf-8")
    assert text.count(old) == 1
    (tmp_path / "resources").mkdir()
    (tmp_path / d.SOURCES_FILE).write_text(text.replace(old, new), encoding="utf-8")
    shutil.copy(d.resolve_project_root() / "pyproject.toml", tmp_path / "pyproject.toml")
    with pytest.raises(ValueError, match=message):
        d.load_sources(tmp_path)


def test_generated_page_is_current():
    on_disk = (d.resolve_project_root() / d.SOURCES_PAGE).read_text(encoding="utf-8")
    assert on_disk == d.render_sources_markdown(d.load_sources()), (
        "docs/standards/data_sources.md is out of date. "
        "Run: python -m songs.common.data_sources --write"
    )
