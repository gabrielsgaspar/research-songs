# Lyric sources

This page is generated from `resources/lyric_sources.toml` and `resources/language_countries.toml`. Do not edit it by hand.

To rebuild it, run `python -m songs.common.lyric_sources --write`.

It answers one question: where can lyrics for a country come from? For one country, with the runs that already used each source, run `uv run songs lyrics sources <ISO3>`.

A run record may name only a source on this page. To use a new source, add its entry to `resources/lyric_sources.toml` first.

| Kind | Meaning |
| --- | --- |
| bulk_dump | A dataset file that we hold. A run sends no requests |
| site_archive | A copy of a whole site that we collected. A run sends no requests |
| manual | Files that a person prepares for the project |
| live_site | A site that a run sends requests to |
| internal | A step of the project itself, not a place that lyrics come from |

| Access | Meaning |
| --- | --- |
| allowed | Requests may be sent, with the stated delay |
| blocked | Do not send requests to the site. A copy that we hold stays usable |
| not_applicable | The source takes no requests |
| unknown | Not confirmed. Confirm before a run sends requests |

"Checked: no" means that the entry comes from notes or from a name only, not from code or data. An empty stored path means that no copy is confirmed.

## Kind: bulk_dump

| Id | Name | Serves | Routes | Access | Stored copy | Checked | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `genius` | [Genius](https://genius.com) | All countries | genius_local | blocked | - | yes | Use the copy that we hold only. Never send a request to the site. |
| `lrclib` | [LRCLIB](https://lrclib.net) | All countries | lrclib_local | blocked | - | yes | Use the copy that we hold only. Never send a request to the site. The copy is an export dated 2026-08-07. |
| `gutenberg_jamaica` | [Project Gutenberg, Jamaican song book](https://www.gutenberg.org/ebooks/35410) | Countries: JAM | dump_name | not_applicable | - | yes | - |
| `tarab_hf` | [Tarab dataset](https://huggingface.co/datasets/drelhaj/Tarab) | Languages: Arabic | dump_name | not_applicable | - | yes | License CC BY 4.0. |
| `hebrew_lyrics_hf` | [Hebrew lyrics dataset](https://huggingface.co/datasets/Norod78/HebrewLyricsDataet) | Countries: ISR | dump_name | not_applicable | - | yes | - |
| `turkish_folk_kaggle` | Turkish folk songs dataset | Countries: TUR | dump_name | not_applicable | - | yes | On hold: the artist column of the dataset is empty. |
| `giitaayan` | Giitaayan | Countries: IND | local_source | not_applicable | - | yes | A pinned copy of a public file collection, dated 2026-07-07. Never sent requests. |
| `tamilcorpus` | Tamil songs corpus | Countries: IND | local_source | not_applicable | - | yes | A pinned copy of a public file, dated 2026-09-08. Songs in Tamil. |
| `wikisource` | [Wikisource, songs of India](https://en.wikisource.org) | Countries: IND | local_source | not_applicable | - | yes | - |
| `kugeci` | [KuGeci](https://www.kugeci.com) | Countries: CHN, HKG, TWN | dump_name | not_applicable | - | yes | A clean copy dated 2026-10-12 exists, with about 258,000 song rows. No pages were downloaded. |
| `nlb_sg` | [National Library Board, Singapore](https://data.gov.sg) | Countries: MYS, SGP | dump_name | not_applicable | - | yes | - |
| `geniusru` | [Russian Genius dataset](https://huggingface.co/datasets/sevenreasons/genius-lyrics-russian) | Countries: ARM, AZE, BLR, EST, GEO, KAZ, KGZ, LTU, LVA, MDA, RUS, TJK, TKM, UKR, UZB | dump_name | not_applicable | - | yes | A copy dated 2026-09-24 exists. On hold: rows carry no song link. |

## Kind: site_archive

| Id | Name | Serves | Routes | Access | Stored copy | Checked | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `letras` | [Letras](https://www.letras.com) | Languages: Portuguese, Spanish | archive, live, roster_update, recover | allowed, 0.5 s between requests | - | no | A site archive exists. The site also holds songs in other languages; the language list is not confirmed. Up to 5 requests per second were approved for the archive run. |
| `musica` | [Musica.com](https://www.musica.com) | Languages: Spanish | archive, live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive dated 2026-10-18 exists. |
| `todotango` | [Todo Tango](https://www.todotango.com) | Countries: ARG, URY | archive | unknown | - | yes | - |
| `hmpu_uy` | [Historia de la musica popular uruguaya](https://www.historiadelamusicapopularuruguaya.com) | Countries: URY | archive | unknown | - | yes | - |
| `jaimeroos` | [Jaime Roos](https://jaimeroos.uy) | Countries: URY | archive | unknown | - | yes | - |
| `mangulina` | [Mangulina](https://mangulina.do) | Countries: DOM | archive | unknown | - | yes | - |
| `parolesnet` | [Paroles.net](https://www.paroles.net) | Languages: French | archive, live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive exists. |
| `paroles2chansons` | Paroles2Chansons | Languages: French | archive, live, roster_update, recover | allowed, 1 s between requests | - | no | A site archive exists. The address of the site is not confirmed. |
| `wikimizik` | [Wikimizik](https://wikimizik.com) | Countries: HTI | archive | unknown | - | yes | - |
| `mentomusic` | [Mento Music](https://www.mentomusic.com) | Countries: JAM | archive | unknown | - | yes | - |
| `afrikalyrics` | [AfrikaLyrics](https://afrikalyrics.com) | Countries: CIV, CMR, COD, ERI, NGA | archive, live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive dated 2026-10-19 exists. The site holds more African countries than this list. |
| `ethiozeima` | [EthioZeima](https://www.ethiozeima.com) | Countries: ETH | local_source | allowed, 1 s between requests | - | yes | A site archive dated 2026-09-13 exists. Text is in Ethiopic script and in Latin letters. |
| `oromolyrics` | [Oromo Lyrics](https://oromolyrics.wordpress.com) | Countries: ETH | archive | unknown | - | yes | - |
| `tewle` | [Tewle](https://tewle.com) | Countries: ERI | local_source | unknown | - | yes | A site archive dated 2026-09-13 exists. Text is in Tigrinya. |
| `tononkira` | [Tononkira](https://tononkira.serasera.org) | Countries: MDG | archive | unknown | - | yes | - |
| `bongolyrics` | [Bongo Lyrics](https://bongolyrics.com) | Countries: KEN, TZA | archive | unknown | - | yes | - |
| `tooxclusive` | [tooXclusive](https://tooxclusive.com) | Countries: NGA | archive | unknown | - | yes | - |
| `ninejalyrics` | [9jaLyrics](https://9jalyrics.com.ng) | Countries: NGA | archive | unknown | - | yes | - |
| `lingala_cd` | [Lingala.cd](https://lingala.cd) | Countries: COD, COG | archive | unknown | - | yes | - |
| `ndombolo` | [Ndombolo](https://ndombolo.co) | Countries: COD, COG | archive | unknown | - | yes | - |
| `howwe` | [Howwe](https://howwe.ug) | Countries: UGA | archive | unknown | - | yes | - |
| `kasilyrics` | [Kasi Lyrics](https://kasilyrics.co.za) | Countries: ZAF | archive, dump_name | unknown | - | yes | - |
| `zedlyric` | [Zed Lyric](https://zedlyric.com) | Countries: ZMB | archive | unknown | - | yes | - |
| `aama` | [AAMA](https://www.aama.sa) | Languages: Arabic | local_source | allowed, 1 s between requests | - | yes | A site archive dated 2026-09-13 exists. |
| `fnanen` | [Fnanen](https://fnanen.com) | Languages: Arabic | archive, live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive dated 2026-09-13 exists. |
| `kalimat_anghami` | [Kalimat by Anghami](https://kalimat.anghami.com) | Languages: Arabic | archive | unknown | - | yes | - |
| `aghanylyrics` | [Aghany Lyrics](https://aghanylyrics.com) | Languages: Arabic | archive | unknown | - | yes | - |
| `songnu` | [Song.nu](https://song.nu) | Languages: Arabic | archive | unknown | - | yes | - |
| `altkia` | [Altkia](https://altkia.com) | Languages: Arabic | archive | unknown | - | yes | - |
| `arabiclyrics_net` | [ArabicLyrics.net](http://arabiclyrics.net) | Countries: EGY | archive | unknown | - | yes | - |
| `aghanilyrics` | [Aghani Lyrics](https://aghanilyrics.com) | Countries: DZA, MAR, TUN | archive | unknown | - | yes | - |
| `lyricstn` | [LyricsTN](https://lyricstn.tn) | Countries: TUN | archive | unknown | - | yes | - |
| `mustext` | [Mustext](https://mustext.net) | Countries: AFG, IRN, TJK | archive | unknown | - | yes | - |
| `ritmahang` | [Ritm Ahang](https://ritmahang.com) | Countries: IRN | archive | unknown | - | yes | - |
| `zibamatn` | [Ziba Matn](https://zibamatn.ir) | Countries: IRN | archive | unknown | - | yes | - |
| `musicdel` | [MusicDel](https://musicdel.ir) | Countries: IRN | archive | unknown | - | yes | - |
| `satext` | [Satext](https://satext.rozblog.com) | Countries: IRN | archive | unknown | - | yes | - |
| `lyric_erfan` | [Lyric Erfan](https://lyric-erfan.blogfa.com) | Countries: IRN | archive | unknown | - | yes | - |
| `zemereshet` | [Zemereshet](https://www.zemereshet.co.il) | Countries: ISR | archive | unknown | - | yes | - |
| `hngn` | [Hngn](https://hngn.co.il) | Countries: ISR | archive | unknown | - | yes | - |
| `jyrics` | [Jyrics](https://jyrics.com) | Countries: ISR | archive | unknown | - | yes | - |
| `tab4u` | [Tab4u](https://www.tab4u.com) | Countries: ISR | archive | unknown | - | yes | On hold: the pages are chord sheets, and no rows were published. |
| `joinmyjam` | [JoinMyJam](https://joinmyjam.com) | Countries: ISR | archive | unknown | - | yes | On hold: no rows were published. |
| `sarkisozum` | [Sarki Sozum](https://sarkisozum.gen.tr) | Countries: TUR | archive | unknown | - | yes | - |
| `repertukul` | [Repertukul](https://repertukul.com) | Countries: BGR, TUR | archive | unknown | - | yes | - |
| `lidicity` | [Lidicity](https://ip.lidicity.com) | Countries: CHN, HKG | archive | unknown | - | yes | A site archive dated 2026-11-06 exists, with Chinese songs, most of them from the 1930s and 1940s. Most artists are Shanghai singers; some sang later in Hong Kong. The songs have no year and no language. |
| `pmdb_taipei` | [Pop Music Database Taipei](https://pmdb.taipei) | Countries: TWN | archive | unknown | - | yes | - |
| `deungdutjai` | [Deungdutjai](https://deungdutjai.com) | Countries: THA | archive | unknown | - | yes | A site archive dated 2026-11-11 exists. The songs have no year and no language. Many artist names have a Thai and a Latin form. |
| `tkaraoke` | [TKaraoke](https://lyric.tkaraoke.com) | Countries: VNM | archive | unknown | - | yes | - |
| `nhaccuatui` | [NhacCuaTui](https://www.nhaccuatui.com) | Countries: VNM | archive | unknown | - | yes | - |
| `nhac_vn` | [Nhac.vn](https://nhac.vn) | Countries: VNM | archive | unknown | - | yes | - |
| `amnhacmiennam` | [Am nhac mien Nam](https://amnhacmiennam.blogspot.com) | Countries: VNM | archive | unknown | - | yes | - |
| `opmtunes` | [OPM Tunes](https://opmtunes.com) | Countries: PHL | archive | unknown | - | yes | - |
| `lieder_net` | [LiederNet](https://www.lieder.net) | Countries: DEU | archive | unknown | - | yes | The site also holds songs of other countries. |
| `deutscheslied` | [Deutsches Lied](https://deutscheslied.com) | Countries: DEU | archive | unknown | - | yes | - |
| `volksmusikdatenbank` | [Volksmusikdatenbank](https://www.volksmusikdatenbank.at) | Countries: AUT | archive | unknown | - | yes | - |
| `guitarparty` | [Guitarparty](https://www.guitarparty.com) | Countries: ISL | archive | unknown | - | yes | - |
| `musik_is` | [Musik.is](https://www.musik.is) | Countries: ISL | archive | unknown | - | yes | - |
| `local_file` | Compiled file of Greek songs | Countries: GRC | local_source | not_applicable | - | yes | A file that a researcher gave to the project. Songs carry no page link. |
| `stixoi` | [Stixoi](https://stixoi.info) | Countries: CYP, GRC | archive, live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive dated 2026-09-25 exists. It also serves Cyprus, because Cypriot artists sing in Greek. |
| `karaoketexty` | [KaraokeTexty](https://www.karaoketexty.cz) | Countries: CZE, SVK | archive | unknown | - | yes | About 1.0 million songs. Up to 5 requests per second were approved for the archive run. |
| `zoznam_hudba` | [Zoznam Hudba](https://hudba.zoznam.sk) | Countries: SVK | archive | unknown | - | yes | About 568,000 lyrics. Up to 5 requests per second were approved for the archive run. |
| `sergiudo` | [Sergiudo](https://sergiudo.com) | Countries: MDA | archive | unknown | - | yes | - |
| `textovenapesni` | [Textove na pesni](https://textovenapesni.com) | Countries: BGR | archive | unknown | - | yes | - |
| `pevcheskipodsetnik` | [Pevcheski Podsetnik](https://pevcheskipodsetnik.com) | Countries: BGR | archive | unknown | - | yes | - |
| `bgtekstove` | [BG Tekstove](https://bgtekstove.start.bg) | Countries: BGR | archive | unknown | - | yes | - |
| `tekstomanija` | Tekstomanija | Countries: BIH, HRV, MKD, MNE, SRB, SVN | archive | unknown | - | no | A site archive dated 2026-09-25 exists. The address and the countries are not confirmed. |
| `cuspajz` | [Cuspajz](https://cuspajz.com) | Countries: BIH, GBR, HRV, MKD, MNE, SRB, SVN, USA | archive | unknown | - | yes | Site archive crawled 2026-09-25, packed as raw/cuspajz/20261002/. Parsed and built 2026-11-25: raw/cuspajz/20261125/ and clean/dumps/cuspajz/20261125/ (29,519 songs, 2,646 artists, no years). The countries are those with at least 0.5 % of songs by artists that match the roster of one country only. The site also holds poems by poets; 839 traditional songs with no artist are left out. |
| `pesmarica` | [Pesmarica](https://www.pesmarica.rs) | Countries: BIH, GBR, HRV, MKD, MNE, SRB, USA | archive | unknown | - | yes | A chord site. Site archive crawled 2026-09-25, packed as raw/pesmarica/20261002/. Parsed and built 2026-11-25: raw/pesmarica/20261125/ and clean/dumps/pesmarica/20261125/ (10,269 songs, 2,282 artists, no years). The reader removes chord lines from each chord sheet. Some songs have more than one chord version, so 1,401 songs repeat an artist and title. The countries are those with at least 0.5 % of songs by artists that match the roster of one country only. |
| `dainuzodziai` | [Dainu zodziai](https://dainuzodziai.lt) | Countries: LTU | archive | unknown | - | yes | - |
| `pisni_org_ua` | [Pisni.org.ua](https://www.pisni.org.ua) | Countries: UKR | archive | unknown | - | yes | - |
| `nashe_com_ua` | [Nashe](https://nashe.com.ua) | Countries: UKR | archive | unknown | - | yes | - |
| `tekstpesni` | Tekst-pesni | Countries: ARM, AZE, BLR, EST, GEO, KAZ, KGZ, LTU, LVA, MDA, RUS, TJK, TKM, UKR, UZB | archive, live, roster_update, recover | allowed, 1 s between requests | - | no | A site archive exists. The address of the site is not confirmed. |
| `textpesenok` | [Text-pesenok](https://text-pesenok.ru) | Countries: ARM, AZE, BLR, EST, GEO, KAZ, KGZ, LTU, LVA, MDA, RUS, TJK, TKM, UKR, UZB | archive | blocked | - | yes | A site archive exists. Blocked for live runs: they returned almost no rows. |
| `akkordlar` | [Akkordlar](https://akkordlar.az) | Countries: AZE | archive | unknown | - | yes | - |
| `georgianlyrics` | [Georgian Lyrics](https://georgianlyrics.com) | Countries: GEO | archive | unknown | - | yes | A site archive dated 2026-10-07 exists (raw/georgianlyrics/20261007/, 1039 pages). The page reader wrote the clean dump clean/dumps/georgianlyrics/20261125/ (413 songs). The site tags do not tell singers from composers and poets, so every person tag is a credit. 53 posts with only genre tags have no artist and are left out. |
| `geolyrics` | [Geolyrics](https://geolyrics.ru) | Countries: GEO | archive | unknown | - | yes | A Russian-language site of Georgian songs; the reader keeps the Georgian text only. A site archive dated 2026-11-16 exists (raw/geolyrics/20261116/, a test crawl of 253 pages). The page reader wrote the clean dump clean/dumps/geolyrics/20261125/ (171 songs). |
| `kyrgyzaudio` | [Kyrgyz Audio](https://kyrgyz-audio.com) | Countries: KGZ | archive | unknown | - | yes | A site archive dated 2026-11-16 exists (raw/kyrgyzaudio/20261116/, 17921 pages). The page reader wrote the clean dump clean/dumps/kyrgyzaudio/20261125/ (7062 songs). 99% of the songs are in the section of Kyrgyz songs; the sections of Kazakh, Uzbek and Russian songs hold under 1% of them. The reader leaves out the books section. |
| `matinder` | [Matinder](https://matinder.kz) | Countries: KAZ | archive | unknown | - | yes | A site archive dated 2026-11-16 exists (raw/matinder/20261116/, 25698 pages). The page reader wrote the clean dump clean/dumps/matinder/20261125/ (6562 songs). 12706 song pages have no text. About 5% of the texts have no Kazakh letters, probably Russian. |
| `mediastar` | [MediaStar](https://mediastar.kz) | Countries: KAZ | archive | unknown | - | yes | A database of Kazakh songs. A site archive dated 2026-11-16 exists (raw/mediastar/20261116/, 3974 pages). The page reader wrote the clean dump clean/dumps/mediastar/20261125/ (2087 songs). The site gives 75 songs the performer "Жасанды интеллект" (artificial intelligence). |
| `uztext` | Uztext | Countries: KAZ, KGZ, TJK, TKM, UZB | archive | unknown | - | no | A site archive dated 2026-09-13 exists. The address of the site is not confirmed. |
| `uzmatn` | Uzmatn | Countries: KAZ, KGZ, TJK, TKM, UZB | archive | unknown | - | no | A site archive dated 2026-09-13 exists. The address of the site is not confirmed. |

## Kind: manual

| Id | Name | Serves | Routes | Access | Stored copy | Checked | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `review_workbook` | Country review workbook | All countries | manual_review | not_applicable | - | yes | A person adds missing songs to the workbook of a country. Each song keeps the link of the site it came from. |

## Kind: live_site

| Id | Name | Serves | Routes | Access | Stored copy | Checked | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lyricstranslate` | [LyricsTranslate](https://lyricstranslate.com) | All countries | live, roster_update, recover | blocked | - | yes | Not approved for requests (2026-10-04). An index of artist pages exists from earlier runs. |
| `songlyrics` | [SongLyrics](https://www.songlyrics.com) | All countries | live, roster_update, recover | blocked | - | yes | Blocked by a project decision. |
| `azlyrics` | [AZLyrics](https://www.azlyrics.com) | All countries | live, roster_update, recover | blocked | - | yes | The site answers with an access-request page. |
| `lyrhub` | [Lyrhub](https://lyrhub.com) | All countries | live, roster_update, recover | allowed, 1 s between requests | - | no | The countries that this site serves are not confirmed. |
| `buenamusica` | [BuenaMusica](https://www.buenamusica.com) | Languages: Spanish | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `catorze` | [Catorze](https://www.catorze.cat) | Countries: AND, ESP | live, roster_update, recover | allowed, 1 s between requests | - | yes | Songs in Catalan. |
| `lacoccinelle` | [La Coccinelle](https://www.lacoccinelle.net) | Languages: French | live, roster_update, recover | blocked | - | yes | Blocked: live runs returned no rows. |
| `solfegebohio` | [Solfege Bohio](https://solfegebohio.com) | Countries: HTI | live, roster_update, recover | allowed, 1 s between requests | - | no | The country is inferred. |
| `lyricsaz` | [Lyrics.az](https://lyrics.az) | Countries: ATG, BHS, BRB, DMA, GRD, GUY, JAM, KNA, LCA, TTO, VCT | live, roster_update, recover | allowed, 0.75 s between requests | - | no | The list of Caribbean countries is not confirmed. Earlier runs also used it for CIV, CMR and COD. |
| `jahlyrics` | [Jah Lyrics](https://jah-lyrics.com) | Countries: ATG, BHS, BRB, DMA, GRD, GUY, JAM, KNA, LCA, TTO, VCT | live, roster_update, recover | allowed, 0.75 s between requests | - | no | The list of Caribbean countries is not confirmed. |
| `reggaetranslate` | [Reggae Translate](https://reggaetranslate.com) | Countries: ATG, BHS, BRB, DMA, GRD, GUY, JAM, KNA, LCA, TTO, VCT | live, roster_update, recover | allowed, 0.75 s between requests | - | no | The list of Caribbean countries is not confirmed. |
| `socarecords` | [Soca Records](https://socarecords.com) | Countries: ATG, BHS, BRB, DMA, GRD, GUY, JAM, KNA, LCA, TTO, VCT | live, roster_update, recover | allowed, 0.75 s between requests | - | no | The list of Caribbean countries is not confirmed. |
| `lyricsarabic` | [Lyrics-Arabic](https://lyrics-arabic.com) | Languages: Arabic | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `ganjoor` | [Ganjoor](https://ganjoor.net) | Countries: IRN | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `afghansonglyrics` | [Afghan Song Lyrics](https://afghansonglyrics.com) | Countries: AFG | live, roster_update, recover | allowed, 1 s between requests | - | no | The country is inferred from the name. |
| `afghanlyric` | [Afghan Lyric](https://afghanlyric.com) | Countries: AFG | live, roster_update, recover | allowed, 1 s between requests | - | no | The country is inferred from the name. |
| `hebrewsongs` | [HebrewSongs](https://www.hebrewsongs.com) | Countries: ISR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `shironet` | [Shironet](https://shironet.mako.co.il) | Countries: ISR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `alternatifim` | [Alternatifim](https://sarki.alternatifim.com) | Countries: TUR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `bharatlyrics` | [Bharatlyrics](https://bharatlyrics.com) | Countries: IND | live, roster_update, recover | allowed, 1.25 s between requests | - | yes | Text from this source is for local scoring only. |
| `hindigeetmala` | [HindiGeetMala](https://www.hindigeetmala.net) | Countries: IND | live, roster_update, recover | allowed, 1 s between requests | - | yes | Earlier runs used it for ten approved singers only. |
| `bengalisonglyrics4u` | [Bengali Song Lyrics 4U](https://bengalisonglyrics4u.com) | Countries: BGD, IND | live, roster_update, recover | allowed, 1 s between requests | - | no | The countries are inferred. Songs in Bengali. |
| `tagoreweb` | [Tagore Web](https://www.tagoreweb.in) | Countries: BGD, IND | live, roster_update, recover | allowed, 1 s between requests | - | no | The countries are inferred. Songs in Bengali. |
| `gitimala` | [Gitimala](https://gitimala.com) | Countries: BGD, IND | live, roster_update, recover | allowed, 1 s between requests | - | no | The countries are not confirmed. |
| `musiccafenepal` | [Music Cafe Nepal](https://lyrics.musiccafenepal.com) | Countries: NPL | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `nepalilyrics` | [Nepali Lyrics](https://nepalilyrics.net) | Countries: NPL | live, roster_update, recover | allowed, 1 s between requests | - | yes | Public artist pages only. Do not use the search or the API of the site. |
| `lyricslk` | [Lyrics.lk](https://lyrics-lk.com) | Countries: LKA | live, roster_update, recover | allowed, 1 s between requests | - | yes | robots.txt allows / and disallows /api/ and /search. The sitemap lists about 9,200 song pages. A song page names the singer, the lyricist and the composer, and no year. The page reader takes the singer as the artist. |
| `lankawebsites` | [Lanka Websites](https://lankawebsites.com) | Countries: LKA | live, roster_update, recover | allowed, 1 s between requests | - | no | The country is inferred from the name. |
| `mulanci` | [Mulanci](https://www.mulanci.org) | Languages: Chinese | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `qqmusic` | [QQ Music](https://y.qq.com) | Languages: Chinese | live, roster_update, recover | allowed, 1 s between requests | - | yes | Reads the data routes of the site, not its pages. |
| `kugou` | [KuGou](https://www.kugou.com) | Languages: Chinese | live, roster_update, recover | allowed, 1 s between requests | - | yes | Reads the data routes of the site, not its pages. |
| `lyricsasia` | [LyricsAsia](https://lyricsasia.com) | Languages: Chinese | live, roster_update, recover | allowed, 1 s between requests | - | yes | The site also holds songs in Japanese and Korean. |
| `utanet` | [Uta-Net](https://www.uta-net.com) | Countries: JPN | live, roster_update, recover | allowed, 1 s between requests | - | no | The address of the site is inferred. |
| `utaten` | [UtaTen](https://utaten.com) | Countries: JPN | live, roster_update, recover | allowed, 1 s between requests | - | no | The address of the site is inferred. |
| `bugs` | [Bugs](https://music.bugs.co.kr) | Countries: KOR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `genie` | [Genie](https://www.genie.co.kr) | Countries: KOR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `lyricscokr` | [Lyrics.co.kr](https://lyrics.co.kr) | Countries: KOR | live, roster_update, recover | allowed, 1 s between requests | - | yes | The site has an index only, with no artist pages. |
| `kpoplyrics` | [K-Pop Lyrics](https://k-poplyrics.com) | Countries: KOR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `siamzone` | [SiamZone](https://www.siamzone.com) | Countries: THA | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `kapanlagi` | [KapanLagi](https://lirik.kapanlagi.com) | Countries: IDN, MYS | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `lirikid` | [Lirik.id](https://lirik.id) | Countries: IDN | live, roster_update, recover | allowed, 1 s between requests | - | no | The address and the country are inferred. |
| `lyricvn` | [LyricVN](https://lyricvn.com) | Countries: VNM | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `lyricsvn` | [Lyrics.vn](https://lyrics.vn) | Countries: VNM | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `hopamviet` | [Hop Am Viet](https://hopamviet.vn) | Countries: VNM | live | allowed, 2 s between requests | - | yes | Gabriel authorized the crawl on 2026-11-26. robots.txt allows /. Skip /chord/printsong/, /chord/search, /auth/, /user/, and /sheet/download/. |
| `loibaihat` | [Loi bai hat](https://loibaihat.biz) | Countries: VNM | live | allowed, 2 s between requests | - | yes | Gabriel authorized the crawl on 2026-11-26. robots.txt allows /. |
| `hopamchuan` | [Hop Am Chuan](https://hopamchuan.com) | Countries: VNM | live | blocked, 2 s between requests | - | yes | Do not crawl. Every HTML page says a crawl affects guitar players who are using the site, and asks for an API request instead. robots.txt has no Allow or Disallow rule. Gabriel stopped the crawl on 2026-11-26. |
| `musiburma` | [MusiBurma](https://www.musiburma.com) | Countries: MMR | live | allowed, 2 s between requests | - | yes | Gabriel authorized the crawl on 2026-11-26. robots.txt allows /. Skip /api/. |
| `pinoysonghits` | [PinoySongHits](https://www.pinoysonghits.com) | Countries: PHL | live, roster_update, recover | allowed, 60 s between requests | - | yes | The site asks for 60 seconds between requests. |
| `songtexte` | [Songtexte](https://www.songtexte.com) | Languages: German | live, roster_update, recover | allowed, 1 s between requests | - | yes | An index of the site was started and is not complete. |
| `songteksten` | [Songteksten](https://songteksten.net) | Languages: Dutch | live, roster_update, recover | allowed, 1 s between requests | - | no | The address of the site is inferred. |
| `infinititesti` | [InfinitiTesti](https://www.infinititesti.com) | Countries: ITA | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `lyricsmania` | [LyricsMania](https://www.lyricsmania.com) | Countries: ITA | live, roster_update, recover | blocked | - | yes | Suspended: the site banned the client after about 420 pages in 12 minutes. |
| `angolotesti` | [Angolo Testi](https://www.angolotesti.it) | Countries: ITA | live, roster_update, recover | blocked | - | no | Blocked: the site banned the client after about 280 pages. The address is inferred. |
| `bellsirishlyrics` | [Bells Irish Lyrics](https://www.bellsirishlyrics.com) | Countries: IRL | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `glatkistan` | [Glatkistan](https://glatkistan.com) | Countries: ISL | live, roster_update, recover | allowed, 2 s between requests | - | yes | Text from this source is for local scoring only. |
| `tekstowo` | [Tekstowo](https://www.tekstowo.pl) | Countries: POL | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `teksciory` | [Teksciory](https://teksciory.interia.pl) | Countries: POL | live, roster_update, recover | blocked | - | yes | Blocked: live runs returned one row. |
| `supermusic` | [Supermusic](https://supermusic.cz) | Countries: CZE, SVK | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `dalszoveg` | [Dalszoveg](https://www.dalszoveg.hu) | Countries: HUN | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `zeneszoveg` | [Zeneszoveg](https://www.zeneszoveg.hu) | Countries: HUN | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `versurius` | [Versuri.us](https://www.versuri.us) | Countries: ROU | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `textove` | [Textove](https://textove.com) | Countries: BGR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `akordite` | [Akordite](https://akordite.com) | Countries: BGR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `tekstovi` | [Tekstovi.net](https://tekstovi.net) | Countries: BIH, HRV, MKD, MNE, SRB, SVN | live, roster_update, recover | blocked | - | yes | Do not send requests: the site forbids mass download. A site archive dated 2026-09-25 exists, and rows from earlier runs stay. |
| `tekstovipesama` | [Tekstovi Pesama](https://tekstovi-pesama.com) | Countries: BIH, HRV, MKD, MNE, SRB, SVN | live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive dated 2026-09-25 exists. |
| `tekstovipjesama` | [Tekstovi Pjesama](https://tekstovi-pjesama.com) | Countries: BIH, HRV, MKD, MNE, SRB, SVN | live, roster_update, recover | allowed, 1 s between requests | - | yes | A site archive dated 2026-09-25 exists. |
| `hitovi` | [Hitovi.ba](https://hitovi.ba) | Countries: BIH, MNE | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `besedilo` | [Besedilo.si](https://www.besedilo.si) | Countries: SVN | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `slolyrics` | [SloLyrics](https://slolyrics.com) | Countries: SVN | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `pesmi` | [Pesmi.si](https://pesmi.si) | Countries: SVN | live, roster_update, recover | allowed, 1 s between requests | - | no | The address of the site is inferred. |
| `dainutekstai` | [Dainu tekstai](https://www.dainutekstai.lt) | Countries: LTU | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `pisniua` | [Pisni.ua](https://pisni.ua) | Countries: UKR | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `tekstpesnionline` | [Tekst-pesni.online](https://tekst-pesni.online) | Languages: Russian | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |
| `ilyrics` | [iLyrics](https://ru.ilyrics.net) | Languages: Russian | live, roster_update, recover | allowed, 1 s between requests | - | yes | Earlier runs also used it for ARM and IRN. |
| `armlyric` | [ArmLyric](https://armlyric.do.am) | Countries: ARM | live, roster_update, recover | allowed, 1 s between requests | - | yes | Allowed on 2026-10-19 for catalog and song pages only. Do not use the search of the site. Text from this source is for local scoring only. |
| `gitar` | [Gitar.az](https://gitar.az) | Countries: AZE | live, roster_update, recover | allowed, 1 s between requests | - | yes | - |

## Kind: internal

| Id | Name | Serves | Routes | Access | Stored copy | Checked | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `old_pipeline` | State of a country in the earlier pipeline | All countries | old_layout | not_applicable | - | yes | A one-time import of the songs that a country already had. Each song keeps its first source. |

## Sources by country

These sources serve every country: `review_workbook`, `old_pipeline`, `genius`, `lrclib`, `lyricstranslate`, `songlyrics`, `azlyrics`, `lyrhub`. The table lists the other sources. A country that is not in the table has only the sources that serve every country.

| Country | Sources |
| --- | --- |
| AFG | `afghanlyric`, `afghansonglyrics`, `mustext` |
| AGO | `letras` |
| AND | `catorze` |
| ARE | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| ARG | `buenamusica`, `letras`, `musica`, `todotango` |
| ARM | `armlyric`, `geniusru`, `tekstpesni`, `textpesenok` |
| ATG | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| AUT | `songtexte`, `volksmusikdatenbank` |
| AZE | `akkordlar`, `geniusru`, `gitar`, `tekstpesni`, `textpesenok` |
| BDI | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| BEL | `lacoccinelle`, `paroles2chansons`, `parolesnet`, `songteksten` |
| BEN | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| BFA | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| BGD | `bengalisonglyrics4u`, `gitimala`, `tagoreweb` |
| BGR | `akordite`, `bgtekstove`, `pevcheskipodsetnik`, `repertukul`, `textove`, `textovenapesni` |
| BHR | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| BHS | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| BIH | `cuspajz`, `hitovi`, `pesmarica`, `tekstomanija`, `tekstovi`, `tekstovipesama`, `tekstovipjesama` |
| BLR | `geniusru`, `ilyrics`, `tekstpesni`, `tekstpesnionline`, `textpesenok` |
| BOL | `buenamusica`, `letras`, `musica` |
| BRA | `letras` |
| BRB | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| CAF | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| CAN | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| CHE | `lacoccinelle`, `paroles2chansons`, `parolesnet`, `songtexte` |
| CHL | `buenamusica`, `letras`, `musica` |
| CHN | `kugeci`, `kugou`, `lidicity`, `lyricsasia`, `mulanci`, `qqmusic` |
| CIV | `afrikalyrics`, `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| CMR | `afrikalyrics`, `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| COD | `afrikalyrics`, `lacoccinelle`, `lingala_cd`, `ndombolo`, `paroles2chansons`, `parolesnet` |
| COG | `lacoccinelle`, `lingala_cd`, `ndombolo`, `paroles2chansons`, `parolesnet` |
| COL | `buenamusica`, `letras`, `musica` |
| COM | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| CPV | `letras` |
| CRI | `buenamusica`, `letras`, `musica` |
| CUB | `buenamusica`, `letras`, `musica` |
| CYP | `stixoi` |
| CZE | `karaoketexty`, `supermusic` |
| DEU | `deutscheslied`, `lieder_net`, `songtexte` |
| DJI | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| DMA | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| DOM | `buenamusica`, `letras`, `mangulina`, `musica` |
| DZA | `aama`, `aghanilyrics`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| ECU | `buenamusica`, `letras`, `musica` |
| EGY | `aama`, `aghanylyrics`, `altkia`, `arabiclyrics_net`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| ERI | `afrikalyrics`, `tewle` |
| ESP | `buenamusica`, `catorze`, `letras`, `musica` |
| EST | `geniusru`, `tekstpesni`, `textpesenok` |
| ETH | `ethiozeima`, `oromolyrics` |
| FRA | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| GAB | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| GBR | `cuspajz`, `pesmarica` |
| GEO | `geniusru`, `geolyrics`, `georgianlyrics`, `tekstpesni`, `textpesenok` |
| GIN | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| GNB | `letras` |
| GNQ | `buenamusica`, `letras`, `musica` |
| GRC | `local_file`, `stixoi` |
| GRD | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| GTM | `buenamusica`, `letras`, `musica` |
| GUY | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| HKG | `kugeci`, `kugou`, `lidicity`, `lyricsasia`, `mulanci`, `qqmusic` |
| HND | `buenamusica`, `letras`, `musica` |
| HRV | `cuspajz`, `pesmarica`, `tekstomanija`, `tekstovi`, `tekstovipesama`, `tekstovipjesama` |
| HTI | `lacoccinelle`, `paroles2chansons`, `parolesnet`, `solfegebohio`, `wikimizik` |
| HUN | `dalszoveg`, `zeneszoveg` |
| IDN | `kapanlagi`, `lirikid` |
| IND | `bengalisonglyrics4u`, `bharatlyrics`, `giitaayan`, `gitimala`, `hindigeetmala`, `tagoreweb`, `tamilcorpus`, `wikisource` |
| IRL | `bellsirishlyrics` |
| IRN | `ganjoor`, `lyric_erfan`, `musicdel`, `mustext`, `ritmahang`, `satext`, `zibamatn` |
| IRQ | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| ISL | `glatkistan`, `guitarparty`, `musik_is` |
| ISR | `hebrew_lyrics_hf`, `hebrewsongs`, `hngn`, `joinmyjam`, `jyrics`, `shironet`, `tab4u`, `zemereshet` |
| ITA | `angolotesti`, `infinititesti`, `lyricsmania` |
| JAM | `gutenberg_jamaica`, `jahlyrics`, `lyricsaz`, `mentomusic`, `reggaetranslate`, `socarecords` |
| JOR | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| JPN | `utanet`, `utaten` |
| KAZ | `geniusru`, `ilyrics`, `matinder`, `mediastar`, `tekstpesni`, `tekstpesnionline`, `textpesenok`, `uzmatn`, `uztext` |
| KEN | `bongolyrics` |
| KGZ | `geniusru`, `ilyrics`, `kyrgyzaudio`, `tekstpesni`, `tekstpesnionline`, `textpesenok`, `uzmatn`, `uztext` |
| KNA | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| KOR | `bugs`, `genie`, `kpoplyrics`, `lyricscokr` |
| KWT | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| LBN | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| LBY | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| LCA | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| LKA | `lankawebsites`, `lyricslk` |
| LTU | `dainutekstai`, `dainuzodziai`, `geniusru`, `tekstpesni`, `textpesenok` |
| LUX | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| LVA | `geniusru`, `tekstpesni`, `textpesenok` |
| MAC | `kugou`, `lyricsasia`, `mulanci`, `qqmusic` |
| MAR | `aama`, `aghanilyrics`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| MCO | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| MDA | `geniusru`, `sergiudo`, `tekstpesni`, `textpesenok` |
| MDG | `lacoccinelle`, `paroles2chansons`, `parolesnet`, `tononkira` |
| MEX | `buenamusica`, `letras`, `musica` |
| MKD | `cuspajz`, `pesmarica`, `tekstomanija`, `tekstovi`, `tekstovipesama`, `tekstovipjesama` |
| MLI | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| MMR | `musiburma` |
| MNE | `cuspajz`, `hitovi`, `pesmarica`, `tekstomanija`, `tekstovi`, `tekstovipesama`, `tekstovipjesama` |
| MOZ | `letras` |
| MRT | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| MYS | `kapanlagi`, `nlb_sg` |
| NER | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| NGA | `afrikalyrics`, `ninejalyrics`, `tooxclusive` |
| NIC | `buenamusica`, `letras`, `musica` |
| NLD | `songteksten` |
| NPL | `musiccafenepal`, `nepalilyrics` |
| OMN | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| PAN | `buenamusica`, `letras`, `musica` |
| PER | `buenamusica`, `letras`, `musica` |
| PHL | `opmtunes`, `pinoysonghits` |
| POL | `teksciory`, `tekstowo` |
| PRI | `buenamusica`, `letras`, `musica` |
| PRT | `letras` |
| PRY | `buenamusica`, `letras`, `musica` |
| PSE | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| QAT | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| ROU | `versurius` |
| RUS | `geniusru`, `ilyrics`, `tekstpesni`, `tekstpesnionline`, `textpesenok` |
| RWA | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| SAU | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| SDN | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| SEN | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| SGP | `nlb_sg` |
| SLV | `buenamusica`, `letras`, `musica` |
| SRB | `cuspajz`, `pesmarica`, `tekstomanija`, `tekstovi`, `tekstovipesama`, `tekstovipjesama` |
| STP | `letras` |
| SUR | `songteksten` |
| SVK | `karaoketexty`, `supermusic`, `zoznam_hudba` |
| SVN | `besedilo`, `cuspajz`, `pesmi`, `slolyrics`, `tekstomanija`, `tekstovi`, `tekstovipesama`, `tekstovipjesama` |
| SYR | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| TCD | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| TGO | `lacoccinelle`, `paroles2chansons`, `parolesnet` |
| THA | `deungdutjai`, `siamzone` |
| TJK | `geniusru`, `mustext`, `tekstpesni`, `textpesenok`, `uzmatn`, `uztext` |
| TKM | `geniusru`, `tekstpesni`, `textpesenok`, `uzmatn`, `uztext` |
| TLS | `letras` |
| TTO | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| TUN | `aama`, `aghanilyrics`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `lyricstn`, `songnu`, `tarab_hf` |
| TUR | `alternatifim`, `repertukul`, `sarkisozum`, `turkish_folk_kaggle` |
| TWN | `kugeci`, `kugou`, `lyricsasia`, `mulanci`, `pmdb_taipei`, `qqmusic` |
| TZA | `bongolyrics` |
| UGA | `howwe` |
| UKR | `geniusru`, `nashe_com_ua`, `pisni_org_ua`, `pisniua`, `tekstpesni`, `textpesenok` |
| URY | `buenamusica`, `hmpu_uy`, `jaimeroos`, `letras`, `musica`, `todotango` |
| USA | `cuspajz`, `pesmarica` |
| UZB | `geniusru`, `tekstpesni`, `textpesenok`, `uzmatn`, `uztext` |
| VCT | `jahlyrics`, `lyricsaz`, `reggaetranslate`, `socarecords` |
| VEN | `buenamusica`, `letras`, `musica` |
| VNM | `amnhacmiennam`, `hopamchuan`, `hopamviet`, `loibaihat`, `lyricsvn`, `lyricvn`, `nhac_vn`, `nhaccuatui`, `tkaraoke` |
| YEM | `aama`, `aghanylyrics`, `altkia`, `fnanen`, `kalimat_anghami`, `lyricsarabic`, `songnu`, `tarab_hf` |
| ZAF | `kasilyrics` |
| ZMB | `zedlyric` |

## Languages

A working table: the countries where a source in that language is worth a run. It is not a list of official languages.

| Code | Language | Countries |
| --- | --- | --- |
| ar | Arabic | ARE, BHR, DZA, EGY, IRQ, JOR, KWT, LBN, LBY, MAR, MRT, OMN, PSE, QAT, SAU, SDN, SYR, TUN, YEM |
| de | German | AUT, CHE, DEU |
| es | Spanish | ARG, BOL, CHL, COL, CRI, CUB, DOM, ECU, ESP, GNQ, GTM, HND, MEX, NIC, PAN, PER, PRI, PRY, SLV, URY, VEN |
| fr | French | BDI, BEL, BEN, BFA, CAF, CAN, CHE, CIV, CMR, COD, COG, COM, DJI, FRA, GAB, GIN, HTI, LUX, MCO, MDG, MLI, NER, RWA, SEN, TCD, TGO |
| nl | Dutch | BEL, NLD, SUR |
| pt | Portuguese | AGO, BRA, CPV, GNB, MOZ, PRT, STP, TLS |
| ru | Russian | BLR, KAZ, KGZ, RUS |
| zh | Chinese | CHN, HKG, MAC, TWN |
