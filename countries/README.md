# Countries

One folder per country, named by its ISO 3166-1 alpha-3 code (`BRA`, `NGA`, `JPN`). The folder is the history of lyric collection for that country ([decision 0003](../docs/decisions/0003-country-folders-and-run-records.md)).

```
countries/<ISO3>/
  runs/        one JSON file per collection run, written by the command that ran
  notes.md     known gaps and their causes (optional, written by people)
```

A folder appears with the first run of its country.

## Where the data of a country is

This folder holds only the history. The songs of a country are in the data folder, never in Git:

```
lyrics/<ISO3>/songs/<run id>/     artists.parquet, songs.parquet, links.parquet, _MANIFEST.json
```

Each run writes the full tables of the country to a new folder, and the name of the folder is the `run_id` of its run record. The newest folder that has a manifest is the current state of the country. [`docs/standards/data_layout.md`](../docs/standards/data_layout.md) gives the columns of each table and the fields of the manifest.

## Before a run

Read what already ran, so the same job does not run twice:

```bash
uv run songs lyrics history BRA
```

## Run records

A collection command writes one record when it ends, also when it fails. Nobody writes or edits a record by hand, and a record is never overwritten. The file name is `<run id>_<route>_<source>.json`.

| Field | Meaning |
| --- | --- |
| `iso3` | Country code |
| `run_id` | Start of the run in UTC, `YYYYMMDDTHHMMSSZ` |
| `route` | How the lyrics were collected (list below) |
| `source` | Key of the site, archive or dataset |
| `state` | `complete`, `partial` or `failed` |
| `started_utc`, `ended_utc` | Start and end of the run |
| `code_commit` | Commit of the code that ran |
| `bulk_file` | Path of the bulk file inside the storage bucket, when one was used |
| `request_delay_seconds` | Wait between requests to the source |
| `artist_limit`, `song_limit` | Limits set for the run |
| `deadline_utc` | Time limit set for the run |
| `artists_attempted`, `rows_added` | What the run did |
| `known_gaps` | What the run could not get, one line each |
| `notes` | Anything else a later reader needs |
| `backfilled` | `true` when the record was rebuilt later from old run files |

An empty value means "not recorded". It never means zero.

## Routes

| Route | Meaning |
| --- | --- |
| `live` | Requests to a lyric site for the artists of the country |
| `roster_update` | A live run for artists added to the country since the last run |
| `recover` | A second live run for artists or songs that failed before |
| `genius_local` | Match against a local copy of Genius data |
| `lrclib_local` | Match against a local copy of the LRCLIB database |
| `archive` | Import from a whole-site archive collected earlier |
| `dump_name` | Match by artist and title against a bulk file |
| `local_source` | Import from a dataset that someone gave to the project |
| `manual_review` | Import of the songs that a person added to a country review workbook |
| `old_layout` | Import of the state of a country from the files of the old pipeline. The old files do not record how each song was first collected |

## Coverage page

[`docs/status/coverage.md`](../docs/status/coverage.md) has one row per country. It is generated from the records, and a test fails when it is out of date:

```bash
uv run songs lyrics coverage --write
```
