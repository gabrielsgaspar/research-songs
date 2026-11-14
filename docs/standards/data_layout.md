# Data layout

This page is the standard for every file in the data folder. Read it before you write code that reads or writes data.

The page answers two questions: where does a data file go, and which columns does a table have?

The column tables on this page are generated from `src/songs/common/schemas.py`. To rebuild them, run `python -m songs.common.schemas --write`. A test fails when they are out of date. All other text on this page is written by hand.

## Where data lives

Data never goes to Git. It lives in a local data folder and in one cloud storage bucket.

- Code finds the local data folder through the environment variable `SONGS_DATA_ROOT`.
- The local data folder and the bucket have the same paths. In the bucket, each path has the prefix `data/`.
- Code works only with paths relative to the data folder. A manifest or a run record never holds a drive letter, a user folder, a scheme or a bucket name.

## The rule

Every saved file has a path of this form:

```
<layer>/<whose>/<when>/<files>
```

- **Layer.** `raw` holds files as received; they are never changed. `clean` holds tidy tables built from raw files. `lyrics` holds one folder per country. `analysis` holds the final files that every table and regression reads.
- **Whose.** A source key in lower case (`lrclib`, `letras`), or a country code in upper case (`BRA`).
- **When.** A date `YYYYMMDD` for a download or a build. A run id `YYYYMMDDTHHMMSSZ` for a collection run or a scoring run. This folder is the version folder.
- A version folder is write-once. It holds one `_MANIFEST.json`, and the manifest is the last file that the writer writes. A folder without a manifest is incomplete, and no reader uses it. A correction is a new version folder.
- A date never stands above a country. A folder name never holds a campaign name, the name of a person or a retry counter.
- Source and year are columns, never folders.

## The tree

```
raw/<source>/<YYYYMMDD>/                     files as received: bulk dumps, site archives, economic data
raw/manual_review/<ISO3>/<YYYYMMDD>/         review workbooks from a person
clean/dumps/<source>/<YYYYMMDD>/             one lyric dump in the uniform format: songs.parquet, artist_names.parquet
clean/catalog/<source>/<YYYYMMDD>/           parsed MusicBrainz and Discogs tables
clean/countries/<YYYYMMDD>/                  country-year table of economic and social variables: countries.parquet
lyrics/<ISO3>/songs/<run id>/                full state of the country after that run: artists.parquet, songs.parquet, links.parquet
lyrics/<ISO3>/scores/<run id>/               topic scores of one scoring run: topics.parquet, provenance.parquet
analysis/<YYYYMMDD>/                         the release: country_year.parquet, songs.parquet
```

Each version folder has one function in `src/songs/common/paths.py`. No other module builds these paths from strings. Each function checks its arguments: a country code is three capital letters, a source is a lower-case key, a date is a calendar date, and a run id is a UTC second.

| Version folder | Function | Newest complete folder |
| --- | --- | --- |
| `raw/<source>/<YYYYMMDD>/` | `raw_dir(data, source, day)` | `latest_raw_dir(data, source)` |
| `raw/manual_review/<ISO3>/<YYYYMMDD>/` | `raw_manual_review_dir(data, iso3, day)` | `latest_raw_manual_review_dir(data, iso3)` |
| `clean/dumps/<source>/<YYYYMMDD>/` | `clean_dump_dir(data, source, day)` | `latest_clean_dump_dir(data, source)` |
| `clean/catalog/<source>/<YYYYMMDD>/` | `clean_catalog_dir(data, source, day)` | `latest_clean_catalog_dir(data, source)` |
| `clean/countries/<YYYYMMDD>/` | `clean_countries_dir(data, day)` | `latest_clean_countries_dir(data)` |
| `lyrics/<ISO3>/songs/<run id>/` | `country_songs_dir(data, iso3, run_id)` | `latest_country_songs_dir(data, iso3)` |
| `lyrics/<ISO3>/scores/<run id>/` | `country_scores_dir(data, iso3, run_id)` | `latest_country_scores_dir(data, iso3)` |
| `analysis/<YYYYMMDD>/` | `analysis_dir(data, day)` | `latest_analysis_dir(data)` |

A `latest_*` function returns the newest folder that has a manifest, or nothing when no such folder exists.

## Example: one country

```
lyrics/BRA/
  songs/
    20261105T140000Z/        BRA after the first run
      artists.parquet
      songs.parquet
      links.parquet
      _MANIFEST.json
    20270203T083000Z/        BRA after an update: the full tables again
      artists.parquet
      songs.parquet
      links.parquet
      _MANIFEST.json
  scores/
    20261201T120000Z/
      topics.parquet
      provenance.parquet
      _MANIFEST.json
```

## How a country update works

1. The collection run reads the newest folder under `lyrics/<ISO3>/songs/` that has a manifest.
2. The run adds rows, or replaces rows that have the same key.
3. The run writes the full tables to a new folder. The name of the folder is the run id, and it is the run id in the run record (`countries/<ISO3>/runs/`).
4. The run writes the manifest last. The manifest names the earlier folder as an input.

The newest folder is always the current state of the country. An earlier folder is never changed.

There is no file per artist in saved data. A collector can keep one file per artist in a local working folder (`tmp/` or `staging/`), to continue after a stop. That folder is never uploaded.

## What is never saved

These folders are not versions and do not go to the bucket: `cache/`, `tmp/`, `staging/`, `interim/`.

## Upload and download

A complete version folder goes to the bucket under the same path, with the prefix `data/`. Three commands move and check folders. Each command takes the version folder relative to the data folder, for example `uv run songs data upload clean/countries/20261114/`. The bucket name comes from `SONGS_GCS_BUCKET`. The code is in `src/songs/common/storage.py`. It calls the `gcloud` program, as it is signed in.

- `songs data upload <version folder>` copies a local folder to the bucket. The folder must have a valid manifest that lists each file in it, and each file must have the SHA-256 of the manifest. The bucket must have object versioning on. The command refuses a folder that has a manifest in the bucket, and an object of the folder that has other bytes. It writes nothing when one of these checks fails. It uploads the manifest last. A second run continues: it keeps each object that has the same size, MD5 and `sha256`. The command prints one line for each object: name, bytes, generation.
- `songs data download <version folder>` copies a folder from the bucket to the data folder. The folder in the bucket must pass the check below. The command refuses a local folder that has a manifest, and it never replaces a local file that has other bytes. Each file goes to `tmp/` first and moves into place after its SHA-256 matches the manifest. The manifest goes last.
- `songs data check <version folder>` compares a folder in the bucket with its manifest. It reads the listing and the manifest, and no data file. Each file of the manifest must have an object with the same size, an MD5, and the same `sha256` metadata. The folder must hold no other object.

Each upload creates an object with the precondition "the object does not exist" (`--if-generation-match=0`), the MD5 of the file (`--content-md5`), and the custom metadata `sha256`: the SHA-256 of the file, 64 hex characters. The bucket refuses an upload whose bytes do not have that MD5. No command deletes, moves or replaces an object. Code that uploads a file that is not in a version folder uses `storage.upload_file`, which makes the same checks, and calls `storage.require_versioning` before its first upload.

## The manifest

Every version folder holds one `_MANIFEST.json`. All kinds of folder use one format. The file is JSON with sorted keys, an indent of 2 spaces, UTF-8, and a final newline, like a run record. The code is in `src/songs/common/manifests.py`.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | `1` |
| `kind` | string | One value from the table of kinds below |
| `path` | string | The version folder, relative to the data folder, with forward slashes and a final slash. Never a scheme, a bucket name or a drive letter |
| `created_utc` | string | When the folder was completed |
| `code_commit` | string | Commit of the code that wrote the folder |
| `country_iso3` | string or null | Country, for the kinds that have one |
| `source` | string or null | Source key, for the kinds that have one |
| `run_id` | string or null | Run id, for the kinds that a run writes |
| `inputs` | list of string | The version folders or files that this folder was built from, as paths relative to the data folder. Empty for a download |
| `origin` | object or null | For `raw` only: `url`, `retrieved_utc`, `license`. Each one can be null |
| `files` | list of object | One entry for each file in the folder except the manifest: `path` (relative to the folder), `bytes`, `sha256`, `rows`. `rows` is the row count of a Parquet file, and null for every other file |
| `counts` | object | Small whole numbers that describe the content, by name (for example `songs`, `artists`, `songs_added`). Can be empty |
| `notes` | string | Anything that a later reader needs. No lyric text, no personal details |

| Kind | Path | Must be set | Files |
| --- | --- | --- | --- |
| `raw` | `raw/<source>/<YYYYMMDD>/` | `source`, `origin` | As received |
| `raw_manual_review` | `raw/manual_review/<ISO3>/<YYYYMMDD>/` | `country_iso3` | The workbook |
| `clean_dump` | `clean/dumps/<source>/<YYYYMMDD>/` | `source`, `inputs` | `songs.parquet`, `artist_names.parquet` |
| `clean_catalog` | `clean/catalog/<source>/<YYYYMMDD>/` | `source`, `inputs` | Tables of the catalog |
| `clean_countries` | `clean/countries/<YYYYMMDD>/` | `inputs` | `countries.parquet` |
| `country_songs` | `lyrics/<ISO3>/songs/<run id>/` | `country_iso3`, `run_id`, `inputs` | `artists.parquet`, `songs.parquet`, `links.parquet` |
| `country_scores` | `lyrics/<ISO3>/scores/<run id>/` | `country_iso3`, `run_id`, `inputs` | `topics.parquet`, `provenance.parquet` |
| `analysis` | `analysis/<YYYYMMDD>/` | `inputs` | `country_year.parquet`, `songs.parquet` |

`write_manifest` lists every file in the folder and computes its size, its SHA-256 and its row count. It refuses a folder that has a manifest. `read_manifest` checks these rules:

- `kind` is one of the kinds in the table.
- `path` is the path that the kind gives for the country, the source, the date or the run id of the manifest.
- The fields in "Must be set" are set. `country_iso3`, `source`, `run_id` and `origin` are null when the kind does not name them.
- Each `sha256` is 64 hex characters.
- For a kind with a fixed file list, `files` matches the list.
- `path` and `inputs` hold only paths relative to the data folder.

The run record says what a run collected. The manifest says which files exist and what they hold. Neither holds the other. The manifest of a `country_songs` folder joins to its run record by `country_iso3` and `run_id`.

## Tables in general

All tables are Parquet with zstd compression. Text is UTF-8. A time is a UTC string `YYYY-MM-DDTHH:MM:SSZ`, as `run_records.utc_now()` writes it. "Required" means that no row is null.

The types are `string`, `boolean`, `int16`, `int32` and `float64`.

A writer calls `schemas.write_table(table, relation, folder)`. The function checks the table against its schema before it writes. The check names every problem: a missing column, an extra column, a wrong type, a null in a required column, and a duplicate key. A reader calls `schemas.read_table(table, folder)`, which makes the same check.

## Tables of a country

<!-- generated:country_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `artists.parquet`: one row per artist of the country

Folder: `lyrics/<ISO3>/songs/<run id>/`. Key: `artist_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder, upper case |
| `artist_id` | string | yes | Project id of the artist. For an artist with a Discogs id it is `uuid5(NAMESPACE_URL, "https://www.discogs.com/artist/<id>")`, the same value as in the old data. For an artist with no Discogs id it is `uuid5(NAMESPACE_URL, "https://research-songs.invalid/artist/<ISO3>/<artist_name>")` |
| `artist_name` | string | yes | Name as the roster has it |
| `discogs_artist_id` | string | no | Discogs id |
| `country_tag` | string | no | Why the artist belongs to the country, as recorded (the old `country_basis`, or the "Nationality / country in our file" value of a review workbook) |
| `attempted` | boolean | yes | True when a collection run tried this artist |
| `last_attempt_utc` | string | no | Time of the last attempt |
| `songs` | int32 | yes | Number of rows of this artist in `songs.parquet` of the same folder |

### `songs.parquet`: one row per song with lyrics

Folder: `lyrics/<ISO3>/songs/<run id>/`. Key: `song_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Id of the song row, unique in the country |
| `artist_id` | string | yes | Joins to `artists.parquet` |
| `artist_name` | string | yes | Name of the artist as collected |
| `song_name` | string | no | Title as the source prints it. The old lyric files have no title column; an importer takes it from the links |
| `title_key` | string | no | Normalized title used in matching (the old `canonical_title_key`) |
| `source` | string | yes | Where the lyrics come from: a source key (`genius`, `letras`, `lrclib`), or the host of the page for a hand-collected song |
| `source_song_id` | string | no | Id of the song at the source |
| `song_url` | string | no | Page of the song at the source |
| `lyrics` | string | yes | The lyric text |
| `lyrics_sha256` | string | yes | SHA-256 of `lyrics` as UTF-8, hex |
| `language` | string | no | Language as recorded; no fixed code list yet |
| `year` | int32 | no | Release year used in analysis |
| `year_source` | string | no | Where `year` comes from (`discogs`, `genius`, `musicbrainz`, `manual_review`, ...) |
| `year_basis` | string | no | How sure the year is (for example `source_printed_unverified`) |
| `first_release_year` | int32 | no | Year of first release when the row is a re-release |
| `canonical_song_id` | string | no | `song_id` of the row that represents this song when it is a duplicate or a re-release |
| `duplicate_decision` | string | no | Decision of the duplicate check (for example `suppress_duplicate`) |
| `quality_status` | string | no | Decision of the quality check (for example `quarantine`) |
| `route` | string | yes | Route of the run that added the row; one of `ROUTES` in `run_records.py` |
| `run_id` | string | yes | Run that added or last replaced the row |
| `collected_utc` | string | no | When the lyrics were fetched or imported |

### `links.parquet`: one row per match between a catalog track and a song

Folder: `lyrics/<ISO3>/songs/<run id>/`. Key: `song_id`, `discogs_release_id`, `discogs_track_index`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Joins to `songs.parquet` |
| `artist_id` | string | yes | Joins to `artists.parquet` |
| `discogs_release_id` | string | yes | Release on the catalog side |
| `discogs_track_index` | string | yes | Position of the track in the release |
| `discogs_title` | string | no | Track title in the catalog |
| `source` | string | yes | Same meaning as in `songs.parquet` |
| `source_song_id` | string | no | Id of the song at the source |
| `source_title` | string | no | Title at the source (the old `provider_title`) |
| `song_url` | string | no | Page of the song at the source |
| `match_method` | string | no | How the match was made |
| `match_score` | float64 | no | Strength of the match; the old files store it as text |
| `run_id` | string | yes | Run that added the link |

<!-- generated:country_tables:end -->

`songs.parquet` of a country holds lyric text. It never goes to Git.

A link says: this Discogs track is this song from this source. One song can have many links. A hand-collected song has no catalog track, so it has no link.

The rule for eligible songs (decision 0007) is not built yet. It will read `duplicate_decision` and `quality_status`; that is why these columns stay.

### Columns of the old data that are not kept

The old lyric files have up to 38 columns. These are dropped on purpose: `song_discogs_id`, `lyrics_id`, `linked_song_count`, `tag_re_release`, `re_release_type`, `re_release_evidence`, `re_release_confidence`, `check`, `notes`, `snapshot_source_date`, `snapshot_source_filename`, `script`, `discogs_year`, `discogs_year_1`, `recording_basis`, `source_release_year`, `duplicate_group_id`, `representative_song_id`, `duplicate_type`, `quality_reason`, `quality_check_id`.

These are renamed: the old `provider` becomes `source`, `provider_song_id` becomes `source_song_id`, and `scraped_at_utc` becomes `collected_utc`. The old `lyrics_text_hash` is replaced by `lyrics_sha256`, which is computed again.

### How the import of a review workbook fills the tables

`songs lyrics import-review <ISO3>` adds the songs that a person added to a review workbook (`src/songs/stage_00_ingest/review_workbooks.py`).

| Value in the workbook | Place in the tables |
| --- | --- |
| Artist, song title, year, language, lyrics, source link | `artist_name`, `song_name`, `year`, `language`, `lyrics`, `song_url` in `songs.parquet` |
| Host of the source link | `source` in `songs.parquet` |
| Discogs artist ID | `discogs_artist_id` in `artists.parquet`; it also decides `artist_id` |
| Nationality / country in our file | `country_tag` in `artists.parquet` |

- `route` and `year_source` are `manual_review`. `song_id` is `mr_` and the first 20 hex characters of the SHA-256 of the source link.
- `run_id` is the run id of the import, and `collected_utc` is the start of the import.
- A reviewed song replaces an earlier row that has the same `song_id`. The run record counts only the songs that are new to the country (`rows_added`). The manifest counts both (`songs_added`, `songs_replaced`).
- The artist of a reviewed song has `attempted` true, and `last_attempt_utc` is the start of the import.
- Two names with one Discogs id are one row in `artists.parquet`. The row keeps the name that the country already has, or the first name in the workbook. `songs.parquet` keeps each name as collected.
- `title_key` is empty, because the shared function that makes the key does not exist yet.
- When the country has no earlier folder, the new folder holds only the reviewed songs, and `links.parquet` has no rows.

## Country-year table

`clean/countries/<YYYYMMDD>/countries.parquet` has one row per country and year. `songs panel countries` builds it (`src/songs/stage_50_analysis/countries_panel.py`). The columns are `COUNTRY_COLUMNS` in that module. [Data sources](data_sources.md) says where each variable comes from. The manifest names every input file that the build read.

## Score tables (planned)

No code writes these tables yet. Only a person starts a scoring run.

<!-- generated:score_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `topics.parquet`: one row per scored song

Folder: `lyrics/<ISO3>/scores/<run id>/`. Key: `song_id`. Planned: no code writes this table yet.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Joins to `songs.parquet` of the country |
| `lyrics_sha256` | string | yes | SHA-256 of the lyric text that was scored |
| `T01` to `T38` | int16 | no | One column per topic id: the score of the song on that topic. Null when the run gave no score. The names come from `songs.stage_30_topics.topic_ids`; [topics](topics.md) lists them |

### `provenance.parquet`: one row per scored song

Folder: `lyrics/<ISO3>/scores/<run id>/`. Key: `song_id`. Planned: no code writes this table yet.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Joins to `songs.parquet` of the country |
| `lyrics_sha256` | string | yes | SHA-256 of the lyric text that was scored |
| `prompt_sha256` | string | yes | SHA-256 of the prompt that scored the song |
| `model` | string | yes | Model that scored the song |
| `text_kind` | string | yes | What the model says the text is |
| `status` | string | yes | Result of the scoring request |
| `scored_utc` | string | no | When the song was scored |

<!-- generated:score_tables:end -->

The old data also has value scores. This project scores topics only (decision 0005).

## Analysis release (planned)

No code writes these files yet.

- `analysis/<YYYYMMDD>/country_year.parquet` will have one row per country and year: the economic and social variables of the country-year table, the region, the number of songs, the number of artists, and the mean score of each topic.
- `analysis/<YYYYMMDD>/songs.parquet` will have one row per eligible song: country, year, artist, source, and the score of each topic. It will hold no lyric text.

## Clean dumps (planned)

A dump is a source that the project holds whole and searches by artist and title: the lyric websites, Letras, LRCLIB and Genius. MusicBrainz and Discogs are catalogs, not dumps, because they hold no lyrics.

In the old data, each dump has its own shape. The uniform format is 2 tables per dump, always both, always these columns. The date of the folder is the date of the build. The manifest names the `raw/` folder that the dump was built from. No code builds a dump in this format yet.

<!-- generated:dump_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `songs.parquet`: one row per song and credited performer

Folder: `clean/dumps/<source>/<YYYYMMDD>/`. Key: `source_song_id`, `credit_position`. Planned: no code writes this table yet.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `source` | string | yes | Source key, the same in every row |
| `source_song_id` | string | yes | Id of the song at the source. When the source has none, the first 20 hex characters of the SHA-256 of `song_url` |
| `song_url` | string | no | Page of the song. Null for LRCLIB and Genius rows that have no page |
| `artist_name` | string | yes | Name of the performer as the source prints it |
| `source_artist_id` | string | no | Id or key of the artist at the source; joins to `artist_names.parquet` |
| `credit_position` | int32 | yes | 1 for the first credited performer, 2 for the next |
| `song_name` | string | yes | Title as the source prints it |
| `lyrics` | string | yes | The lyric text |
| `lyrics_sha256` | string | yes | SHA-256 of `lyrics` as UTF-8, hex |
| `language` | string | no | Language as the source states it |
| `year` | int32 | no | Release year as the source states it, when it is a plausible year (`songs.common.years.is_admissible_year`) |
| `album` | string | no | Album name |
| `fetched_utc` | string | no | When the page or the record was fetched |
| `raw_ref` | string | no | Where the raw page is under `raw/`, relative to the data folder |

### `artist_names.parquet`: one row per name of an artist at the source

Folder: `clean/dumps/<source>/<YYYYMMDD>/`. Key: `source_artist_id`, `artist_name`. Planned: no code writes this table yet.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `source` | string | yes | Source key |
| `source_artist_id` | string | yes | Id or key of the artist at the source |
| `artist_name` | string | yes | One name of the artist |
| `name_type` | string | yes | `primary` or `alias` |
| `artist_url` | string | no | Page of the artist |

<!-- generated:dump_tables:end -->

`songs.parquet` of a dump holds only rows with real lyric text: no translations, no empty pages, no error pages. For a source with no artist table, build `artist_names.parquet` from the distinct names in `songs.parquet`, with `source_artist_id` equal to the name.

### Rules for a dump

- A dump stores no normalized name key and no normalized title key. Matching code computes keys with one shared function, so a change of the normalization does not need a new build of every dump.
- Crawl state is not clean data. Queues, attempts, HTTP status, parser versions, receipts and logs stay in `raw/`.
- A source that is held back from matching is a list in tracked code or in `resources/`, with the reason. It is not a missing dump.
- `year` and `language` are null for most rows of Letras, AAMA, Fnanen, Kugeci and the text-only sources. That is correct. Do not invent values.

### Where each uniform column comes from

This table is guidance for the builder of the dumps. It gives the column of each old shape that holds the value.

| Uniform column | Site snapshot family | Letras | Stixoi | Kugeci | AAMA, Fnanen | Genius | LRCLIB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `source_song_id` | `provider_song_id` | `source_song_key` | `provider_song_id` | `provider_song_id` | `provider_song_id` | `genius_song_id` | `track_id` |
| `song_url` | `song_url` | `song_url` | `provider_url` | `song_url` in the song index | `url` | none | none |
| `artist_name` | `artist_name`, performer credits only | `artist_name` | through `artist_songs` | labels in a JSON list | through `relations` or the artist heading | `artist_name` | `artist_name` |
| `song_name` | `song_name` | `song_name` | `title` | `provider_title` | `title` | `song_name` | `name` |
| `lyrics` | `lyrics`, rows with `text_kind` = `lyrics` | `lyrics` | `lyrics` | `lyrics_text` | `lyrics` | `lyrics` | `plain_lyrics` |
| `language` | `language_label` | none | `language` | none | none | `language_cld3` | none |
| `year` | `release_year_raw` | none | `release_year` | none | none | `year` | none |
| `album` | `album_name` | none | through `song_albums` | none | none | none | `album_name` |
| `fetched_utc` | `retrieved_at_utc` | `retrieved_at_utc` | `parsed_at_utc` | `last_attempt_at_utc` | `fetched_at` | none | `updated_at` |

## Known gaps

These things do not follow the layout yet. Each one needs its own task. Do not copy them in new code.

- **Raw folders with no dated folder, or with the date inside the name.** These `raw_path` values in `resources/data_sources.toml`: `raw/discogs/`, `raw/crisis_review_20261109/`, `raw/crisis_review_20261110/`, `raw/un_wpp/2024/`, `raw/unsd_divorces/undata_pop_table16/`. The two `crisis_review` folders also have a campaign name, and they hold the files of 7 sources.
- **A raw path in the old order.** `musicbrainz/clean/20260624-001001/` is the `raw_path` of the MusicBrainz catalog. Its place in the layout is `clean/catalog/musicbrainz/20260624/`.
- **Undated inputs of the country-year table.** The `CLEAN_FILES` values in `countries_panel.py` are files from the old pipeline: `extraction/countries.parquet`, `clean/analysis_sample.parquet`, `clean/country_year_song_counts.parquet`, `clean/country_year_artist_counts.parquet`, `clean/populism.parquet`. The layout has no `extraction` layer.
- **No manifest in `raw/`.** No command writes a manifest for a `raw` folder or for a `raw_manual_review` folder. A person puts a review workbook in its folder, so the import of a workbook does not ask for a manifest there.
- **Earlier builds have no manifest.** A `clean/countries/<YYYYMMDD>/` folder that was built before this standard has no manifest, so `latest_clean_countries_dir` does not return it. Build the table again to get a folder with a manifest.
- **Earlier imports of a review workbook.** Before this standard, the import wrote `lyrics/<ISO3>/manual_review/<run id>/songs.parquet`. A folder of that form is not in the layout, and no code reads it.
- **`countries.parquet` has no schema in `schemas.py`.** Its column list is in `countries_panel.py`, and the build checks the list.
- **Tiers outside the layout.** `DataLayout` in `paths.py` still names `extraction`, `processed`, `restricted`, `manifests`, `rankings` and `matching`. The layout has no such layers.
- **Old data.** All data of the old repository and everything in the bucket today has the old layout. Nothing there has the new layout yet.
