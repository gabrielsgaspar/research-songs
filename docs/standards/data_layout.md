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
clean/quality/song_quarantine/<YYYYMMDD>/    songs that the old quality checks put in quarantine: song_quarantine.csv
clean/quality/artist_country/<YYYYMMDD>/     roster artists that belong to another country: artist_country.parquet
clean/quality/text_copies/<YYYYMMDD>/        campaign songs whose text another song of the country has: text_copies.parquet
clean/quality/uncredited_songs/<YYYYMMDD>/   campaign songs whose dump credit does not name their artist: uncredited_songs.parquet
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
| `clean/quality/song_quarantine/<YYYYMMDD>/` | `clean_song_quarantine_dir(data, day)` | `latest_clean_song_quarantine_dir(data)` |
| `clean/quality/artist_country/<YYYYMMDD>/` | `clean_artist_country_dir(data, day)` | `latest_clean_artist_country_dir(data)` |
| `clean/quality/text_copies/<YYYYMMDD>/` | `clean_text_copies_dir(data, day)` | `latest_clean_text_copies_dir(data)` |
| `clean/quality/uncredited_songs/<YYYYMMDD>/` | `clean_uncredited_songs_dir(data, day)` | `latest_clean_uncredited_songs_dir(data)` |
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

`cache/dump_keys/<source>/<YYYYMMDD>/<hash>/` holds the key tables of one dump. The match builds them one time for each dump. The folder name `<hash>` comes from the key code, so a change of the key code builds the tables again in a new folder. `cache/discogs_keys/<source>/<YYYYMMDD>/<hash>/` holds the name keys of the Discogs artists, built the same way. These tables are never uploaded.

## Upload and download

A complete version folder goes to the bucket under the same path, with the prefix `data/`. Three commands move and check one folder. Each of them takes the version folder relative to the data folder, for example `uv run songs data upload clean/countries/20261114/`. The bucket name comes from `SONGS_GCS_BUCKET`. The code is in `src/songs/common/storage.py`. It calls the `gcloud` program, as it is signed in.

- `songs data upload <version folder>` copies a local folder to the bucket. The folder must have a valid manifest that lists each file in it, and each file must have the SHA-256 of the manifest. The bucket must have object versioning on. The command refuses a folder that has a manifest in the bucket, and an object of the folder that has other bytes. It writes nothing when one of these checks fails. It uploads the manifest last. A second run continues: it keeps each object that has the same size, MD5 and `sha256`. The command prints one line for each object: name, bytes, generation.
- `songs data download <version folder>` copies a folder from the bucket to the data folder. The folder in the bucket must pass the check below. The command refuses a local folder that has a manifest, and it never replaces a local file that has other bytes. Each file goes to `tmp/` first and moves into place after its SHA-256 matches the manifest. The manifest goes last.
- `songs data check <version folder>` compares a folder in the bucket with its manifest. It reads the listing and the manifest, and no data file. Each file of the manifest must have an object with the same size, an MD5, and the same `sha256` metadata. The folder must hold no other object.
- `songs data pull <ISO3> ...` downloads the newest complete folders that a campaign for the countries needs. For each country it takes the songs folder, the scores folder and the dump of each lyric source of the country. Then it takes the Discogs catalog. The option `--no-catalog` leaves the catalog out (17 GB, about 2 hours). A folder that is complete on this disk is not downloaded again. The rules of `songs data download` hold.
- `songs lyrics publish <ISO3> ...` uploads the songs folders of the countries that the bucket lacks, oldest first. Before a folder, it uploads the inputs of its manifest that this disk holds and the bucket lacks. It checks each uploaded folder against its manifest. It does not upload a folder when one of its inputs is a version folder that is neither on this disk nor in the bucket, and it does not upload the folders that need that folder. It then exits with 1 after the other uploads. An input that is not a version folder of the data layout is only noted.
- `songs lyrics audit` compares the run records with the songs folders of the bucket. It prints each run record that wrote a songs folder with no complete folder in the bucket, and each complete songs folder with no run record. It exits with 1 when it finds one. It takes about 3 minutes.
- `songs data sync` prints a Markdown report of the complete local folders that the bucket lacks. It looks at these kinds: clean dumps, catalogs, the country-year table, the quarantine list, country songs, the table of artist countries, the table of text copies, the table of uncredited songs, country scores and the analysis release. With `--write`, it uploads them with the rules of `songs lyrics publish`, inputs first. Without `--write`, it uploads nothing. It uploads a songs folder only when `countries/<ISO3>/runs/` holds a run record with the same run id and the country has no open campaign. The report lists each folder that is left out, with the reason. The report also names the newest country-year table and the newest analysis release when they are stale, with the command that builds each one again. The country-year table is stale when a build would now read a file that its manifest does not name. The release is stale when an input has a newer complete folder, or when a country has songs or scores that are not an input. The command builds nothing, scores nothing and deletes nothing. It exits with 1 when a folder names an input that is neither on this disk nor in the bucket. The code is in `src/songs/common/sync.py`.

A weekly task in Windows Task Scheduler runs the sync. To register the task, run this command one time in PowerShell, in the folder of the repository:

```powershell
Register-ScheduledTask -TaskName "songs-data-sync" -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am) -Action (New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c if not exist reports mkdir reports & uv run songs data sync --write > reports\data_sync.md 2>&1" -WorkingDirectory $PWD.Path)
```

The task runs each Sunday at 03:00, as the user who registered it, while that user is signed in. Each run writes its report to `reports/data_sync.md` in place of the report of the week before. The folder `reports/` is local only. The task reads `SONGS_DATA_ROOT` and `SONGS_GCS_BUCKET` as each other command does.

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
| `clean_song_quarantine` | `clean/quality/song_quarantine/<YYYYMMDD>/` | `inputs` | `song_quarantine.csv` |
| `clean_artist_country` | `clean/quality/artist_country/<YYYYMMDD>/` | `inputs` | `artist_country.parquet` |
| `clean_text_copies` | `clean/quality/text_copies/<YYYYMMDD>/` | `inputs` | `text_copies.parquet` |
| `clean_uncredited_songs` | `clean/quality/uncredited_songs/<YYYYMMDD>/` | `inputs` | `uncredited_songs.parquet` |
| `country_songs` | `lyrics/<ISO3>/songs/<run id>/` | `country_iso3`, `run_id`, `inputs` | `artists.parquet`, `songs.parquet`, `links.parquet` |
| `country_scores` | `lyrics/<ISO3>/scores/<run id>/` | `country_iso3`, `run_id`, `inputs` | `topics.parquet`, `provenance.parquet` |
| `analysis` | `analysis/<YYYYMMDD>/` | `inputs` | `country_year.parquet`, `songs.parquet` |

`write_manifest` lists every file in the folder and computes its size, its SHA-256 and its row count. A caller can add the entries of files that are in the bucket and no longer on the local disk (`uploaded_files`), such as the parts of a packed source. It refuses a folder that has a manifest. `read_manifest` checks these rules:

- `kind` is one of the kinds in the table.
- `path` is the path that the kind gives for the country, the source, the date or the run id of the manifest.
- The fields in "Must be set" are set. `country_iso3`, `source`, `run_id` and `origin` are null when the kind does not name them.
- Each `sha256` is 64 hex characters.
- For a kind with a fixed file list, `files` matches the list.
- `path` and `inputs` hold only paths relative to the data folder.

The run record says what a run collected. The manifest says which files exist and what they hold. Neither holds the other. The manifest of a `country_songs` folder joins to its run record by `country_iso3` and `run_id`.

## Tables in general

All tables are Parquet with zstd compression. Text is UTF-8. A time is a UTC string `YYYY-MM-DDTHH:MM:SSZ`, as `run_records.utc_now()` writes it. "Required" means that no row is null.

The types are `string`, `boolean`, `int16`, `int32`, `int64` and `float64`.

A writer calls `schemas.write_table(table, relation, folder)`. The function checks the table against its schema before it writes. The check names every problem: a missing column, an extra column, a wrong type, a null in a required column, and a duplicate key. A reader calls `schemas.read_table(table, folder)`, which makes the same check.

## Packed raw sources

Files in `raw/` stay as received, with one exception. A source that arrived as many loose files, such as the pages of a website with one file for each page, is packed into `tar.gz` parts. Millions of small objects are slow to list, to read and to prove; a few large parts are not. A file that arrived as one large file (a dump, an archive, a Parquet table) is never packed. It stays as received, and it can be in the same version folder as the parts.

A packed `raw/<source>/<YYYYMMDD>/` folder holds these files:

- `pages-00001.tar.gz`, `pages-00002.tar.gz`, and so on: the parts, numbered from 1, with 5 digits and no gap. Each member of a part is one file, with its bytes as received. The member name is the path of the file relative to the folder that was packed, with forward slashes. For the old data, that folder is the old data folder, so a member name is the old path.
- `members.parquet`: one row for each member, with its size and its SHA-256. It holds no file content. A copy of a local file is proved by a member with the same size and the same SHA-256.
- `_MANIFEST.json`: the kind is `raw`. The manifest lists the parts and `members.parquet`. Its counts are `parts`, `members` and `skipped`.

The packer is `src/songs/common/tar_parts.py`. It follows these rules:

- The order is stable: in each folder, the files by name, then the subfolders by name. Symbolic links are not packed.
- A part closes after the file that makes its source bytes reach the limit (1 GiB by default). A file that is larger than the limit makes a part of its own.
- The packer writes one part at a time to a work folder outside the version folder, for example under `staging/`. It gives the part to the caller before it starts the next part. The caller uploads the part and removes it, so the peak disk use is one part.
- A file that changes or disappears while it is read is not packed: its size or its change time after the read differs from before the read. The record of its part names the file, and the manifest counts it as `skipped`.
- The headers of a part are fixed (gzip time 0, no gzip file name, tar format PAX, mode 644, owner 0), so the same files give the same parts. A second run with the same input makes the same parts in the same order, and skips the parts that the caller names as done. When the files planned for a done part changed, the packer stops. Then pack into a new version folder.
- `verify_part` reads a local part as a stream. `verify_stream` reads any stream, such as a download from the bucket. Both compare each member with its row in `members.parquet`: the name, the bytes and the SHA-256.
- `tar_parts.write_manifest` writes the manifest after every part is in the bucket. It lists the recorded size and SHA-256 of each part, because the parts are no longer on the local disk. It refuses parts that do not agree with `members.parquet`.

<!-- generated:raw_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `members.parquet`: one row per file in the parts of a packed source

Folder: `raw/<source>/<YYYYMMDD>/`. Key: `member`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `part` | string | yes | The part that holds the file: `pages-00001.tar.gz` |
| `member` | string | yes | Name of the file in the part: its path as received, with forward slashes |
| `bytes` | int64 | yes | Size of the file |
| `sha256` | string | yes | SHA-256 of the bytes of the file, hex |
| `modified_utc` | string | yes | Last change of the source file when it was packed |

<!-- generated:raw_tables:end -->

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
| `lyrics_text_hash` | string | no | Hash by which the lyric-hash lists of the rule for eligible songs name the text (`songs.common.lyric_hash`): the hash that the old files store, or the SHA-256 of the text after whitespace normalization. Empty when the text is blank |
| `language` | string | no | Language as recorded; no fixed code list yet |
| `year` | int32 | no | Release year used in analysis |
| `year_source` | string | no | Where `year` comes from (`discogs`, `genius`, `musicbrainz`, `manual_review`, ...) |
| `year_basis` | string | no | How sure the year is (for example `source_printed_unverified`) |
| `first_release_year` | int32 | no | Year of first release when the row is a re-release |
| `re_release` | boolean | no | Verdict of the re-release check: true when the row is a re-release (the old `tag_re_release`). Empty when no check ran |
| `canonical_song_id` | string | no | `song_id` of the row that represents this song when it is a duplicate or a re-release |
| `duplicate_decision` | string | no | Decision of the duplicate check (for example `suppress_duplicate`) |
| `quality_status` | string | no | Decision of the quality check (for example `quarantine`) |
| `route` | string | yes | Route of the run that added the row; one of `ROUTES` in `run_records.py` |
| `run_id` | string | yes | Run that added or last replaced the row |
| `collected_utc` | string | no | When the lyrics were fetched or imported |

### `links.parquet`: one row per link from a song to a source page

Folder: `lyrics/<ISO3>/songs/<run id>/`. Key: `song_id`, `discogs_release_id`, `discogs_track_index`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Joins to `songs.parquet` |
| `artist_id` | string | yes | Joins to `artists.parquet` |
| `discogs_release_id` | string | no | Release on the catalog side. Empty when the link has no catalog track |
| `discogs_track_index` | string | no | Position of the track in the release. Empty when the link has no catalog track |
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

A link records the source page of a song. `discogs_release_id` and `discogs_track_index` name the catalog track when the link has one. Both columns are empty when the link has no catalog track, and the row stays. One song can have many links. The key includes those two columns, so one song has at most one link with both of them empty. The import of a review workbook writes songs and no link rows.

The rule for eligible songs (decision 0007) reads `duplicate_decision`, `quality_status`, `canonical_song_id`, `re_release` and `lyrics_text_hash`; that is why these columns stay. The section "Analysis release" gives the rule.

### Columns of the old data that are not kept

The old lyric files have up to 38 columns. These are dropped on purpose: `song_discogs_id`, `lyrics_id`, `linked_song_count`, `re_release_type`, `re_release_evidence`, `re_release_confidence`, `check`, `notes`, `snapshot_source_date`, `snapshot_source_filename`, `script`, `discogs_year`, `discogs_year_1`, `recording_basis`, `source_release_year`, `duplicate_group_id`, `representative_song_id`, `duplicate_type`, `quality_reason`, `quality_check_id`.

These are renamed: the old `provider` becomes `source`, `tag_re_release` becomes `re_release`, `provider_song_id` becomes `source_song_id`, and `scraped_at_utc` becomes `collected_utc`. `lyrics_sha256` is computed again from the text. The old `lyrics_text_hash` stays as it is, because the lyric-hash lists name texts by it; a row with no old hash gets the hash of `songs.common.lyric_hash`.

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

### How the import of the old layout fills the tables

`songs lyrics import-old <ISO3>` writes the state of a country from the files of the old pipeline (`src/songs/stage_00_ingest/old_layout.py`). The old data folder is an argument (`--old-data`) or the environment variable `SONGS_OLD_DATA_ROOT`. The command only reads it. It is not the data folder of this layout.

| Old file, relative to `lyrics/<iso3>/` in the old data folder | Place in the tables |
| --- | --- |
| `lyrics/*.parquet`, one file for each artist | `songs.parquet` |
| `lyrics_links/*.parquet`, one file for each artist | `links.parquet`, and `song_name` in `songs.parquet` |
| `artists.csv`, the roster | `artists.parquet` |
| `discogs_cache/artists.parquet` | `discogs_artist_id` in `artists.parquet` |

- **Songs.** `song_id`, `artist_id`, `artist_name`, `song_url`, `lyrics`, `year`, `year_source`, `year_basis`, `first_release_year`, `canonical_song_id`, `duplicate_decision` and `quality_status` keep their old values. The renamed columns are `source`, `source_song_id` and `collected_utc`. `lyrics_sha256` is computed again. The old files do not all have the same columns; a column that the files lack is empty.
- **Route.** Every imported row has the route `old_layout`. The old files do not record how a row was first collected, so the import does not guess a route. `run_id` is the run id of the import.
- **Title.** `song_name` is the `provider_title` of a link of the song: first a link to the page of the song, then the link with the highest `match_score`. A song with no link has no title. `title_key` and `language` are empty.
- **Time.** An old time is UTC text with the offset `+00:00`. The import writes it as a UTC second. A time with another offset, or text that is not a time, is left empty and counted (`songs_time_not_read`).
- **Artists.** `artist_id` is the old value. `artist_name` is the `name` of the roster, and `country_tag` is `country_basis`. `attempted` is true when the roster marks the artist as scraped or holds a time for it; that time is `last_attempt_utc`. The roster has no Discogs id. The import makes the artist id of each Discogs id in the Discogs cache of the country and joins on it; an artist that the cache does not hold has no `discogs_artist_id`. An artist with songs that the roster does not have gets a row with the name of its songs.
- **Two names with one id.** When an artist id appears again in the roster, the first row stays. `songs.parquet` keeps each name as collected.
- **Links.** `source_title` is the old `provider_title`. `match_score` becomes a number. `artist_id` is the artist of the song. A row with no Discogs release or no track position stays. `discogs_release_id` and `discogs_track_index` are empty, and the row still records the source page.
- **Rows that are dropped.** Only these rules drop a row, and the manifest counts each one. A song row: no `song_id`; no lyrics, or only blank text; no `provider`; no artist id, or no artist name in the row and in the roster; a `song_id` that a run with another route already holds; a `song_id` that appears again (the row with the newest time stays). A link row: a song that is not in `songs.parquet`; a key that appears again (the row with the highest `match_score` stays). A roster row: no artist id or no name; an artist id that appears again.
- **A second import.** The old pipeline still writes, so a country can be imported again. The command then needs `--reason`, and the reason goes to the run record. The new folder holds the old files as they are now, and the rows that a run with another route added to the earlier folder. The manifest names the earlier folder as an input, and counts the songs that are new (`songs_added`) and the songs that are gone (`songs_removed`).
- **Inputs.** The first input in the manifest is `lyrics/<iso3>/`, relative to the old data folder. The manifest also counts the old files that the import read (`old_lyric_files`, `old_link_files`).
- The import does not filter songs for analysis. `duplicate_decision` and `quality_status` stay as columns.

## Country-year table

`clean/countries/<YYYYMMDD>/countries.parquet` has one row per country and year. `songs panel countries` builds it (`src/songs/stage_50_analysis/countries_panel.py`). The columns are `COUNTRY_COLUMNS` in that module. [Data sources](data_sources.md) says where each variable comes from. The manifest names every input file that the build read.

The rows are the countries with a folder in `countries/`, less the old codes in `OLD_CODES`. `country_name` is the name in the World Bank income workbook (`income_group_world_bank`); a country that the workbook lacks has an empty name. `num_songs`, `num_artists` and the analysis tier come from the eligible songs: `eligible_songs.classify` over the newest complete `lyrics/<ISO3>/songs/<run id>/` folder of each country, counted by country and year with the same functions as the analysis release. A country with a complete songs folder has 0 songs in a year with no eligible song; a country with no such folder has empty counts. A country with no song row has no tier. `sample_tiers.assign` gives `analysis_tier` from the eligible songs by decade. `in_wvs`, `in_evs`, `discogs_artists_available` and `discogs_dump_date` have no source yet (`NO_SOURCE`): they are empty, and the build reports them absent. The manifest counts the songs read, the eligible songs, the eligible songs with no year, the songs left out for each reason, the countries of each tier and the countries with no name.

## Artist countries

Some rosters hold artists of other countries. `songs lyrics roster-check --write` writes `clean/quality/artist_country/<YYYYMMDD>/` (`src/songs/stage_10_clean/artist_country.py`). Without `--write`, the command only prints the counts. The table has one row for each roster artist with a Discogs id, from the newest songs folder of every country. No person checks a row.

The decision is `other_country` only when three conditions hold. Every other artist gets `keep`.

1. The first 160 characters of the Discogs profile state another country. A statement is a country word that describes a role noun within a few words ("Syrian traditional singer"), or a country word that follows "from" within 40 characters with no sentence break ("from Dublin, Ireland"). A word followed by "-born" or " born" is no statement. A country word before a role noun is no statement when "the" comes before it ("founded by the German composer"), because such a phrase describes another person. A country word that is in the name of the artist is no statement and no home word.
2. No word of a home country is anywhere in that text. A home country is the country itself, and each country whose Discogs release names are all release names of this country in `resources/lyrics/discogs_countries.csv`. For example, the USSR is a home of Ukraine. The Federal Republic of Germany is a home of the German Democratic Republic.
3. The artist has a release with a country, fewer than 20% of those releases are in a home release country, and the release country with the most releases is not a home release country.

The country words are in `resources/lyrics/country_words.csv`. A word in capitals or of three letters or fewer, such as `UK`, is matched with its case. Every other word is matched without case. A longer word wins over a shorter one. Some phrases hold a country word and name no country of an artist, such as "New Jersey". The rule makes them blank first (`IGNORED_PHRASES`).

The manifest names the Discogs catalog folder and the songs folder of each country that the rule read. It counts the roster artists read, the artists with a Discogs id, the artists with `other_country`, and the songs of those artists.

Two places read the newest complete folder. The rule for eligible songs leaves out a song of an artist with `other_country` for the country of the song, with the reason `artist_country` (section "Analysis release"). `songs lyrics import-dump` does not add a song of such an artist; it counts the song as `artist_other_country` in the run record and in the manifest, and the manifest notes name the folder. With no such folder, both work without the table.

## Text copies

A country can hold the same lyrics two or more times, from a second source with other punctuation or spacing. A campaign can add such a copy, and the old pipeline holds many: on 2026-11-24, 554,752 of the 4,295,956 older songs had the same `text_key` as another older song of the same country, and the duplicate checks of the old pipeline flagged only 51,443 of them. `songs lyrics copy-check --write` writes `clean/quality/text_copies/<YYYYMMDD>/` (`src/songs/stage_10_clean/text_copies.py`). Without `--write`, the command only prints the counts. It reads the newest complete songs folder of every country, one country at a time. No person checks a row.

The keys are those of `songs.common.lyric_hash`: the text in lower case with only its letters and digits, of any script. A kept text of fewer than 30 characters has no key. A song B is a text copy of a song A of the same country when one of two conditions holds:

1. `same_text`: A and B have the same `text_key`, for any two artists.
2. `same_artist_start`: A and B have the same `artist_id` and the same `start_key`, the key of the first 300 kept characters.

A song of any route can be a copy. The songs of one key are a group. One song represents the group, in this order:

1. A song that the rule for eligible songs lets in before a song that it leaves out for another reason than `text_copy` (for example an old duplicate flag, the song quarantine list or a year out of range). The check calls `classify` with no text copies, and reads its lists as `load_rule` does, so the data folder needs a song quarantine folder. A song left out that represents a group would leave out the whole text.
2. An older song before a campaign song (route `dump_name`). So a campaign song represents a group only when another rule leaves out every older song of the group.
3. Of the older songs, the song with the earliest year, and a song with no year last. An analysis by country and year cannot use a song with no year, and the year of a re-release or of a cover is later than the year of the first release.
4. The smallest `run_id`, then the smallest `song_id`.

Each other song of the group gets one row, with that song as `kept_song_id`. The reason is `same_text` when the song is not the first of its `same_text` group, else `same_artist_start`. The first song of a set of linked groups is never a copy, so each text keeps one song.

The folders of the data are write-once, so the table marks the copies and deletes nothing. The rule for eligible songs leaves out a song that the newest complete table lists, with the reason `text_copy` (section "Analysis release"). With no such folder, the rule leaves out no song for this reason. An import of a dump holds back a new copy before it enters (`held_text`, see `countries/README.md`). The manifest names the songs folder of each country that the rule read. It counts the songs read, the campaign songs, the songs whose text has no key, the copies by reason, and the copies that are campaign songs (`campaign_copies`).

## Uncredited songs

Until 2026-11-24, an import of a dump could give a song a roster artist that the song does not credit. A Genius artist id can hold the names of unrelated artists, and the match gave each song every name of its id. `songs lyrics credit-check --write` writes `clean/quality/uncredited_songs/<YYYYMMDD>/` (`src/songs/stage_10_clean/uncredited_songs.py`). Without `--write`, the command only prints the counts. It reads the campaign songs (route `dump_name`) of the newest complete songs folder of every country, and the newest complete dump of each of their sources. No person checks a row.

A song is credited when the `name_key` of its roster artist is one of the keys that the match now gives the song (`credited_keys` in `src/songs/stage_00_ingest/dump_match.py`): the key of a credited name, the key of its lead performer, or the key of another name of its artist id. An artist id with two or more primary names of different keys holds unrelated artists, so its other names do not count. Each other campaign song gets one row, with the first reason that fits:

1. `merged_artist_id`: a name of the artist id of the credit has the key, and the id holds unrelated artists.
2. `no_credit`: no credited name has the key, and no credited name starts with it.

A song with a credited name that starts with the key at a place where the match does not split it, such as "Crosby Stills Nash" for the roster artist "Crosby", gets no row. The manifest counts these songs as `credited_by_split`. On 2026-11-24 no campaign song had this class. The split of a joint credit ("A & B" gives A) also cuts some band names, but the Discogs title step removed those songs: in samples of 120 songs that entered through a split, all were right.

The rule for eligible songs leaves out a song that the newest complete table lists, with the reason `uncredited_song` (section "Analysis release"). With no such folder, the rule leaves out no song for this reason. A song that the newest dump of its source lacks is not checked; the manifest counts it as `not_in_dump`. The manifest names the songs folder of each country and the dump of each source that the rule read. It counts the campaign songs, the songs not in the dump, the credited songs (`credited`, `credited_by_split`), and the uncredited songs by reason.

<!-- generated:quality_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `artist_country.parquet`: one row per roster artist with a Discogs id

Folder: `clean/quality/artist_country/<YYYYMMDD>/`. Key: `country_iso3`, `artist_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the roster |
| `artist_id` | string | yes | Joins to `artists.parquet` of the country |
| `discogs_artist_id` | string | yes | Discogs id of the roster, or the id that `dump_match.discogs_ids` found by name |
| `stated_country` | string | yes | Country that the start of the Discogs profile states for the artist, as a code. Empty text when it states none |
| `home_word` | boolean | yes | True when the start of the profile holds a word of a home country |
| `releases` | int64 | yes | Releases that credit the artist and have a country |
| `releases_home` | int64 | yes | Those releases in a home release country |
| `top_release_country` | string | yes | Release country of Discogs with the most of those releases. Empty text when `releases` is 0 |
| `decision` | string | yes | `other_country` when the artist belongs to another country, or `keep` |

### `text_copies.parquet`: one row per song that is a text copy of another song of its country

Folder: `clean/quality/text_copies/<YYYYMMDD>/`. Key: `country_iso3`, `song_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the song |
| `song_id` | string | yes | The copy: a song of any route in `songs.parquet` of the country |
| `kept_song_id` | string | yes | The song of the same country that represents the group: a song that no other rule for eligible songs leaves out; then an older song before a song of the route `dump_name`; of the older songs, the earliest year, with no year last; then the smallest `run_id` and the smallest `song_id` |
| `reason` | string | yes | `same_text`: the same `text_key` as the kept song (`songs.common.lyric_hash`). `same_artist_start`: the same artist and the same `start_key` |

### `uncredited_songs.parquet`: one row per campaign song whose dump credit does not name its roster artist

Folder: `clean/quality/uncredited_songs/<YYYYMMDD>/`. Key: `country_iso3`, `song_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the song |
| `song_id` | string | yes | A song with the route `dump_name` in `songs.parquet` of the country |
| `reason` | string | yes | `merged_artist_id`: a name of the artist id of the credit has the key of the roster artist, and the id holds unrelated artists. `no_credit`: no credited name has that key or starts with it |

<!-- generated:quality_tables:end -->

## Score tables

Two commands write these tables: `songs lyrics import-scores <ISO3>` from the old topic scores, and `songs score collect <run id>` from a scoring run. Only a person starts a scoring run.

<!-- generated:score_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `topics.parquet`: one row per scored song

Folder: `lyrics/<ISO3>/scores/<run id>/`. Key: `song_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Joins to `songs.parquet` of the country |
| `lyrics_sha256` | string | yes | SHA-256 of the lyric text that was scored |
| `T01` to `T38` | int16 | no | One column per topic id: the score of the song on that topic. Null when the run gave no score. The names come from `songs.stage_30_topics.topic_ids`; [topics](topics.md) lists them |

### `provenance.parquet`: one row per scored song

Folder: `lyrics/<ISO3>/scores/<run id>/`. Key: `song_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country of the folder |
| `song_id` | string | yes | Joins to `songs.parquet` of the country |
| `lyrics_sha256` | string | yes | SHA-256 of the lyric text that was scored |
| `prompt_sha256` | string | yes | SHA-256 of the prompt that scored the song |
| `model` | string | yes | Model that scored the song |
| `text_kind` | string | yes | What the model says the text is |
| `status` | string | yes | Result of the scoring request: `complete`, or `reused` when `songs score prepare` copied the score of a song with the same text and decade |
| `scored_utc` | string | no | When the song was scored |

<!-- generated:score_tables:end -->

### How the import of the old scores fills the tables

`songs lyrics import-scores <ISO3>` reads the old topic scores of one country and writes `lyrics/<ISO3>/scores/<run id>/` (`src/songs/stage_30_topics/old_scores.py`). The old data folder is `--old-data` or the environment variable `SONGS_OLD_DATA_ROOT`. The command only reads that folder.

| Old file, under `lyrics/<iso3>/scores/` in the old data folder | Place in the tables |
| --- | --- |
| `topics.parquet`, columns `t1` to `t38` | `topics.parquet`, one column per topic id, in the order of `TOPIC_IDS` |
| `topic_provenance.parquet`, or `provenance.parquet` when that file is absent | `provenance.parquet` |

- A score joins a song on `song_id`. The manifest names the newest songs folder of the country that has a manifest.
- A score with no song in that folder stays. The manifest counts it as `scores_no_song`.
- `lyrics_sha256` is the value stored in the old provenance. The old scorer stored the SHA-256 of the lyric text that it scored. The command keeps that value.
- When the song is in the songs folder and the two hashes differ, the lyric text changed after the score. The command keeps the score and keeps the stored hash. The manifest counts the row as `scores_text_changed`.
- `prompt_sha256` is the old `instrument_sha256`: the identity of the prompt and model that `songs.stage_30_topics.scoring_prompt.PROMPT_SHA256` pins for the topics-only prompt. The old `prompt_sha256` is the SHA-256 of the prompt of one song, so the command does not keep it. The manifest counts a row whose `instrument_sha256` is not the pinned value as `scores_other_prompt`; for example, the old prompt that scored topics and values together.
- `model` and `text_kind` come from the provenance row. `status` is the old `measurement_status`. When a row has no value for one of these, no `instrument_sha256` or no `lyrics_sha256`, the command stops and writes no folder.
- `scored_utc` is empty. The old files have no time of the score.
- A topic cell that is empty stays empty. The old files leave every topic empty when the text is not song lyrics.
- The command reads neither `values.parquet` nor `value_flags.parquet`. This project keeps topic scores only.
- The command writes no collection run record. A score import is not a collection run.
- The first manifest input is `lyrics/<iso3>/scores/`, relative to the old data folder. The second input is the songs folder.

### How a scoring run fills the tables

A scoring run sends songs to the model and the prompt of `prompts/scoring/` through the Batch API (`src/songs/stage_30_topics/scoring_run.py`). It has three commands, and a fourth command shows the state of the scores.

- `songs score prepare <ISO3> ... --max-requests N` reads the newest songs folder and the newest scores folder of each country. It takes the songs that `eligible_songs.classify` lets in and that have no score from this prompt and model for their current `lyrics_sha256`. Songs of one country with the same `lyrics_sha256` and decade share one request. A song in a run that is not collected yet is not taken again. The command writes the batch file and prints the counts and a cost estimate in US dollars. It sends nothing.
- `--decade 1980s` takes only the songs of that decade. Repeat the option for more decades. The other songs with no score wait for a later run, and the plan counts them as `other_decade`. A song with no year belongs to no decade, so a run with `--decade` does not take it.
- The request of a song holds only its country, decade and lyric text. So `prepare` sends no request for a song when another song of the country with the same `lyrics_sha256` and decade has a score from this prompt and model. The decade is that of the scored song in the newest songs folder now. `prepare` copies that score with `status` `reused` and the `scored_utc` of the copied score. It writes a new folder `lyrics/<ISO3>/scores/<run id>/` for each country with a copied score: every score of the newest scores folder and the copied scores. The manifest counts `scores`, `scores_carried` and `scores_reused`. The plan counts the copied songs as `reused`. A score is never copied to a song of another country or decade, because its request would be different.
- `songs score status [<ISO3> ...]` counts the songs and the eligible songs of each country by the state of their score: `scored` (a score from this prompt and model for the current text), `other_prompt` (a score of the current text from another prompt or model), `text_changed` (a score of other text only) and `not_scored`. These four sum to the eligible songs. `in_open_run` counts the eligible songs with no current score that a run holds that is not collected. With `--write`, the command writes the counts of all countries to `docs/status/scoring.md`. It sends nothing and writes no data.
- `songs score submit <run id> --max-usd X` uploads the batch file and starts the batch. It stops when the estimate is above `--max-usd`, when the prompt changed after `prepare`, and when the run was submitted before. It asks the person to type the run id. The key is the environment variable `OPENAI_API_KEY`.
- `songs score collect <run id>` reads the answers when the batch has ended. It checks each answer against the answer format: the model, the field order, and a score from 0 to 100 for each topic, or `unknown` for each topic when the text is not song lyrics. It writes a new folder `lyrics/<ISO3>/scores/<run id>/` for each country with a valid answer. The folder holds every score of the newest scores folder, with the new scores in place of older scores of the same `song_id`. `status` is `complete` and `scored_utc` is the time of the collection.
- The manifest counts `scores` (rows written), `scores_carried` (rows from the earlier folder), `requests`, `answers`, the songs by `text_kind` (`songs_song_lyrics`, `songs_non_song`, `songs_uncertain`), and the requests with no valid answer by reason: `no_answer`, `request_error`, `http_error`, `not_completed`, `bad_answer`. A song with no valid answer gets no score, and the next `prepare` takes it again. The inputs are the songs folder that `prepare` read and the earlier scores folder.
- The working files of a run are in `staging/scoring/<run id>/`: the batch file (with lyric text), the request of each song, the plan, the batch ids, and the answers. They are never uploaded. `collected.json` marks a run as collected.
- The cost estimate counts about 4 bytes of request for each input token and 1,000 output tokens for each request, at the batch price, with no cache reads. It is an upper estimate.

The old data also has value scores. This project scores topics only (decision 0005).

## Analysis release

`songs analysis release` writes `analysis/<YYYYMMDD>/` (`src/songs/stage_50_analysis/release.py`). Every table and regression of the paper reads these files.

<!-- generated:analysis_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `country_year.parquet`: one row per country and year of the country-year table

Folder: `analysis/<YYYYMMDD>/`. Key: `country_iso3`, `year`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country |
| `year` | int32 | yes | Year |
| `num_songs` | int64 | no | Eligible songs of the country and year. Null when the release has no songs folder for the country |
| `num_artists` | int64 | no | Distinct artists of those songs |
| `num_songs_by_exception` | int64 | no | Those songs that entered by exception (`resources/lyrics/eligibility_exceptions.csv`) |
| `num_songs_scored` | int64 | no | Those songs that have topic scores |
| `T01` to `T38` | float64 | no | One column per topic id: the mean of the scores on that topic that are not null. Null when no song of the country and year has a score on the topic |

The file also holds every column of `countries.parquet` (`COUNTRY_COLUMNS` in `countries_panel.py`), except `num_songs`, `num_artists` and `artist_count_method`, which the release counts again.

### `songs.parquet`: one row per eligible song; no lyric text

Folder: `analysis/<YYYYMMDD>/`. Key: `country_iso3`, `song_id`.

| Column | Type | Required | Meaning |
| --- | --- | --- | --- |
| `country_iso3` | string | yes | Country |
| `song_id` | string | yes | Id of the song in the country tables |
| `artist_id` | string | yes | Joins to `artists.parquet` of the country |
| `year` | int32 | no | Release year. Empty when the song has no year; such a song is not in `country_year.parquet` |
| `source` | string | yes | Where the lyrics come from |
| `route` | string | yes | Route of the run that added the song |
| `by_exception` | boolean | yes | True when the song entered by exception (`resources/lyrics/eligibility_exceptions.csv`) |
| `scored` | boolean | yes | True when a score of the newest scoring run has the same `song_id` and `lyrics_sha256` |
| `T01` to `T38` | int16 | no | One column per topic id: the score of the song. Null when the song has no score |

<!-- generated:analysis_tables:end -->

### How the release is built

- **Inputs.** The newest complete songs folder and scores folder of each country (`latest_country_songs_dir`, `latest_country_scores_dir`), and the newest complete country-year table (`latest_clean_countries_dir`). A country with no complete songs folder is not in the release. The manifest names each input folder.
- **Eligible songs.** One function decides which songs enter: `classify` in `src/songs/stage_50_analysis/eligible_songs.py` (decision 0007). It gives each song that it leaves out one reason, in this order: `quality_quarantine` (`quality_status` is `quarantine`), `suspect_text` (`lyrics_text_hash` and `source` are on `resources/lyrics/suspect_text_hashes.csv`), `quarantined_song` (`song_id`, `artist_id`, `source` and `lyrics_text_hash` are on the list of the newest `clean/quality/song_quarantine/<YYYYMMDD>/` folder), `excluded_artist` (`artist_id` is on `resources/lyrics/excluded_artists.csv`), `artist_country` (`resources/lyrics/artist_countries.csv` gives the artist another country than `country_iso3`, or the newest `clean/quality/artist_country/<YYYYMMDD>/` folder gives the artist `other_country` for `country_iso3`; the tracked list alone decides for an artist that it names), `suppressed_duplicate` (`duplicate_decision` is `suppress_duplicate`), `not_canonical` (`canonical_song_id` names another row), `re_release` (the re-release check says that the row is a re-release), `text_copy` (the newest `clean/quality/text_copies/<YYYYMMDD>/` folder lists `country_iso3` and `song_id`; a listed song that an earlier rule leaves out reports that rule), `uncredited_song` (the newest `clean/quality/uncredited_songs/<YYYYMMDD>/` folder lists `country_iso3` and `song_id`), `entered_by_hand` (route `manual_review`, and the country has no group in the exceptions file), and `year_out_of_range` (outside 1900 to 2026). A song with no year is eligible: it is in `songs.parquet` with an empty `year`, and it is not in `country_year.parquet`.
- **Exceptions.** `resources/lyrics/eligibility_exceptions.csv` names the countries whose hand-collected songs enter, with the reason and the date of the decision. Such a song has `by_exception` true. `country_year.parquet` counts them in `num_songs_by_exception`, and the manifest counts them for each country (`songs_by_exception_<ISO3>`). The file has no rows while no country has a `manual_review` run. A test fails when a run record names that route and the file has no row for its country.
- **Scores.** A score joins a song on `country_iso3`, `song_id` and `lyrics_sha256`. A score of other lyric text, or of a song that is not in the songs folder, does not join. The manifest counts both (`scores_other_lyrics`, `scores_no_song`), and the scores of songs that are left out (`scores_ineligible_song`). The build stops when these counts and `songs_scored` do not add up to the scores read, when a country has scores and no complete songs folder, and when a row names another country than its folder. A song with no score stays, with empty topic columns.
- **Counts.** The manifest counts `songs` (rows read), `eligible_songs` (rows in `songs.parquet`), `left_out_<reason>` for each reason, `songs_by_exception`, `songs_scored`, `songs_in_country_year`, `country_year_left_out_no_year` (eligible songs that are not in `country_year.parquet` because they have no year), `songs_outside_panel` (eligible songs with a year whose country and year are not in the country-year table), `scores`, `countries` and `country_years`. The build stops when the eligible songs and the songs left out do not add up to the songs read, and when `songs_in_country_year`, `country_year_left_out_no_year` and `songs_outside_panel` do not add up to the eligible songs.
- `songs.parquet` of the release holds no lyric text.

## Clean dumps

A dump is a source that the project holds whole and searches by artist and title: the lyric websites, Letras, LRCLIB and Genius. MusicBrainz and Discogs are catalogs, not dumps, because they hold no lyrics.

In the old data, each dump has its own shape. The uniform format is 2 tables per dump, always both, always these columns. The date of the folder is the date of the build. The manifest names the `raw/` folder that the dump was built from. `songs dumps build` reads one old dump and writes this format. The command reads the folder the caller names and the `raw/` folder the caller names. It does not choose a folder itself.

<!-- generated:dump_tables:start -->
<!-- Do not edit by hand. To rebuild, run: python -m songs.common.schemas --write -->

### `songs.parquet`: one row per song and credited performer

Folder: `clean/dumps/<source>/<YYYYMMDD>/`. Key: `source_song_id`, `credit_position`.

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
| `year_source` | string | no | Old column that gave `year`, without `_raw`: `release_year` is the song, `album_release_year` is the album of the song (a fallback), `release_date` is a printed date. Null when `year` is null |
| `album` | string | no | Album name |
| `fetched_utc` | string | no | When the page or the record was fetched |
| `raw_ref` | string | no | Where the raw page is under `raw/`, relative to the data folder |

### `artist_names.parquet`: one row per name of an artist at the source

Folder: `clean/dumps/<source>/<YYYYMMDD>/`. Key: `source_artist_id`, `artist_name`.

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

- A dump stores no normalized name key and no normalized title key. Matching code computes keys with one shared function, so a change of the normalization does not need a new build of every dump. The builder does not copy LRCLIB `artist_key` or `title_key`, a site-snapshot `latin_matching_key`, or the Letras `source_artist_key`.
- Crawl state is not clean data. Queues, attempts, HTTP status, parser versions, receipts and logs stay in `raw/`.
- A source that is held back from matching is a list in tracked code or in `resources/`, with the reason. It is not a missing dump. The list is `resources/lyrics/held_back_from_matching.csv`.
- `year` and `language` are null for most rows of Letras, AAMA, Fnanen, Kugeci and the text-only sources. That is correct. Do not invent values.
- A crawl that did not finish has the manifest note `The crawl is incomplete.` The builder reads `STOP`, `latest.json` and `manifest.json` in the folder it gets and, for a `snapshots/<stamp>/` folder, in the crawl folder two levels up. A result with no songs is not written.
- `year_source` names the old column that gave `year`, without `_raw`. `album_release_year` is the year of the album of the song, a fallback when the song has no year of its own. A date text gives a year only when it holds exactly one four-digit number.
- A row whose `text_kind` is not a lyric kind is dropped as `not_lyrics`. The manifest also counts these rows for each kind, as `dropped_not_lyrics_<kind>` (for example `dropped_not_lyrics_lyrics_or_poem`, `dropped_not_lyrics_chord_sheet`).

### Where each uniform column comes from

This table is guidance for the builder of the dumps. It gives the column of each old shape that holds the value.

| Uniform column | Site snapshot family | Letras | Stixoi | Kugeci | AAMA, Fnanen | Genius | LRCLIB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `source_song_id` | `provider_song_id` | `source_song_key` | `provider_song_id` | `provider_song_id` | `provider_song_id` | `genius_song_id` | `track_id` |
| `song_url` | `song_url` | `song_url` | `provider_url` | `song_url` in the song index | `song_url` | none | none |
| `artist_name` | `artist_name`, performer credits only | `artist_name` | through `artist_songs`, role `performer` | labels in a JSON list | `artist_name` on the song, or `<site>_artist_songs.artist_name`, or `artist_heading` | `artist_name` | `artist_name` |
| `song_name` | `song_name` | `song_name` | `title` | `provider_title` | `song_name`, or `provider_title` | `song_name` | `name` |
| `lyrics` | `lyrics`, rows with `text_kind` = `lyrics` | `lyrics` | `lyrics` | `lyrics_text` | `lyrics`, or `lyrics_text` when `lyrics` is empty | `lyrics` | `plain_lyrics` |
| `language` | `language_label` | none | `language` | none | `language` when the column exists | `language_cld3` | none |
| `year` | `release_year_raw`, then `album_release_year_raw`, then the year in `release_date_raw` | none | `release_year` | none | none | `year` | none |
| `album` | `album_name` | none | through `song_albums`, when the song has one album | none | none | none | `album_name` |
| `fetched_utc` | `retrieved_at_utc` | `retrieved_at_utc` | `parsed_at_utc` | `last_attempt_at_utc` | `fetched_at_utc` | none | `updated_at` |

The columns `url`, `title`, `fetched_at` and the table `relations` are not the AAMA or Fnanen dump. Those names were wrong.

These shapes are not in the table above. The same uniform columns come from them as follows.

| Uniform column | Balkan engine | Central Asia harvest | Corpus import | Russian dump | GeniusRU import |
| --- | --- | --- | --- | --- | --- |
| `source_song_id` | `source_song_key` | `provider_song_id` | `provider_song_id`, or `source_record_id` | `source_song_id` | `source_song_key` |
| `song_url` | `song_url` | `song_url` | `song_url` | `song_url`, or `source_url` | `song_url` |
| `artist_name` | `artist_name` | `artist_name`, or rows of `artist_songs` | performer credits, or `artist_name`, or `source_singer_credit` | `artist_name`, or `artist` | performer credits, then `featured_artists` |
| `song_name` | `song_name` | `song_name`, or `provider_title` | `song_name` | `song_name`, or `song_title` | `song_name` |
| `lyrics` | `lyrics`, rows with `text_kind` = `lyrics`, `original` or `source_lyrics_or_poem` | `lyrics`, or `lyrics_text` when `lyrics` is empty | `lyrics` | `lyrics` | `lyrics` |
| `language` | none | none | none | none | `verified_language` |
| `year` | none | none | `source_year` | none | `release_year` |
| `album` | none | none | none | none | none |
| `fetched_utc` | `fetched_at_utc` | `fetched_at_utc` | none | `fetched_at_utc` | `imported_at_utc` |

Four integration builds have no column map yet: `appleofmyeye`, `deungdutjai`, `lidicity` and `lyricsmy`. Their columns were not read.

## Known gaps

These things do not follow the layout yet. Each one needs its own task. Do not copy them in new code.

- **Populism from the old pipeline.** `OLD_PIPELINE_FILES` in `countries_panel.py` reads one file of the old pipeline, `populism_fst/populism.parquet`, from the newest complete folder of `raw/populism_fst/<YYYYMMDD>/`. No such folder exists yet, so the three populism columns are empty and the build reports the input absent. The source is `populism_fst` in `resources/data_sources.toml`.
- **No manifest in `raw/`.** Only three writers make a manifest for a `raw` folder: `songs lyrics collect`, for the folder that it writes, `songs dumps parse`, for the lyric table that it reads from a packed folder of saved pages, and the packer, for a packed folder. No command calls the packer yet. No command writes a manifest for a `raw_manual_review` folder. A person puts a review workbook in its folder, so the import of a workbook does not ask for a manifest there.
- **Earlier builds have no manifest.** A `clean/countries/<YYYYMMDD>/` folder that was built before this standard has no manifest, so `latest_clean_countries_dir` does not return it. Build the table again to get a folder with a manifest.
- **Earlier imports of a review workbook.** Before this standard, the import wrote `lyrics/<ISO3>/manual_review/<run id>/songs.parquet`. A folder of that form is not in the layout, and no code reads it.
- **`countries.parquet` has no schema in `schemas.py`.** Its column list is in `countries_panel.py`, and the build checks the list.
- **Tiers outside the layout.** `DataLayout` in `paths.py` still names `extraction`, `processed`, `restricted`, `manifests`, `rankings` and `matching`. The layout has no such layers.
- **Old data.** The songs of all 226 countries are in the layout: `songs lyrics import-old` imported them from the final files of the old pipeline, and the bucket holds the songs folders. The `raw/<source>/<YYYYMMDD>/` folders that `resources/data_sources.toml` names for the economic sources also have the layout and a manifest. On 2026-11-24 Gabriel deleted the other objects that the bucket held before this layout, by the list of decision 0010: 10,415,216 objects (474.286 GiB). A deleted object can be restored until about 2027-03-24. Gabriel chose to keep 267.941 GiB of earlier objects at their old paths: crawl state, objects that were not checked, and sole copies. No code of this repository reads them.
