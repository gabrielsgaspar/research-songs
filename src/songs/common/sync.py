"""The weekly sync: upload the complete local version folders that the bucket lacks.

`sync` finds the folders, applies the guard for songs folders, and gives the rest to
`storage.publish`, which is the only upload path. `stale` only reads: it names each
derived folder that has a newer input. `report` writes the result as Markdown.

The sync never deletes, never builds and never scores. It reads only the kinds in
`KINDS`, so `cache/`, `tmp/` and `staging/` never go to the bucket.
"""

from pathlib import Path, PurePosixPath

from songs.common import manifests, paths, run_records, storage

# The folders above the version folders, inputs first.
KINDS = (
    "clean/dumps/*/",
    "clean/catalog/*/",
    "clean/countries/",
    "clean/quality/song_quarantine/",
    "lyrics/*/songs/",
    "clean/quality/artist_country/",
    "lyrics/*/scores/",
    "analysis/",
)
OPEN_CAMPAIGN = "the country has an open campaign"
NO_RECORD = "no run record with this run id"
PANEL_COMMAND = "uv run songs panel countries"
RELEASE_COMMAND = "uv run songs analysis release"


def _complete(parent: Path) -> list[Path]:
    """Return the version folders under `parent` that have a manifest, oldest first."""
    return sorted(
        path
        for path in parent.glob("*")
        if storage._is_version(path.name) and (path / paths.MANIFEST_NAME).is_file()
    )


def _parents(data: Path, patterns: tuple[str, ...] = KINDS) -> list[Path]:
    return [path for pattern in patterns for path in sorted(data.glob(pattern)) if path.is_dir()]


def held_songs(data: Path, countries: Path | None = None) -> dict[str, str]:
    """Return each complete songs folder that must not go to the bucket, with the reason.

    A songs folder goes only when `countries/<ISO3>/runs/` holds a run record with its
    run id and the country has no open campaign. The function reads the files of the
    checkout; it does not ask Git whether a record is committed.
    """
    base = countries or run_records.countries_dir()
    held = {}
    for parent in _parents(data, ("lyrics/*/songs/",)):
        code = parent.parent.name
        campaign = run_records.open_campaign_id(code, base)
        for folder in _complete(parent):
            if campaign:
                held[paths.data_relative(data, folder)] = OPEN_CAMPAIGN
            elif not any((base / code / "runs").glob(f"{folder.name}_*.json")):
                held[paths.data_relative(data, folder)] = NO_RECORD
    return held


def stale(data: Path) -> list[tuple[str, str, str]]:
    """Return (folder, cause, command) for each cause that makes a newest derived folder stale.

    The country panel reads the paths that `resources/data_sources.toml` names, so it is
    stale when a build would now read a file that its manifest does not name. The
    analysis release reads the newest folders, so it is stale when an input has a newer
    complete folder, or when a country has songs or scores that are not an input.
    """
    found = []
    panel = paths.latest_clean_countries_dir(data)
    if panel is not None:
        # Imported here so that a sync with no panel does not load the data libraries.
        from songs.stage_50_analysis import countries_panel

        inputs = countries_panel.default_inputs(data)
        absent = [name for name, path in inputs.items() if path is None or not path.exists()]
        new = set(countries_panel.files_read(data, inputs, absent))
        for name in sorted(new - set(manifests.read_manifest(panel).inputs)):
            found.append(
                (paths.data_relative(data, panel), f"a build now reads `{name}`", PANEL_COMMAND)
            )
    release = paths.latest_analysis_dir(data)
    if release is not None:
        folder = paths.data_relative(data, release)
        inputs = [PurePosixPath(item) for item in manifests.read_manifest(release).inputs]
        for item in inputs:
            newest = _complete(data / item.parent)[-1:]
            if storage._is_version(item.name) and newest and newest[0].name > item.name:
                newer = paths.data_relative(data, newest[0])
                found.append((folder, f"`{item}/` has the newer folder `{newer}`", RELEASE_COMMAND))
        known = {item.parent for item in inputs}
        for parent in _parents(data, ("lyrics/*/songs/", "lyrics/*/scores/")):
            if _complete(parent) and PurePosixPath(parent.relative_to(data)) not in known:
                name = paths.data_relative(data, parent)
                found.append((folder, f"`{name}` is not an input", RELEASE_COMMAND))
    return found


def sync(
    transport: storage.Transport,
    bucket: str,
    data: Path,
    *,
    write: bool = False,
    countries: Path | None = None,
) -> dict:
    """Upload the complete folders of `KINDS` that the bucket lacks, inputs first.

    Without `write`, nothing is uploaded. Return the lists of `storage.publish`, with
    `held` (the songs folders that the guard keeps back, each with its reason) and
    `stale` (the result of `stale`).
    """
    held = held_songs(data, countries)
    folders = [paths.data_relative(data, parent) for parent in _parents(data)]
    result = storage.publish(transport, bucket, data, folders, held=held, write=write)
    result["held"] = {
        folder: reason for folder, reason in held.items() if folder not in result["present"]
    }
    result["stale"] = stale(data)
    return result


def report(data: Path, result: dict, *, write: bool) -> str:
    """Return the Markdown report of a sync: counts first, then one line for each folder."""
    rows = {
        folder: sum(entry["rows"] or 0 for entry in manifests.read_manifest(data / folder).files)
        for folder in result["uploaded"]
    }
    missing = dict(result["missing_inputs"])
    left = dict(result["held"])
    for folder in result["skipped"]:
        left[folder] = (
            f"the input `{missing[folder]}` is not on this disk and not in the bucket"
            if folder in missing
            else "an input is left out"
        )
    verb = "Uploaded" if write else "Would upload"
    lines = [
        f"# Data sync, {run_records.utc_now()}{'' if write else ', dry run'}",
        "",
        f"- {verb}: {len(rows)} folders, {sum(rows.values())} rows",
        f"- In the bucket already: {len(result['present'])} folders",
        f"- Left out: {len(left)} folders",
        f"- Stale: {len({folder for folder, _, _ in result['stale']})} folders",
    ]
    if rows:
        lines += ["", f"## {verb}", ""]
        lines += [f"- `{folder}`: {number} rows" for folder, number in rows.items()]
    if left:
        lines += ["", "## Left out", ""]
        lines += [f"- `{folder}`: {reason}" for folder, reason in left.items()]
    if result["stale"]:
        lines += ["", "## Stale", ""]
        lines += [
            f"- `{folder}`: {cause}. To build it again, run `{command}`"
            for folder, cause, command in result["stale"]
        ]
    return "\n".join(lines)
