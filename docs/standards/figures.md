# Figure standards

Every paper figure follows these rules. The code is in `src/songs/common/plot_style.py`. A test checks that this page and the module agree.

A figure calls `apply_paper_matplotlib(plt)` once, draws with the constants in the module, and saves with `save_png(fig, path)`. If a figure needs something that this page does not cover, add it to the module and to this page first.

## Output

Figures are PNG only, at 300 dpi (`DPI`), with a white background and a tight bounding box. `save_png` does this. It creates the parent folder. It raises `ValueError` for any suffix other than `.png`. No figure calls `savefig` itself.

## Sizes

Sizes are in inches, width then height. Pick one of the four names. Do not type a size by hand.

| Name | Width x height | Use |
| --- | --- | --- |
| `SIZE_STANDARD` | 8.0 x 5.0 | Default. One panel, such as a line chart or a bar chart. |
| `SIZE_LARGE` | 8.5 x 6.0 | One panel with many labels or a long legend. |
| `SIZE_WIDE` | 12.0 x 5.0 | Several panels side by side, or a long time series. |
| `SIZE_TALL` | 7.0 x 8.0 | Many rows, such as one row per topic or per country. |

The old analysis code used 8.5 x 6.0 in 11 figures, 8.0 x 5.0 in 11, 7 x 8 in 8, and 12 x 5 in 4. Of 197 `dpi=` arguments that named a number, 115 said 300, 72 said 160, 7 said 320, and 3 said 200. The standard is 300.

## Typography

The font is Latin Modern Roman. Math uses Computer Modern. All text is black.

The font lookup never fails. It tries an installed font, then a TeX installation through `kpsewhich`. If it finds neither, it uses STIX and gives one warning. A figure made with the fallback font is for a draft only.

Sizes come from `PAPER_MATPLOTLIB_RCPARAMS`: base 10 pt, title 11 pt in regular weight, axis labels 10 pt, tick labels 9 pt, legend 9 pt. Do not set a font size in a figure. The legend has no frame.

## Numbers

Use `thousands` for counts: 1, 100, 1,000, 10,000. Never use `10^n`, scientific notation, or `k` and `M` suffixes.

Use `percent` for shares. It turns a fraction into a whole percent: 0%, 10%, 100%.

Axes show no offset text.

## Colors

Text, axis lines and ticks are black. The background is white.

Each topic family has one color and one marker. A figure that shows topic families uses these values everywhere, so a family looks the same in every figure.

| Family | Color | Marker | Meaning |
| --- | --- | --- | --- |
| A | `#2a78d6` | `o` | Romantic love, desire and conflict |
| B | `#eb6834` | `s` | Inner life, meaning and mortality |
| C | `#1baf7a` | `^` | Selfhood, agency and aspiration |
| D | `#eda100` | `D` | Society, power and material life |
| E | `#e87ba4` | `v` | Social bonds, community and cultural identity |
| F | `#008300` | `P` | Home, place, nature and everyday life |
| G | `#7a4fa3` | `X` | Pleasure, escape and excess |

For a plot that is not about families, use `CATEGORICAL` in order. It holds six colors: `#2a78d6`, `#eb6834`, `#1baf7a`, `#eda100`, `#e87ba4`, `#008300`. Do not use more than six series in one panel.

## Markers

Seven colors are hard to tell apart. So the marker is a second code for the family. Always draw the family marker with the family color. Label important points directly on the plot.

## Legends

A legend has no frame. Put it inside the plot area where there is space, or below the plot. Never let it cover data. Name each entry with the label from `songs.stage_30_topics.topic_ids`, not with a typed copy.

## Ticks

Linear axes have labeled five-unit major ticks when the scale allows.

Event-time plots label every five years, with unlabeled yearly minor ticks.

Log axes tick at powers of ten only.
