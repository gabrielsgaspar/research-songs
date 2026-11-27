# Countries

One folder per country, named by its ISO 3166-1 alpha-3 code (`BRA`, `NGA`, `JPN`). The folder is the history of lyric collection for that country ([decision 0003](../docs/decisions/0003-country-folders-and-run-records.md)).

```
countries/<ISO3>/
  runs/        one JSON file per collection run, written by the command that ran
  campaigns/   two JSON files per campaign: one when it opens, one when it closes
  scoring/     one JSON file per topic scoring run, written by `songs score collect`
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

Close a campaign as `stopped` when its songs failed a check after its runs, for example the roster check. While the newest campaign of a country is `stopped` and `songs_after` is more than `songs_before`, the rule for eligible songs leaves out every campaign song (route `dump_name`) of the country with the reason `held_country`. The older songs of the country stay eligible. A stopped campaign that added no songs holds nothing. To end the hold, fix the cause and close a later campaign as `complete` or `abandoned`. On 2026-11-24, 14 countries were held with 1,928 campaign songs. The rule gave 1,899 of them the reason `held_country`; the other 29 songs (PHL) have the earlier reason `artist_country`.

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

10. Open the pull request with the new run records, the campaign records and the coverage page. Each run writes the coverage page again, so it is already current. Use the report of step 6 as the body of the pull request.

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

A roster artist with no Discogs id gets one when exactly one Discogs artist has the same name key. No other roster artist may hold that id. A release of the country must credit that Discogs artist, so an artist of another country with the same name gets no id. When several Discogs artists have the name key, the roster artist gets the id of the one that two or more releases of the country credit, when these are at least 0.5% of its releases and no other of them has a release of the country, or when the next of them has fewer than one fifth of its releases of the country (`DOMINANCE`). When neither holds, the roster artist gets the id of the only one whose Discogs profile starts by stating the country itself. Two roster artists of the country with the same name key get the same id. On 2026-11-25, in a sample of 50 artists of the Spanish-speaking countries that got an id by the last three rules, 48 were right and 2 doubtful. These rules brought in, for example, Luis Miguel, Alejandro Fernández, Mecano and Ricky Martin. The share keeps out a world star with a few local releases, such as Madonna for DZA. On 2026-11-24, in a sample of 100 such pairs in 22 countries, 1 was wrong and 4 were doubtful; with one release of the country as the minimum, 3 of 16 were wrong. The file `resources/lyrics/discogs_countries.csv` lists the release countries of Discogs that count for each country; a state that no longer exists, such as the USSR, counts for each country that followed it. The songs of the artist still need a title match with a track of that artist. The links of these songs carry a match method that ends with `_artist_by_name`. The import writes the Discogs id of such an artist to the roster of its new folder (`discogs_artist_id` in `artists.parquet`), for each artist that gets a song or that has a link of an earlier import. The match method of the links still shows that the id was found by name.

### Other names of an artist

A dump can credit a roster artist under another name: "Jesse y Joy" for the roster artist "Jesse & Joy", or "Camarón de la Isla" for "El Camarón De La Isla". A roster artist with a Discogs id also matches a dump credit under each name variation of that Discogs id, each name that a release credits it with, its name with or without a leading article (el, la, los, las), its name without an inner "y", "and" or "e", and its name without text in brackets (`dump_match.variant_keys`). Such a name must have 4 characters or more, must not be the name key of a roster artist of the country, and must come from one Discogs id only. A name of one word must also be the name key of no other Discogs artist, because a name such as "Soraya" is the name of many artists. A dump name whose `dump_match.spelling_key` is the spelling key of the names of one Discogs id only is a name of that artist too. The spelling key joins two transliterations of one name: it drops the apostrophes, writes Cyrillic in Latin letters, joins letter groups such as "kh" and "x", and keeps the consonants of each word, so "Sherali Jo'rayev", "Sherali Juraev" and "Шерали Жураев" share one key. A name of one word, or of fewer than 6 key letters, has no spelling key. The apostrophe letters of Uzbek Latin (ʻ, ʼ) count as apostrophes in every name key. A dump credit "A (B)" whose two parts are in two scripts, such as "Bird Thongchai (เบิร์ด ธงไชย)", gives A and B as other names of that dump artist: the dump build writes them to `artist_names.parquet` (`dumps._TWO_SCRIPT_ALIASES`). The songs still need a title match with a track of that Discogs id. On 2026-11-25 a sample of 40 artists of the Spanish-speaking countries with the most songs from these names gave 33 right and 7 doubtful; of the songs that MEX would add, 780 came under another name.

### Artists on no roster

A large artist of a country can be on no roster, and then no dump song of it can be added. At campaign time, `songs.stage_00_ingest.discogs_roster` finds Discogs artists with strong home evidence, and the survey and the import treat them as roster artists with a Discogs id. Such an artist has at least 5 releases as a main artist in a release country that is a home of this country only, these releases are at least 80% of its main releases with a release country, the start of its profile states no other country, and fewer than half of its main releases are Classical or Non-Music. A release of the USSR does not count, because the USSR is a home of 16 countries. An artist whose Discogs id is on any roster, or whose name key is on the roster of the country or on another roster without a Discogs id, is left out. Only an artist that gets a song joins the roster of the new folder, with the country tag `discogs_home_releases`. The manifest counts these artists (`artists_added_by_discogs_home_rule`), the run record names them in its notes, and the survey gives `would_add_new_artists`. On 2026-11-24 the rule would add about 4,900 songs of 392 artists to 16 of 22 thin countries; most are in TUR (3,476 songs) and UKR (1,108 songs). In a sample of 120 artists of the rule, 3 were of another country, 2 were doubtful, and 6 were not song artists (instrumental or DJ acts).

A second rule starts from the dump of the campaign (`discogs_roster.dump_artists`). It reads only the credited names and the song ids of the dump, never the lyric text. A credited name with at least 10 songs in the dump looks for a Discogs artist with the same name key, the same loose key, or the same spelling key (see "Other names of an artist") when no other credited name of the dump has that spelling key. The loose key is the key without text in brackets, without the words "y", "and", "e" and "et", and without spaces, so that "Alexis y Fido" finds "Alexis & Fido". The name is left out when its key is on the roster of the country, or on the roster of another country that the source of the dump serves, with a Discogs id. A roster of a country that the source does not serve does not count: the German electronic act "Olympic" does not stop the Czech band "Olympic (2)" in the Czech dump `karaoketexty`. A source of every country (`genius`, `lrclib`) keeps every roster. The name is also left out when its key is on another roster with no Discogs id and the Discogs artist has a release in a home of that country only, because that roster artist can get the id by name. A release in "Czechoslovakia" or "Yugoslavia" is in a home of several countries, so it does not stop a Slovak singer on the Czech roster. A Discogs artist gets a country when the start of its profile states exactly that country. It also gets a country when its profile states no country, its top release country is a home of that country only, and at least 3 of its main releases are there. The Classical and Non-Music filter, the list of entries that name no performer, and the rule that no roster may hold its id apply as above. When several Discogs artists get a country, the one with at least 5 times the home releases of the next wins. Otherwise the name gets no artist. The roster name is the credited spelling, so that the dump songs match it. Such an artist joins with the same country tag `discogs_home_releases`. On 2026-11-25, on the musica dump, the rule would add 2,444 songs to MEX, 2,142 to ARG, 1,341 to ESP, 143 to URY and 72 to ECU. In a sample of 80 artists of an earlier version in 8 countries, 69 were right, 11 were doubtful and 1 was of another country. Most wrong artists have a career in a large market, for example a Guatemalan band with most of its releases in Mexico.

### Artists of another country

Some rosters hold artists of other countries. `uv run songs lyrics roster-check` applies one automatic rule to every roster and prints the counts. It takes about 10 minutes and reads only. With `--write`, it writes the table `clean/quality/artist_country/<YYYYMMDD>/artist_country.parquet` in the data folder.

The rule looks at each roster artist with a Discogs id, also an id found by name. The artist gets the decision `other_country` only when three conditions hold: the start of the Discogs profile states another country, the same text has no word of a home country, and fewer than 20% of the releases of the artist are in a home release country while another country has the most releases. Every other artist gets `keep`. No person checks a row. The tracked list `resources/lyrics/artist_countries.csv` wins over the table for an artist that it names. For the rules of "Artists on no roster", an artist that the tracked list gives another country is on no roster, so the country that the list names can take its Discogs id. An import of a dump does not add a song of an artist with `other_country` in the newest table, or of an artist that the tracked list gives another country; the run record counts the song as `artist_other_country`. The rule for eligible songs leaves out the songs that the country already holds of such an artist, with the reason `artist_country`. The United States is a home of Puerto Rico for the profile words (`ALSO_HOME`), because many Puerto Rican artists live and record in New York. On 2026-11-25, without it, 2 of the 3 `other_country` decisions for PRI were wrong, among them De La Ghetto with 300 songs. [The data layout](../docs/standards/data_layout.md) gives the rule in full and the columns of the table. The country words are in `resources/lyrics/country_words.csv`.

### Copies of a held text

The same lyrics from a second source differ in punctuation, spacing or case, so their hash is not the hash of the held text. An import compares the texts on a key instead: the text in lower case with only its letters and digits, of any script (`songs.common.lyric_hash`). An import does not add a song that is a text copy of a song that the country holds, or of a song that the same import adds. A song is a text copy of another song when one of two conditions holds:

- The two kept texts are the same, for any two artists of the country.
- The two songs have the same roster artist, and the first 300 kept characters are the same.

A kept text of fewer than 30 characters has no key and is never a copy. Of two copies in one import, the import adds the song with the lower `source_song_id`. The run record counts each song that the import holds back as `held_text`. The survey estimate uses the same rule, so it does not count these songs. The rule reads the text of each held song of the country and of each song that the import would add, not the text of the whole dump. On 2026-11-24 this added about 35 seconds to an estimate of the `lrclib` dump, and the held songs of a country with 1.5 million songs take about 35 seconds more.

### Close title matches

A dump song can match a Discogs track of its artist only by close spelling: the loose title keys are 90% similar or more (`CLOSE_CUTOFF`), for example "Tu Tenias Razón" and "Tu Tenia Razon". An import adds such a song when both titles hold the same numbers in the same order (`dump_match.same_numbers`). A song whose numbers differ, such as "Saludo 2010 (En Vivo)" and "Saludo 2004", stays out with the class `close`. A decision in `resources/lyrics/reviewed_close_matches.csv` wins over the rule for its track: `reject` keeps a song out, and `accept` adds it. The link of such a song has the match method `dump_discogs_close_title` and its similarity as the score. On 2026-11-25, a sample of 130 close matches of the `musica` dump (70, in DOM, URY, ECU, PAN, CRI, NIC, PRY and SLV) and the `lrclib` dump (60, in ECU and URY) gave these counts: the rule added 126 songs, of which 2 were another song ("No hice nada" and "No dice nada") and 4 were doubtful. It kept out 4 songs, of which 2 were wrong and 2 were right with a track number in the dump title.

### Limits of a campaign

An audit on 2026-11-24 read the 978,744 songs that campaigns added to 74 countries. It found these limits. Read them before you report the result of a campaign.

- `rows_added` is not the number of new lyrics. About 72% of the added songs were a new text with no doubt. About 19% had the same text as an older song of the same artist in the same country, when only letters and digits are compared.
- Until 2026-11-24, an import held back a text only when its hash was the same as the hash of a held text. The hash changes with punctuation and with small differences between two sources, so the same lyrics from a second source passed this check. Since then, an import also holds back a text copy (see "Copies of a held text"). The copies that earlier imports added stay in their folders. `uv run songs lyrics copy-check --write` lists them in `clean/quality/text_copies/<YYYYMMDD>/`, and the rule for eligible songs leaves them out with the reason `text_copy`. The check also lists the older songs that are copies, because the duplicate checks of the old pipeline found only some of them. A campaign song represents a group of copies only when another rule leaves out every older song of the group. On 2026-11-25 the dry check marked 215,006 of the 990,307 campaign songs and 604,711 of the 4,295,956 older songs.
- The title checks cannot see an older song that has no title. In the audit, 53% of the older songs had no title, and 95% of the older copies were such songs. The text copy check needs no title.
- A title with a suffix after a dash, such as "- Remastered" or "- Live", counts as a new title. In the audit, about 2% of the added songs repeated the text of another added song of the same artist. The text copy check now holds back such a song when its text is a copy.
- Until 2026-11-24, the match gave each dump song every name of its artist id. In the Genius dump, 4,086 ids hold the primary names of unrelated artists (282,810 songs). For example, id 353676 holds Nicki Minaj, Rosa Linn, KIDZ BOP Kids, Mura Masa, Magic System and Kygo. So a song could go to a roster artist that it does not credit: about 1,880 campaign songs did. Since then, the songs of an id with two or more primary names of different keys get only their credited name. `uv run songs lyrics credit-check --write` lists the songs that earlier imports added this way in `clean/quality/uncredited_songs/<YYYYMMDD>/`, and the rule for eligible songs leaves them out with the reason `uncredited_song`. On 2026-11-24 the dry check marked 1,870 of the 990,307 campaign songs.
- About 2% of the added songs have a text that another country also holds. Most are one artist on the rosters of two countries.
- About 78% of the added songs belong to an artist whose Discogs id was found by name. In a sample of 30 such artists, 27 were right for their country.
- The dumps `lrclib` and `genius` hold the lyrics of a song under each recording of it. An instrumental recording of a standard can get the lyrics of the song.
- A remaster or a live version can give a song a year that is too late, because the year comes from the matched Discogs track.
- A dump campaign adds little to a country with a small roster or with few Discogs ids. On 2026-11-24 the survey estimate for the 30 best countries with no campaign was about 16,600 songs in total. Such a country needs a new source first.

After a campaign, report the `held_text` count of each run record next to `rows_added`.

### Lessons of the musica campaigns of 2026-11-25

Four rounds of the `musica` dump for the 20 Spanish-speaking countries added 40,064 songs, about 6,460 of them from before 1990. A fifth survey added 0. Read these lessons before the next campaign with a dump that already ran.

- A rule change can make an old dump worth a new run. The first round only ran the import again with the rules of the week before, and it added 20,397 songs to 10 countries. After a change to the matching rules, run `songs lyrics survey` again for every country that a dump already served.
- The largest class of songs left out is `no_track`: the artist is on the roster with a Discogs id, but Discogs has no track with that title. A looser title match does not help. In DOM, 336 of 2,016 such songs had a Discogs title of the artist that was 50% similar or more, and almost all of them were another song.
- Most close title matches are the same song with a spelling error. A match whose numbers differ was the most common wrong match.
- A famous artist was often missing because its name had another form in the dump ("Jesse y Joy" against "Jesse & Joy"), because several Discogs artists had its name, or because it was on no roster. The rules of "Artists with no Discogs id", "Other names of an artist" and "Artists on no roster" now find most of them. Some are still blocked by a homonym on the roster of a country outside the Spanish-speaking world, for example Raphael (FRA), Yuri (JPN), Karina (KOR) and Lucero (USA).
- An artist with a career in a large market, such as Mexico or Spain, can get that country from its release counts. Such an artist goes to `resources/lyrics/artist_countries.csv`, which the import now reads.
- The small countries (BOL, CRI, ECU, GTM, HND, NIC, PAN, PRY, SLV) have large rosters with Discogs ids, but musica has songs for only a few of their artists. These countries need a new source, not new rules.
- 368 of the 39,986 songs of the first three rounds have a text that another of the 20 countries also holds. Most are duets, such as the songs of Leiva with artists of other countries.

### Lessons of the dump campaigns of 2026-11-26

Campaigns for 53 countries (the former USSR, the Balkans, Bulgaria, the Czech Republic, Slovakia, India, and the Portuguese- and Spanish-speaking countries) added 166,714 songs from the dumps we hold, in up to three rounds. A last round added 0 to 57 songs for each country. At least 32,500 of the new songs are from before 1990. BRA gained 70,113 songs (55,850 of them from `letras`), ESP 19,735, RUS 13,591 and MEX 9,080. Read these lessons before the next campaign.

- Clean every saved site first. Seven archives (`cuspajz`, `pesmarica`, `kyrgyzaudio`, `matinder`, `mediastar`, `georgianlyrics`, `geolyrics`) had raw pages only. Each now has a page reader in `site_pages.SITES` and a clean dump in the bucket. The `letras` clean dump (3.2 million songs) was in the bucket only and had never been matched.
- Check the countries that each source serves. The Russian dumps served only the Russian-language countries and the Balkan dumps did not serve MKD and SVN, so no campaign tried them there. A source entry must list every country with a real share of its songs.
- Transliteration was the largest gain after letras. The spelling key and the Discogs name variations brought in Cyrillic and Latin spellings of one artist: RUS gained 9,432 songs from `lrclib`, which had run before. A sample of 45 artists with the most songs under another name was right, except a band and its singer (Неприкасаемые and Гарик Сукачёв) and one cover version.
- The Uzbek apostrophe letter (ʻ) gave another name key than the plain apostrophe, so "Sherali Joʻrayev" of the roster never met "Sherali Jo'rayev" of the dump. Every apostrophe letter is now an apostrophe in a name key.
- A homonym on the roster of a country that a dump does not serve blocked a famous artist: the German act "Olympic" blocked the Czech band. Such rosters no longer block a dump name; Olympic joined CZE with 140 songs.
- Most songs of the Central Asian and Caucasian sites have no Discogs track, so the rule for songs with no year keeps them out: `uztext` added 2 songs of 3,841, `kyrgyzaudio` 25 of 7,062, `matinder` 293 of 6,562. These countries need another catalog of songs, not new matching rules. TJK, TKM, HND, PRY and TLS gained nothing.
- About 7% of the `letras` songs of BRA came through a close title match, and some of them are other songs ("Coração Vadio" matched "Coração Vazio"). A rule for close titles of letras is the next quality check.
- The famous-artist check of 1,236 artists in 30 countries found 709 covered. The gaps that remain are mostly in GEO, MOZ, UZB, ARM, MNE, MDA, AZE and KAZ, artists on the SUN or YUG roster (Ekatarina Velika, Агата Кристи), and roster artists that hold the Discogs id of a homonym (Rasta and Coby in SRB).

### Lessons of the new-rules pass of 2026-11-27

One round of `lrclib`, `genius` and the local dumps, with the rules of pull requests 108 to 136, added 180,423 songs to 14 countries whose last campaign came before those rules: GBR 61,495, DEU 37,025, JPN 19,594, ITA 18,836, POL 13,549, NLD 13,211, ISR 7,295, ROU 3,094, HUN 2,111, TUR 2,037, THA 661, IDN 631, MYS 502 and CYP 382. The USA was left out, because its estimate alone takes about 2 h 45 min. Read these lessons before the next campaign.

- Run a survey again after every change of the match rules, also for a country whose dumps are "used". The new rules found Hebrew, Japanese and Greek names of roster artists that carry a Latin name on Discogs: `hebrew_lyrics_hf` added 6,265 songs to ISR, where it had added 2,676 before.
- Most new songs are from after 2000. lrclib and genius add few songs before 1990 in any country.
- A sample of the largest groups of songs with another dump name was right, except a few cases: 13 songs of the Italian Nino D'Angelo went to the German Nino de Angelo, 53 songs of Yoko Ono to The Plastic Ono Band (GBR), and 38 Genius poem pages of A. E. Housman to song settings of his poems (GBR).
- `stixoi` serves CYP: it added 256 songs, all of Anna Vissi and Evridiki. `deungdutjai` added only 40 songs to THA. Its titles are in Thai script, and the Discogs tracks of Thai artists mostly have Latin titles, so 2,407 songs of roster artists find no track.

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

## Read a saved site

Some sites are on this disk as saved pages, packed into `pages-*.tar.gz` parts. `songs dumps build` cannot read pages, so one command reads them first. `songs.stage_00_ingest.site_pages` reads the packed parts of every site, and one small module for each site reads its pages: `textpesenok`, `cuspajz`, `pesmarica`, `kyrgyzaudio`, `matinder`, `mediastar`, `georgianlyrics`, `geolyrics` and `afghansonglyrics` (`site_pages.SITES`). For example:

```bash
uv run songs dumps parse textpesenok raw/textpesenok/20261004/
```

- It reads the parts as a stream. It extracts no file to disk and sends no request.
- It writes a new folder `raw/<source>/<YYYYMMDD>/`: one lyric table, one table of the performers of each song, and a manifest whose input is the packed folder. It never writes over a folder.
- It prints the pages read, the songs written, and the pages left out by reason: an error status, a page that is not a song page, a page that does not decode, no lyric block, no artist, no title, an empty text, an instrumental marker, a second copy of a song.
- A title with the word "перевод" (translation) or "аккорды" (chords) gives the text kind `translation` or `chords`. `songs dumps build` leaves such a text out.

The command prints the `songs dumps build` command that follows it.

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

[`docs/status/coverage.md`](../docs/status/coverage.md) has one row per country. It is generated from the records. Each collection run writes it again, and a test fails when it is out of date. After you merge `main` into a branch with new records, the page can conflict. Then write it again:

```bash
uv run songs lyrics coverage --write
```
