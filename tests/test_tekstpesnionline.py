from songs.stage_00_ingest import tekstpesnionline as site


def test_only_original_lyric_paragraphs_and_all_named_singers():
    url = "https://naizust.com/first-second-sample/"
    html = """<h1>First, Second &#8212; Sample</h1>
    <h2>Слушать First, Second — Sample</h2><p>Player</p>
    <h2>Текст First, Second — Sample</h2><p>Invented light<br />Invented road</p>
    <p>Invented sky</p><div>Video</div><p>Unrelated text</p>"""
    row, artists, reason = site.parse_song(html, url)
    assert not reason
    assert row["lyrics"] == "Invented light\nInvented road\n\nInvented sky"
    assert row["song_name"] == "Sample"
    assert artists == [(None, "First"), (None, "Second")]
    assert site.parse_song(html.replace("Текст", "Перевод"), url)[2] == "no_lyric_block"
    assert site.canonicalize(url.rstrip("/")) == url
    assert site.canonicalize(url.replace("naizust.com", "example.org")) is None
    assert site.crawl_urls(html, url) == []
