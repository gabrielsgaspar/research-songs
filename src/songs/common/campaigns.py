"""Campaign records: one effort with a goal for one country, made of several runs.

A campaign says why a group of runs happened and what the next campaign must
try. Its runs are the run records that carry its id; nobody types that list.

    countries/<ISO3>/campaigns/<campaign id>_open.json     written by `open_campaign`
    countries/<ISO3>/campaigns/<campaign id>_close.json    written by `close_campaign`

Each file is written one time and never changed. A campaign with no close file
is open, and a country has at most one open campaign.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from songs.common import run_records
from songs.common.paths import ISO3, RUN_ID
from songs.common.run_records import RunRecord

SCHEMA_VERSION = 1
OUTCOMES = ("complete", "stopped", "abandoned")
OPEN_FIELDS = ("iso3", "campaign_id", "goal", "opened_utc", "songs_before", "schema_version")
CLOSE_FIELDS = (
    "iso3",
    "campaign_id",
    "closed_utc",
    "songs_after",
    "outcome",
    "reason",
    "next_time",
    "schema_version",
)


@dataclass
class Campaign:
    """One campaign of one country. `None` means "not recorded", never zero."""

    iso3: str
    campaign_id: str
    goal: str
    opened_utc: str
    songs_before: int | None = None
    closed_utc: str | None = None
    songs_after: int | None = None
    outcome: str | None = None
    reason: str = ""
    next_time: str = ""

    @property
    def is_open(self) -> bool:
        return self.closed_utc is None


def _folder(iso3: str, countries: Path | None) -> Path:
    if not ISO3.fullmatch(iso3):
        raise ValueError(f"iso3 must be three capital letters, got {iso3!r}")
    return (countries or run_records.countries_dir()) / iso3 / "campaigns"


def _write_once(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _read(path: Path, expected: tuple[str, ...], iso3: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if set(payload) != set(expected):
        raise ValueError(f"{path}: the fields must be {sorted(expected)}")
    name = f"{payload['campaign_id']}_{'open' if 'goal' in payload else 'close'}.json"
    if name != path.name or payload["iso3"] != iso3 or not RUN_ID.fullmatch(path.name[:16]):
        raise ValueError(f"{path}: file name or folder does not match the record")
    del payload["schema_version"]
    return payload


def read_campaigns(iso3: str, countries: Path | None = None) -> list[Campaign]:
    """Return the campaigns of one country, oldest first."""
    folder = _folder(iso3, countries)
    campaigns = {}
    for path in sorted(folder.glob("*_open.json")):
        campaign = Campaign(**_read(path, OPEN_FIELDS, iso3))
        campaigns[campaign.campaign_id] = campaign
    for path in sorted(folder.glob("*_close.json")):
        close = _read(path, CLOSE_FIELDS, iso3)
        if close["campaign_id"] not in campaigns:
            raise ValueError(f"{path}: this campaign has no open file")
        if close["outcome"] not in OUTCOMES:
            raise ValueError(f"{path}: outcome must be one of {OUTCOMES}")
        for name, value in close.items():
            setattr(campaigns[close["campaign_id"]], name, value)
    return [campaigns[key] for key in sorted(campaigns)]


def held_countries(countries: Path | None = None) -> list[str]:
    """Return the countries whose newest campaign stopped after it added songs.

    Such a campaign added songs and then failed a check, for example a roster
    check, so its songs wait for a later campaign. A stopped campaign that added
    no songs (`songs_after` is not more than `songs_before`) holds nothing: its
    stop was about a source, not about the songs that the country holds. A
    campaign that did not record both counts is held.
    """
    root = countries or run_records.countries_dir()
    held = []
    for folder in sorted(root.glob("*/campaigns")):
        if not ISO3.fullmatch(folder.parent.name):
            continue
        found = read_campaigns(folder.parent.name, root)
        newest = found[-1] if found else None
        if newest is None or newest.outcome != "stopped":
            continue
        before, after = newest.songs_before, newest.songs_after
        if before is None or after is None or after > before:
            held.append(newest.iso3)
    return held


def open_campaign(
    iso3: str, goal: str, *, songs_before: int | None = None, countries: Path | None = None
) -> Campaign:
    """Open a campaign for a country. Refuse when the country has an open campaign."""
    folder = _folder(iso3, countries)
    if not goal.strip():
        raise ValueError("a campaign needs a goal")
    current = run_records.open_campaign_id(iso3, countries)
    if current:
        raise FileExistsError(
            f"{iso3} has an open campaign, {current}. Close it before you open a new campaign."
        )
    campaign = Campaign(
        iso3, run_records.new_run_id(), goal.strip(), run_records.utc_now(), songs_before
    )
    values = {name: getattr(campaign, name) for name in OPEN_FIELDS[:-1]}
    values["schema_version"] = SCHEMA_VERSION
    _write_once(folder / f"{campaign.campaign_id}_open.json", values)
    return campaign


def close_campaign(
    iso3: str,
    outcome: str,
    next_time: str,
    *,
    reason: str = "",
    songs_after: int | None = None,
    countries: Path | None = None,
) -> Campaign:
    """Close the open campaign of a country. `next_time` says what the next campaign must try."""
    folder = _folder(iso3, countries)
    current = run_records.open_campaign_id(iso3, countries)
    if not current:
        raise FileNotFoundError(f"{iso3} has no open campaign")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if not next_time.strip():
        raise ValueError(
            "next_time is empty: say what the next campaign must try, or why no more work is useful"
        )
    if outcome != "complete" and not reason.strip():
        raise ValueError(f"a campaign that is {outcome} needs a reason")
    close = {
        "iso3": iso3,
        "campaign_id": current,
        "closed_utc": run_records.utc_now(),
        "songs_after": songs_after,
        "outcome": outcome,
        "reason": reason.strip(),
        "next_time": next_time.strip(),
        "schema_version": SCHEMA_VERSION,
    }
    _write_once(folder / f"{current}_close.json", close)
    return next(c for c in read_campaigns(iso3, countries) if c.campaign_id == current)


def _count(value: int | None) -> str:
    return "not recorded" if value is None else str(value)


def format_campaigns(campaigns: list[Campaign], records: list[RunRecord]) -> str:
    """Return the campaigns of a country as plain lines, each with its runs."""
    if not campaigns:
        return "No campaigns recorded."
    lines = []
    for campaign in campaigns:
        state = (
            "open" if campaign.is_open else f"{campaign.outcome}, closed {campaign.closed_utc[:10]}"
        )
        lines += [
            f"{campaign.iso3} campaign {campaign.campaign_id}: {state}",
            f"    goal: {campaign.goal}",
            f"    songs before: {_count(campaign.songs_before)}"
            + ("" if campaign.is_open else f", songs after: {_count(campaign.songs_after)}"),
        ]
        if campaign.reason:
            lines.append(f"    reason: {campaign.reason}")
        if campaign.next_time:
            lines.append(f"    next time: {campaign.next_time}")
        runs = [record for record in records if record.campaign_id == campaign.campaign_id]
        lines.append(f"    runs: {len(runs)}")
        lines += [
            f"        {line}" for line in run_records.format_history(runs).splitlines() if runs
        ]
    return "\n".join(lines)


def _last_run_lines(run: RunRecord) -> list[str]:
    """Return what the next run of a source must know about its last run."""

    def pairs(values: dict | None) -> str:
        if values is None:
            return "not recorded"
        # The largest count first: it is the first thing to fix.
        ordered = sorted(
            values.items(), key=lambda item: -item[1] if isinstance(item[1], int) else 0
        )
        return ", ".join(f"{name}: {value}" for name, value in ordered) or "none"

    settings = ", ".join(
        f"{label} {_count(value) if value is None else value}"
        for label, value in (
            ("delay s", run.request_delay_seconds),
            ("artist limit", run.artist_limit),
            ("song limit", run.song_limit),
        )
    )
    took = run_records.duration_text(run)
    return [
        f"    last run {run.started_utc[:10]} {run.route}: {run.state}"
        f"{', ' + took if took else ''}, rows added {_count(run.rows_added)}",
        f"    settings: {settings}",
        f"    requests sent: {_count(run.requests_sent)}; "
        f"songs accepted: {_count(run.songs_accepted)} of {_count(run.songs_attempted)} attempted",
        f"    rejected: {pairs(run.songs_rejected)}",
        f"    limits hit: {pairs(run.limits_hit)}",
    ]


def format_plan(
    iso3: str, sources: list, records: list[RunRecord], campaigns: list[Campaign]
) -> str:
    """Return what a new campaign for a country must read first.

    For each source that can serve the country: "never ran", or the settings and
    the results of its last run. Then the advice of the last closed campaign.
    """
    lines, ran = [], 0
    for source in sources:
        runs = [record for record in records if record.source == source.id]
        ran += bool(runs)
        lines.append(
            f"{source.id} ({source.kind}, requests {source.access}): "
            f"{f'{len(runs)} runs' if runs else 'never ran'}"
        )
        if runs:
            lines += _last_run_lines(runs[-1])
    head = (
        f"{iso3}: {len(sources)} sources apply, {ran} already ran, {len(sources) - ran} never ran."
    )
    current = [campaign for campaign in campaigns if campaign.is_open]
    closed = [campaign for campaign in campaigns if not campaign.is_open]
    if current:
        lines.append(f"Open campaign {current[-1].campaign_id}: {current[-1].goal}")
    if closed:
        last = closed[-1]
        lines += [
            f"Last closed campaign {last.campaign_id} ({last.outcome}): {last.goal}",
            f"    next time: {last.next_time}",
        ]
    if not campaigns:
        lines.append("No campaigns recorded.")
    return "\n".join([head, *lines])
