from hft_research.normalized_cache import CACHE_FORMAT, cached_events, metadata, write_cache
from research_lab.storage import Event


def test_normalized_cache_preserves_event_order_and_provenance(tmp_path):
    path = tmp_path / "tape.sqlite3"
    events = [
        Event(4, 10, None, "market", {"market": {"ticker": "KXBTC15M-A"}}, "a"),
        Event(2, 10, 9, "ws", {"frame": {"type": "trade"}}, "b"),
    ]
    result = write_cache(path, events, {"main": ["raw-main"], "trade": ["raw-trade"]})
    assert result["format"] == CACHE_FORMAT
    assert result["event_count"] == 2
    assert metadata(path)["source"] == {"main": ["raw-main"], "trade": ["raw-trade"]}
    assert list(cached_events(path)) == events


def test_normalized_cache_refuses_to_overwrite(tmp_path):
    path = tmp_path / "tape.sqlite3"
    write_cache(path, [], {"main": [], "trade": []})
    try:
        write_cache(path, [], {"main": [], "trade": []})
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected immutable cache to reject overwrite")
