"""The page reader of the Georgian lyric site `georgianlyrics`, for `site_pages.parse_folder`.

The site is a blog. A song is a post; its tags name genres, places and people. The tags
do not say if a person sings, wrote the music or wrote the words, so every person tag is
a credit of the song, in page order.
"""

import re
from html.parser import HTMLParser
from urllib.parse import unquote

from songs.stage_00_ingest import site_pages
from songs.stage_00_ingest.dump_match import name_key

SOURCE = "georgianlyrics"
BASE = "https://georgianlyrics.com"
COLUMNS = (
    "provider_song_id",
    "song_url",
    "song_name",
    "artist_name",
    "artist_url",
    "lyrics",
    "text_kind",
    "language_label",
    "release_year_raw",
    "retrieved_at_utc",
)
# The categories of song posts: song texts and chants.
_SONG = re.compile(re.escape(BASE) + r"/((?:სიმღერის-ტექსტი|საგალობელი)/[^/?#]+)/")
_TAG = re.compile(re.escape(BASE) + r"/tag/([^/?#]+)/")
# Tags that name a genre, a form, a theme, a place or an occasion, not a person or a group.
NOT_PEOPLE = frozenset(
    {
        "საესტრადო",
        "სატრფიალო",
        "სალაღობო",
        "ქალაქური",
        "სიმღერა ფილმიდან",
        "ხალხური",
        "საბავშვო",
        "რომანსი",
        "საგალობელი",
        "ჰიმნი",
        "ცოცხალი შესრულება",
        "მეგრული",
        "რაჭული",
        "კახური",
        "ბალადა",
        "სერენადა",
        "იავნანა",
        "ბაიათი",
        "აკაპელა",
        "ალილო",
        "საშობაო",
        "აღდგომა",
        "ახალი წელი",
        "თბილისობა",
        "წერილი",
        "ზუმბა",
        "შვიდკაცა",
        "უცნობი",
        "საქართველო",
        "თბილისი",
        "ქუთაისი",
        "ბათუმი",
        "სოხუმი",
        "რუსთავი",
        "კახეთი",
        "ვაკის პარკი",
    }
)


class _Page(HTMLParser):
    """Read the post title, the paragraphs of the post body and the tag links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.post = False
        self.title = ""
        self.lines: list[str] | None = None
        self.tags: list[tuple[str, str]] = []
        self._in_title = self._in_tags = self._in_paragraph = self._done = False
        self._depth = 0
        self._href: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag == "body":
            self.post = "single-post" in classes
        elif tag == "div" and self._in_body():
            self._depth += 1
            self._done = "sharedaddy" in classes or "jp-relatedposts" in classes
        elif tag == "div" and "entry-content" in classes and self.lines is None:
            self.lines, self._depth = [], 1
        elif tag == "div" and "taxonomy-post_tag" in classes:
            self._in_tags = True
        elif tag == "h1" and "wp-block-post-title" in classes:
            self._in_title = True
        elif tag == "p" and self._in_body():
            self._in_paragraph = True
            self.lines += ["", ""]
        elif tag == "br" and self._in_paragraph:
            self.lines.append("")
        elif tag == "a" and self._in_tags:
            self._href, self._text = found.get("href") or "", ""

    def _in_body(self) -> bool:
        return self.lines is not None and not self._done

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_body():
            self._depth -= 1
            self._done = self._depth == 0
        elif tag == "div":
            self._in_tags = False
        elif tag == "h1":
            self._in_title = False
        elif tag == "p":
            self._in_paragraph = False
        elif tag == "a" and self._href is not None:
            found = _TAG.fullmatch(self._href)
            name = " ".join(self._text.split())
            if found and name:
                self.tags.append((unquote(found[1]), name))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        elif self._in_title:
            self.title += data
        elif self._in_paragraph and self._in_body():
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the song id (`<category>/<slug>`, decoded) of a song post URL, or None."""
    found = _SONG.fullmatch(unquote(url))
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the credited people (tag, name) of a post and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if not page.post or page.lines is None:
        return None, [], "no_lyric_block"
    people = [tag for tag in dict.fromkeys(page.tags) if tag[1] not in NOT_PEOPLE]
    title = " ".join(page.title.split())
    lyrics = site_pages.lyric_text(page.lines)
    if not people:
        return None, [], "no_artist"
    if not title:
        return None, [], "no_title"
    if not name_key(lyrics):
        return None, [], "empty_text"
    row = dict.fromkeys(COLUMNS)
    row.update(
        provider_song_id=song_id(url),
        song_url=url,
        song_name=title,
        artist_name=people[0][1],
        artist_url=f"{BASE}/tag/{people[0][0]}/",
        lyrics=lyrics,
        text_kind="lyrics",
    )
    return row, people, ""
