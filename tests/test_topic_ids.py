from songs.stage_30_topics import topic_ids as t


def test_counts():
    assert len(t.TOPIC_IDS) == 38
    assert len(t.FAMILY_LABELS) == 7
    assert set(t.TOPIC_LABELS) == set(t.TOPIC_IDS)
    assert all(label.strip() for label in t.TOPIC_LABELS.values())
    assert all(label.strip() for label in t.FAMILY_LABELS.values())


def test_every_topic_has_exactly_one_family():
    members = [topic_id for topics in t.FAMILY_TOPIC_IDS.values() for topic_id in topics]
    assert sorted(members) == sorted(t.TOPIC_IDS)
    assert set(t.FAMILY_TOPIC_IDS) == set(t.FAMILY_LABELS)
    assert set(t.FAMILY_BY_TOPIC_ID) == set(t.TOPIC_IDS)


def test_display_order_is_a_permutation():
    assert sorted(t.TOPIC_DISPLAY_IDS) == list(t.TOPIC_IDS)
    assert t.FAMILY_BY_TOPIC_ID["T27"] == "G"


def test_generated_page_is_current():
    on_disk = t.TOPICS_PAGE.read_text(encoding="utf-8")
    assert on_disk == t.render_topics_markdown(), (
        "docs/standards/topics.md is out of date. "
        "Run: python -m songs.stage_30_topics.topic_ids --write"
    )
