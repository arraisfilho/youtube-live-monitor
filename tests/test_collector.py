from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests
import yaml

import backend.collector as monitor
from backend.collector import MonitorError, State, YouTubeClient, extract_video_id, load_config, normalize

VID = "AbCdEfGhI12"
VID2 = "XyZ98765432"
NOW = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc).timestamp()
SECRET = "AIzaFAKE-SECRET-TEST-KEY-000000000000"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://youtu.be/AbCdEfGhI12?si=x", "AbCdEfGhI12"),
        ("https://www.youtube.com/watch?v=AbCdEfGhI12&t=10", "AbCdEfGhI12"),
        ("youtube.com/live/AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://www.youtube.com/embed/AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://music.youtube.com/watch?v=AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://www.youtube-nocookie.com/embed/AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://studio.youtube.com/video/AbCdEfGhI12/livestreaming", "AbCdEfGhI12"),
        ("https://m.youtube.com/shorts/AbCdEfGhI12", "AbCdEfGhI12"),
    ],
)
def test_extract_video_id(value: str, expected: str) -> None:
    assert extract_video_id(value) == expected


def test_extract_video_id_rejects_invalid_value() -> None:
    with pytest.raises(MonitorError, match="Video ID inválido"):
        extract_video_id("https://example.com/not-a-video")



def test_load_config_without_file_uses_defaults() -> None:
    config = load_config(None)
    assert config["lives"] == []
    assert config["collector"]["batch_size"] == 50
    assert config["collector"]["schedule_poll"]["overdue_after_48h"] == 21600
    assert config["exporter"] == {"listen": "127.0.0.1", "port": 9877}
    assert config["youtube"] == {"daily_quota": 10000, "api_key": ""}


def test_load_config_reads_advanced_settings(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"collector": {"retries": 4}, "exporter": {"listen": "0.0.0.0"}}))
    config = load_config(str(config_file))
    assert config["collector"]["retries"] == 4 and config["exporter"]["listen"] == "0.0.0.0"


def test_load_config_rejects_invalid_values(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"collector": {"batch_size": 80}}))
    with pytest.raises(MonitorError, match="batch_size"):
        load_config(str(config_file))


def youtube_item(video_id: str = VID, *, broadcast: str, scheduled: float = NOW, started: float | None = None,
                 ended: float | None = None, viewers: int | None = 321) -> dict[str, Any]:
    details: dict[str, str] = {"scheduledStartTime": iso(scheduled), "scheduledEndTime": iso(scheduled + 7200)}
    if started is not None:
        details["actualStartTime"] = iso(started)
        if viewers is not None and ended is None:
            details["concurrentViewers"] = str(viewers)
    if ended is not None:
        details["actualEndTime"] = iso(ended)
    return {
        "id": video_id,
        "snippet": {"channelId": "UC0000000000000000000000", "channelTitle": "Canal de teste",
                    "title": "Live de teste", "liveBroadcastContent": broadcast},
        "statistics": {"viewCount": "1000", "likeCount": "75", "commentCount": "12"},
        "liveStreamingDetails": details,
    }


def test_normalize_exposes_public_metrics_and_statuses() -> None:
    upcoming = normalize(VID, youtube_item(broadcast="upcoming"), 0.1, 200, NOW)
    live = normalize(VID, youtube_item(broadcast="live", started=NOW), 0.1, 200, NOW)
    ended = normalize(VID, youtube_item(broadcast="none", started=NOW, ended=NOW + 60), 0.1, 200, NOW)
    assert (upcoming["status"], live["status"], ended["status"]) == (1, 2, 3)
    assert live["total_views"] == 1000 and live["like_count"] == 75 and live["comment_count"] == 12
    assert live["concurrent_viewers"] == 321 and live["viewer_count_available"] == 1


def collector_config(interval: float = 15) -> dict[str, Any]:
    return {
        "interval": interval, "unknown_interval": 300, "unavailable_interval": 1800,
        "error_backoff_initial": 300, "error_backoff_max": 3600, "batch_size": 50, "log_api_state": False,
        "schedule_poll": dict(monitor.DEFAULT_POLL_POLICY),
    }


def sample_info(viewers: int | None, views: int, likes: int = 50, comments: int = 5) -> dict[str, Any]:
    return {
        "video_id": VID, "channel_id": "UC0", "channel_name": "Canal", "title": "Live",
        "scheduled_start": "1970-01-01T00:15:00Z", "scheduled_end": "", "actual_start": "1970-01-01T00:15:00Z",
        "actual_end": "", "status": 2, "concurrent_viewers": viewers, "total_views": views,
        "like_count": likes, "comment_count": comments,
    }


def test_state_persists_peak_average_and_deltas(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    state = State(str(database))
    first = state.update(VID, sample_info(100, 1000), collector_config(), 1000.0)
    second = state.update(VID, sample_info(160, 1100, 60, 8), collector_config(), 1060.0)
    state.db.commit()
    assert first["peak_viewers"] == 100
    assert second["peak_viewers"] == 160
    assert second["average_viewers"] == 130
    assert second["viewer_change_per_minute"] == 60
    assert second["new_views_per_minute"] == 100
    assert second["likes_per_minute"] == 10
    assert second["comments_per_minute"] == 3
    assert second["viewer_change_percent"] == 60
    assert second["views_since_start"] == 100
    state.close()
    reopened = State(str(database))
    third = reopened.update(VID, sample_info(120, 1150, 65), collector_config(), 1120.0)
    assert third["peak_viewers"] == 160
    assert third["average_viewers"] == pytest.approx(126.6666667)
    reopened.close()


def test_hidden_audience_does_not_report_zero_peak_or_average(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    state.update(VID, sample_info(None, 1000, 50), collector_config(), 1000.0)
    result = state.update(VID, sample_info(None, 1120, 62), collector_config(), 1060.0)
    assert result["new_views_per_minute"] == 120
    assert result["likes_per_minute"] == 12
    assert result["peak_viewers"] is None and result["average_viewers"] is None
    state.close()


def test_rates_follow_a_longer_interval(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    state.update(VID, sample_info(100, 1000), collector_config(120), 1000.0)
    result = state.update(VID, sample_info(200, 1500), collector_config(120), 1120.0)
    assert result["viewer_change_per_minute"] == 50
    state.close()


def test_state_adds_missing_columns(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    db = sqlite3.connect(database)
    db.execute(
        """CREATE TABLE lives (video_id TEXT PRIMARY KEY, channel_id TEXT, channel_name TEXT, title TEXT,
        scheduled_start TEXT, actual_start TEXT, actual_end TEXT, status INTEGER NOT NULL DEFAULT 0,
        last_view_count INTEGER, last_concurrent_viewers INTEGER, peak_viewers INTEGER NOT NULL DEFAULT 0,
        viewer_sum INTEGER NOT NULL DEFAULT 0, viewer_samples INTEGER NOT NULL DEFAULT 0, last_collection REAL)"""
    )
    db.execute(
        "CREATE TABLE samples (video_id TEXT NOT NULL, collected_at REAL NOT NULL, viewers INTEGER, "
        "views INTEGER, PRIMARY KEY(video_id,collected_at))"
    )
    db.commit()
    db.close()
    state = State(str(database))
    columns = {row["name"] for row in state.db.execute("PRAGMA table_info(lives)")}
    assert {"peak_timestamp", "scheduled_end", "first_view_count", "snapshot"} <= columns
    state.close()


@pytest.mark.parametrize(
    ("seconds_until_start", "expected"),
    [(90000, 21600), (30000, 3600), (7200, 900), (1800, 300), (600, 60), (-10, 30),
     (-7200, 300), (-30000, 3600), (-200000, 21600)],
)
def test_adaptive_schedule_intervals(seconds_until_start: int, expected: int) -> None:
    info = {"status": 1, "scheduled_start": iso(NOW + seconds_until_start)}
    assert State.next_interval(info, collector_config(), NOW) == expected


def test_live_interval_and_ended_finalization(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    state.mark_success(VID, {"status": 2}, collector_config(), 1000.0)
    assert not state.is_due(VID, 1014) and state.is_due(VID, 1015)
    state.mark_success(VID, {"status": 3, "actual_end": "2026-01-01T00:00:00Z"}, collector_config(), 1015.0)
    assert not state.is_due(VID, 10_000_000)
    state.close()


def test_ended_without_end_time_needs_a_second_reading(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    state.mark_success(VID, {"status": 3}, collector_config(), 1000.0)
    assert state.is_due(VID, 1060)
    state.mark_success(VID, {"status": 3}, collector_config(), 1060.0)
    assert not state.is_due(VID, 10_000_000)
    state.close()


def test_error_backoff_is_persistent(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    state = State(str(database))
    state.mark_failure(VID, collector_config(), 1000)
    assert not state.is_due(VID, 1299) and state.is_due(VID, 1300)
    state.mark_failure(VID, collector_config(), 1300)
    state.db.commit()
    state.close()
    reopened = State(str(database))
    assert not reopened.is_due(VID, 1899) and reopened.is_due(VID, 1900)
    reopened.close()


def test_quota_day_follows_pacific_midnight(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    before_utc_midnight = datetime(2026, 10, 15, 23, 59, tzinfo=timezone.utc).timestamp()
    after_utc_midnight = datetime(2026, 10, 16, 0, 1, tzinfo=timezone.utc).timestamp()
    state.record_api_calls(5000, 5000, before_utc_midnight)
    state.record_api_calls(10, 10, after_utc_midnight)
    assert state.api_calls_today(after_utc_midnight) == 5010
    reset = monitor.next_quota_reset(after_utc_midnight)
    assert datetime.fromtimestamp(reset, timezone.utc) == datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)
    state.close()


class FakeClient:
    def __init__(self, items: dict[str, dict[str, Any]], error: Exception | None = None):
        self.items = items
        self.error = error
        self.request_count = 0
        self.batches: list[list[str]] = []

    def get_many(self, ids: list[str], _key: str) -> tuple[dict[str, dict[str, Any]], float, int]:
        self.request_count += 1
        self.batches.append(ids)
        if self.error:
            raise self.error
        return {i: self.items[i] for i in ids if i in self.items}, 0.1, 200


def cycle_config(*ids: str) -> dict[str, Any]:
    return {
        "youtube": {"api_key": "fake", "daily_quota": 10000},
        "collector": {**collector_config(), "timeout": 10, "retries": 0},
        "display_timezone": "America/Sao_Paulo",
        "lives": [{"url": i, "video_id": i, "enabled": True} for i in ids],
    }


def test_cycle_batches_due_lives_and_defers_scheduled_ones(tmp_path: Path) -> None:
    items = {i: youtube_item(i, broadcast="upcoming", scheduled=NOW + 7200) for i in (VID, VID2)}
    client = FakeClient(items)
    state = State(str(tmp_path / "state.db"))
    cfg = cycle_config(VID, VID2)
    assert monitor.cycle(cfg, state, client, now=NOW) == 0  # type: ignore[arg-type]
    assert client.batches == [[VID, VID2]]
    assert monitor.cycle(cfg, state, client, now=NOW + 15) == 0  # type: ignore[arg-type]
    assert client.request_count == 1
    assert state.counter("scheduled_polls_skipped") == 2
    state.close()


def test_missing_video_becomes_unavailable_without_counting_errors(tmp_path: Path) -> None:
    client = FakeClient({})
    state = State(str(tmp_path / "state.db"))
    cfg = cycle_config(VID)
    for step in range(24 * 60 * 4):
        monitor.cycle(cfg, state, client, now=NOW + step * 15)  # type: ignore[arg-type]
    health = state.health([VID], NOW + 86400)
    assert health["consecutive_errors"] == 0 and health["lives"]["unavailable"] == 1
    assert client.request_count == 48
    state.close()


def test_quota_exhaustion_pauses_until_pacific_midnight(tmp_path: Path) -> None:
    client = FakeClient({}, error=monitor.QuotaExceeded("quota"))
    state = State(str(tmp_path / "state.db"))
    cfg = cycle_config(VID)
    monitor.cycle(cfg, state, client, now=NOW)  # type: ignore[arg-type]
    monitor.cycle(cfg, state, client, now=NOW + 3600)  # type: ignore[arg-type]
    assert client.request_count == 1
    assert state.counter("quota_paused_until") == monitor.next_quota_reset(NOW) + 120
    assert state.is_due(VID, monitor.next_quota_reset(NOW) + 121)
    state.close()


def test_abandoned_scheduled_live_backs_off(tmp_path: Path) -> None:
    client = FakeClient({VID: youtube_item(broadcast="upcoming", scheduled=NOW - 3 * 86400)})
    state = State(str(tmp_path / "state.db"))
    for step in range(24 * 60 * 4):
        monitor.cycle(cycle_config(VID), state, client, now=NOW + step * 15)  # type: ignore[arg-type]
    assert client.request_count <= 5
    state.close()


class FailingAdapter(requests.adapters.BaseAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[requests.PreparedRequest] = []

    def send(self, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        self.requests.append(request)
        response = requests.Response()
        response.status_code = 503
        response.url = request.url or ""
        response._content = b'{"error": {"message": "backend error", "errors": [{"reason": "backendError"}]}}'
        response.request = request
        return response

    def close(self) -> None:
        pass


def test_api_key_travels_in_header_and_never_reaches_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(monitor.time, "sleep", lambda _s: None)
    client = YouTubeClient(timeout=1, retries=1)
    adapter = FailingAdapter()
    client.session.mount("https://www.googleapis.com", adapter)
    cfg = cycle_config(VID)
    cfg["youtube"]["api_key"] = SECRET
    caplog.set_level(logging.ERROR)
    monitor.cycle(cfg, State(str(tmp_path / "s.db")), client, now=NOW)
    assert len(adapter.requests) == 2
    assert adapter.requests[0].headers["X-Goog-Api-Key"] == SECRET
    assert SECRET not in (adapter.requests[0].url or "")
    assert "backendError" in caplog.text and SECRET not in caplog.text


def test_quota_error_is_not_retried() -> None:
    class Response:
        status_code = 403

        @staticmethod
        def json() -> dict[str, Any]:
            return {"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}}

    class Session:
        calls = 0

        def get(self, *_args: Any, **_kwargs: Any) -> Response:
            self.calls += 1
            return Response()

    client = YouTubeClient(timeout=1, retries=4)
    session = Session()
    client.session = session  # type: ignore[assignment]
    with pytest.raises(monitor.QuotaExceeded):
        client.get_many([VID], "fake")
    assert session.calls == 1


def test_metrics_exposition_keeps_state_visible(tmp_path: Path) -> None:
    items = {
        VID: youtube_item(VID, broadcast="live", scheduled=NOW - 600, started=NOW - 600),
        VID2: youtube_item(VID2, broadcast="upcoming", scheduled=NOW + 30 * 3600),
    }
    items[VID]["snippet"]["title"] = 'Live "especial" (ao vivo)'
    state = State(str(tmp_path / "s.db"))
    cfg = cycle_config(VID, VID2)
    monitor.cycle(cfg, state, FakeClient(items), now=NOW)  # type: ignore[arg-type]
    text = monitor.render_metrics(cfg, state, NOW + 3600)
    assert f'youtube_live_status{{video_id="{VID2}"}} 1' in text
    assert f'youtube_live_concurrent_viewers{{video_id="{VID}"}} 321' in text
    assert f'youtube_live_seconds_until_start{{video_id="{VID2}"}} {29 * 3600}' in text
    assert "live=\"Live 'especial' (ao vivo) — 15/10/2026\"" in text
    assert 'youtube_collector_lives{status="live"} 1' in text
    assert "fake" not in text


def test_evening_live_uses_display_timezone(tmp_path: Path) -> None:
    scheduled = datetime(2026, 10, 16, 0, 30, tzinfo=timezone.utc).timestamp()  # 21:30 in UTC-3
    state = State(str(tmp_path / "s.db"))
    cfg = cycle_config(VID)
    monitor.cycle(cfg, state, FakeClient({VID: youtube_item(broadcast="upcoming", scheduled=scheduled)}),  # type: ignore[arg-type]
                  now=NOW)
    assert "— 15/10/2026" in monitor.render_metrics(cfg, state, NOW)
    state.close()
