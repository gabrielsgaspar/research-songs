---
id: "0010"
title: One layout for all data
status: accepted
date: 2026-11-19
supersedes: null
---

# One layout for all data

## Context

The project keeps its data in a local data folder and in one cloud storage bucket. A review of the bucket found one cause for most of its problems: paths had no single rule. Dates stood above countries, so an update of one country uploaded all countries again. Sources and layers appeared in two orders. Each lyric source had its own "clean" format. A country was a folder with one file per artist, and the columns differed between the files of one country. Nobody could list what was uploaded and when.

## Decision

Every saved file has a path of one form: `<layer>/<whose>/<when>/<files>`.

- The layers are `raw` (files as received), `clean` (tidy tables built from raw files), `lyrics` (one folder per country) and `analysis` (the final files that every table and regression reads).
- "Whose" is a source key in lower case or a country code in upper case. "When" is a date `YYYYMMDD` for a download or a build, and a run id for a collection run or a scoring run.
- The dated folder or the run folder is the version folder. It is write-once. It holds one `_MANIFEST.json`, written last. A folder without a manifest is incomplete. A correction is a new version folder.
- A date never stands above a country. A folder name never holds a campaign name, the name of a person or a retry counter. Source and year are columns, never folders.
- A country is `lyrics/<ISO3>/songs/<run id>/` with three tables: `artists.parquet`, `songs.parquet` and `links.parquet`. Each collection run reads the newest folder, adds or replaces rows, and writes the full tables to a new folder named by its run id. The newest folder that has a manifest is the current state of the country.
- Each lyric dump has the same two tables, `songs.parquet` and `artist_names.parquet`, in `clean/dumps/<source>/<YYYYMMDD>/`.
- The local data folder and the bucket have the same paths. Code works only with paths relative to the data folder.

No version folder is deleted, in the bucket or as the only local copy, until a later decision sets a rule for it.

A file that has no place in the layout yet goes to a holding area. The holding area is outside the layout, under `holding/<YYYYMMDD>/`. It keeps the path that the file had before, and each unit has a manifest. A file in holding is a stored copy, not an input: no code of this repository reads it.

Objects that the bucket held before this layout stay where they are. They are not moved to a second bucket or to a `legacy/` folder. A list gives each of them a class (has a successor, was rebuilt, sole copy, not checked), and a person deletes by that list on a date that the person sets.

`docs/standards/data_layout.md` is the standard: the tree, the tables with their columns, and the manifest. The path functions are in `songs.common.paths`, the table schemas in `songs.common.schemas`, and the manifest in `songs.common.manifests`. No other module builds a data path from strings, and a writer checks a table against its schema before it writes.

## Consequences

- "Where does this file go?" and "which columns does this table have?" have one answer in one place.
- An update of one country writes only in the folder of that country.
- A manifest says which files a folder holds, which code wrote them, and what they were built from. A list of the manifests is a list of what exists.
- Cost: each country update writes the full tables of the country again, also the rows that did not change. Storage grows with each run, because no version folder is deleted yet. One full copy of all countries is about 1.7 GiB today.
- Cost: a reader cannot use a fixed path. It must take the newest folder that has a manifest.
- Cost: data collected before this decision needs an importer. Until the importer runs for a source or a country, that data does not follow the layout. The standard lists the known gaps.
- Cost: a folder named by a date allows one build per day.
- Cost: saved data has no file per artist. A collector that must continue after a stop keeps its own working files in a local folder that is never uploaded.
- Cost: the holding area and the earlier objects make the bucket larger until the deletion by list.
