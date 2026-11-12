import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

from songs.common import plot_style as ps
from songs.stage_30_topics import topic_ids

FIGURES_PAGE = Path(__file__).resolve().parents[1] / "docs" / "standards" / "figures.md"


@pytest.mark.parametrize(
    ("value", "text"), [(1, "1"), (100, "100"), (1000, "1,000"), (1234567, "1,234,567")]
)
def test_thousands(value, text):
    assert ps.thousands(value) == text


@pytest.mark.parametrize(("value", "text"), [(0, "0%"), (0.1, "10%"), (1, "100%"), (0.504, "50%")])
def test_percent(value, text):
    assert ps.percent(value) == text


def test_save_png(tmp_path):
    fig, ax = plt.subplots(figsize=ps.SIZE_STANDARD)
    ax.plot([0, 1], [0, 1])
    target = ps.save_png(fig, tmp_path / "new" / "a.png")
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError):
        ps.save_png(fig, tmp_path / "a.pdf")
    plt.close(fig)


def test_font_family_warns_only_on_fallback(monkeypatch):
    monkeypatch.setattr(ps, "_installed", lambda: False)
    monkeypatch.setattr(ps, "_register_from_tex", lambda: None)
    ps.paper_font_family.cache_clear()
    try:
        with pytest.warns(UserWarning, match="not found"):
            assert ps.paper_font_family() == ps.FALLBACK_FONT_FAMILY
        monkeypatch.setattr(ps, "_installed", lambda: True)
        ps.paper_font_family.cache_clear()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert ps.paper_font_family() == ps.PAPER_FONT_FAMILY
    finally:
        ps.paper_font_family.cache_clear()


def test_every_family_has_a_color_and_a_marker():
    families = set(topic_ids.FAMILY_LABELS)
    assert set(ps.FAMILY_COLORS) == families
    assert set(ps.FAMILY_MARKERS) == families
    assert len(set(ps.FAMILY_COLORS.values())) == len(families)
    assert len(set(ps.FAMILY_MARKERS.values())) == len(families)


def test_rcparams_apply():
    ps.apply_paper_matplotlib(plt, overrides={"font.size": 12})
    assert plt.rcParams["font.size"] == 12
    assert plt.rcParams["savefig.dpi"] == ps.DPI
    assert plt.rcParams["text.color"] == ps.PAPER_TEXT_COLOR
    assert plt.rcParams["font.family"] == [ps.paper_font_family()]
    plt.rcdefaults()


def test_figures_page_matches_module():
    page = FIGURES_PAGE.read_text(encoding="utf-8")
    sizes = [name for name in vars(ps) if name.startswith("SIZE_")]
    assert len(sizes) == 4
    for name in sizes:
        assert f"`{name}`" in page
    for color in (*ps.FAMILY_COLORS.values(), *ps.CATEGORICAL):
        assert color in page
    for marker in ps.FAMILY_MARKERS.values():
        assert f"`{marker}`" in page
    assert str(ps.DPI) in page
