# Countries

One folder per country, named by its ISO 3166-1 alpha-3 code (`BRA`, `NGA`, `JPN`). The folder is the history of lyric collection for that country ([decision 0003](../docs/decisions/0003-country-folders-and-run-records.md)).

```
countries/<ISO3>/
  runs/        one JSON file per collection run, written by the command that ran
  campaigns/   two JSON files per campaign: one when it opens, one when it closes
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
uv run songs lyrics plan BRA
```

The plan lists each source that can serve the country. For a source that already ran, it shows the last run: date, route, duration, delay, limits, requests sent, songs accepted of songs attempted, rejections by reason, and limits that were hit. Then it shows what the last closed campaign said to try next. `uv run songs lyrics history BRA` lists every run, with its duration and its campaign.

A run that repeats a complete run is refused before any work. The same job is the same country, route, source, bulk file, request delay, artist limit and song limit. To run it again, change a setting or give a reason; the reason goes to `notes` of the new record.

## Campaigns

A campaign is one effort with a goal for one country, for example "add songs before 1990". It is made of several runs. Open the campaign before its first run and close it after its last run:

```bash
uv run songs lyrics campaign open BRA --goal "Add songs before 1990"
uv run songs lyrics campaign close BRA --outcome complete --next-time "Raise the song limit from 5 to 20."
uv run songs lyrics campaign list BRA
```

Each run that starts while the campaign is open carries its id in `campaign_id`. Nobody types the list of runs. A country has at most one open campaign.

The close command refuses an empty `--next-time`. That text is what a later campaign reads first, so write what to try next, or why no more work is useful. The outcomes `stopped` and `abandoned` also need `--reason`.

A campaign has two files in `countries/<ISO3>/campaigns/`: `<campaign id>_open.json` and `<campaign id>_close.json`. Each file is written one time and never changed. A campaign with no close file is open. The name of a campaign never appears in a folder name of the data.

| Field | File | Meaning |
| --- | --- | --- |
| `iso3` | both | Country code |
| `campaign_id` | both | Time the campaign opened in UTC, `YYYYMMDDTHHMMSSZ` |
| `goal` | open | What the campaign must reach |
| `opened_utc` | open | Time the campaign opened |
| `songs_before` | open | Songs of the country at the start. The command reads the newest songs folder; `--songs` gives the number by hand |
| `closed_utc` | close | Time the campaign closed |
| `songs_after` | close | Songs of the country at the end |
| `outcome` | close | `complete`, `stopped` or `abandoned` |
| `reason` | close | Why the campaign stopped |
| `next_time` | close | What the next campaign must try |

## Run a campaign

This is the order of steps for one country or for several. Each step is one command. A command that takes countries accepts a list, for example `BRA NGA`. The examples use `BRA`.

1. Read the plan. It shows the last run of each source and what the last campaign said to try next:

   ```bash
   uv run songs lyrics plan BRA
   ```

2. Pull the folders that the campaign needs: the songs of the country, its scores, the dump of each of its sources and the Discogs catalog. A folder that is complete on this disk is not downloaded again:

   ```bash
   uv run songs data pull BRA
   ```

3. Look at the thin decades. The command shows, by decade, the songs that the country holds and the Discogs tracks that it lacks. `--years` shows one year or one range of years:

   ```bash
   uv run songs lyrics gaps BRA --years 1960-1969
   ```

4. Estimate what each dump on this disk adds. The command writes nothing:

   ```bash
   uv run songs lyrics survey BRA --years 1960-1969
   ```

5. Run the campaign. It estimates each dump, opens a campaign, imports the dumps that add songs, and leaves the campaign open:

   ```bash
   uv run songs lyrics campaign run BRA --goal "Add songs before 1970" --years 1960-1969
   ```

6. Read the report. It holds counts only: the runs, the songs not added by reason, the songs by decade, and the songs that wait for scoring:

   ```bash
   uv run songs lyrics campaign report BRA --years 1960-1969
   ```

7. Close the campaign. Write what the next campaign must try:

   ```bash
   uv run songs lyrics campaign close BRA --outcome complete --next-time "Raise the Discogs coverage of the 1960s."
   ```

8. Publish the new songs folder and its inputs to the bucket:

   ```bash
   uv run songs lyrics publish BRA
   ```

9. Audit the run records against the bucket. It takes about 3 minutes:

   ```bash
   uv run songs lyrics audit
   ```

10. Write the coverage page again:

    ```bash
    uv run songs lyrics coverage --write
    ```

11. Open the pull request with the new run records, the campaign records and the coverage page. Use the report of step 6 as the body of the pull request.

What the commands do:

- A campaign run opens no campaign and writes nothing when the estimates of all dumps of the country sum to fewer than `--min-songs` songs. The default is 25 songs.
- When the country has an open campaign, the runs join it. The goal of the command is not used.
- A dump that ran before runs again when the estimate says that it adds songs. The estimate is the reason in the run record.
- A dump run adds every match. It cannot aim at a decade. `--years` changes only what the goal, the report and the survey show.
- After the first import, each remaining dump is estimated again on the new songs folder, because an earlier import can take its tracks.
- No command calls a model. A person starts topic scoring.
- Each import writes the full tables of the country to a new folder.
- A song is published when it is in the newest complete songs folder of its country, that folder passes `songs data check` in the bucket, and its run record is on `main`.

### Artists with no Discogs id

A roster artist with no Discogs id gets one when exactly one Discogs artist has the same name key. No other roster artist may hold that id or have that key. A release of the country must credit that Discogs artist, so an artist of another country with the same name gets no id. The file `resources/lyrics/discogs_countries.csv` lists the release countries of Discogs that count for each country; a state that no longer exists, such as the USSR, counts for each country that followed it. The songs of the artist still need a title match with a track of that artist. The links of these songs carry a match method that ends with `_artist_by_name`.

### Artists of another country

Some rosters hold artists of other countries. `uv run songs lyrics roster-check` applies one automatic rule to every roster and prints the counts. It takes about 10 minutes and reads only. With `--write`, it writes the table `clean/quality/artist_country/<YYYYMMDD>/artist_country.parquet` in the data folder.

The rule looks at each roster artist with a Discogs id, also an id found by name. The artist gets the decision `other_country` only when three conditions hold: the start of the Discogs profile states another country, the same text has no word of a home country, and fewer than 20% of the releases of the artist are in a home release country while another country has the most releases. Every other artist gets `keep`. No person checks a row. [The data layout](../docs/standards/data_layout.md) gives the rule in full and the columns of the table. The country words are in `resources/lyrics/country_words.csv`.

## Collect a lyric site

A site with no dump on this disk is collected first. One collector exists, for `dainutekstai` (LTU). Only a person starts it, because it sends requests to the site:

```bash
uv run songs lyrics collect dainutekstai LTU
```

What the command does:

- It reads `robots.txt` first. It sends no request that `robots.txt` disallows, and it counts each page that it skips.
- It waits 2 seconds or more between requests. `--delay` gives a longer wait. The delay of the source file and the crawl delay of `robots.txt` apply when they are longer.
- It sends a request again when the site gives no answer, a server error or an empty page. It waits 1 minute, then 5 minutes, then 15 minutes before each new try. It stops at HTTP 401, 403 or 429, and after 3 pages in a row that still fail.
- `--artist-limit` and `--song-limit` make a short first run.
- It writes `raw/dainutekstai/<YYYYMMDD>/` in the data folder: one lyric table and a manifest. It never writes over a folder, so a second run on the same day is refused.
- It writes one run record with the route `live`: the delay, the limits, the pages requested, the songs written, and the songs left out by reason. `rows_added` is 0, because the command adds no song to the country.
- A run that ends early keeps its songs. Its folder has a file `STOP`, so the dump is marked as incomplete.
- The next run continues a folder that has a file `STOP`. It reads only the songs that the folder lacks, and its new folder holds the songs of both runs. Its run record counts only the songs that it read.

The command prints the two commands that follow it. `songs dumps build` turns the raw folder into a dump, and `songs lyrics import-dump` adds the songs that match a Discogs track.

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
| `campaign_id` | The campaign that was open when the run started |
| `requests_sent` | Requests sent to the source. A run on a local copy sends 0 |
| `songs_attempted`, `songs_accepted` | Songs that the run looked at, and songs that passed its checks |
| `songs_rejected` | Songs that failed a check: the reason, then the count |
| `limits_hit` | Limits that stopped work early: the name of the limit, then the number of artists or a note. An empty value `{}` means that no limit was hit |
| `notes` | Anything else a later reader needs |
| `backfilled` | `true` when the record was rebuilt later from old run files |

An empty value means "not recorded". It never means zero.

The duration of a run has no field. The commands compute it from `started_utc` and `ended_utc`.

Records of schema version 1 do not have the fields from `campaign_id` to `limits_hit`. They still load, and each of these fields reads as "not recorded".

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
