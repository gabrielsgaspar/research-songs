"""The Pesni.net reader keeps only the original text of the requested song."""

from songs.stage_00_ingest import pesninet


def test_original_text_and_page_identity():
    url = "https://www.pesni.net/text/test-band/test-song"
    html = f"""<div class="song-page" data-quote-artist-value="Test Band"
        data-quote-title-value="A Test" data-quote-url-value="{url}">
        <div class="song-block-text">A blue jar<br>A green cup</div>
        <div class="song-meaning">An invented explanation</div></div>"""
    row, artists, reason = pesninet.parse_song(html, url)
    assert not reason
    assert artists == [("test-band", "Test Band")]
    assert row["song_name"] == "A Test"
    assert row["lyrics"] == "A blue jar\nA green cup"
    assert pesninet.parse_song(html, url + "-other")[2] == "not_song_page"
    assert pesninet.song_id("https://other.example/text/test-band/test-song") is None
    assert pesninet.song_id("https://www.pesni.net/text/test-band") is None
    assert pesninet.parse_song("<div class='song-meaning'>Only a summary</div>", url)[2] == (
        "no_lyric_block"
    )
