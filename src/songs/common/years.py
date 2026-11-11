"""The window of release years that analysis accepts.

A song year is usable only from `MIN_SONG_YEAR` to `MAX_SONG_YEAR`. A table
reports every other song as "No year" (missing) or "Out of range" (present but
impossible). It never drops such a song silently, and never counts it in a panel.
"""

MIN_SONG_YEAR = 1900
MAX_SONG_YEAR = 2026

DATED_COLUMN = "Dated"
NO_YEAR_COLUMN = "No year"
OUT_OF_RANGE_COLUMN = "Out of range"
YEAR_STATUS_COLUMNS = [DATED_COLUMN, NO_YEAR_COLUMN, OUT_OF_RANGE_COLUMN]


def is_admissible_year(value: object) -> bool:
    """Return whether a year value is a finite number inside the window."""
    try:
        year = round(float(value))  # type: ignore[arg-type]
    except TypeError, ValueError, OverflowError:
        return False
    return MIN_SONG_YEAR <= year <= MAX_SONG_YEAR
