from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

import youtube_live_monitor as monitor
from youtube_live_monitor import (
    MonitorError,
    State,
    YouTubeClient,
    extract_video_id,
    load_config,
    normalize,
    sender_lines,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://youtu.be/AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://www.youtube.com/watch?v=AbCdEfGhI12&t=10", "AbCdEfGhI12"),
        ("youtube.com/live/AbCdEfGhI12", "AbCdEfGhI12"),
        ("https://www.youtube.com/embed/AbCdEfGhI12", "AbCdEfGhI12"),
    ],
)
def test_extract_video_id(value: str, expected: str) -> None:
    assert extract_video_id(value) == expected


def test_extract_video_id_rejects_invalid_value() -> None:
    with pytest.raises(MonitorError, match="Video ID inválido"):
        extract_video_id("https://example.com/not-a-video")


def write_config(tmp_path: Path, *, enabled: object = True) -> Path:
    lives = tmp_path / "lives.yaml"
    lives.write_text(yaml.safe_dump({"lives": [{"url": "AbCdEfGhI12", "enabled": enabled}]}))
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "youtube": {"api_key": "fake-api-key"},
                "collector": {"interval": 15, "timeout": 10, "retries": 2},
                "zabbix": {"port": 10051},
                "lives_file": str(lives),
            }
        )
    )
    return config


def test_load_config_reads_external_lives_and_adaptive_defaults(tmp_path: Path) -> None:
    config = load_config(str(write_config(tmp_path)))
    assert config["lives"] == [{"enabled": True, "url": "AbCdEfGhI12"}]
    assert config["collector"]["interval"] == 15
    assert config["collector"]["batch_size"] == 50
    assert config["collector"]["schedule_poll"]["more_than_24h"] == 21600


def test_load_config_rejects_quoted_boolean(tmp_path: Path) -> None:
    with pytest.raises(MonitorError, match="sem aspas"):
        load_config(str(write_config(tmp_path, enabled="false")))


def test_environment_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "key-from-environment")
    monkeypatch.setenv("ZABBIX_PORT", "10052")
    config = load_config(str(write_config(tmp_path)))
    assert config["youtube"]["api_key"] == "key-from-environment"
    assert config["zabbix"]["port"] == 10052


def youtube_item(*, broadcast: str, started: str | None = None, ended: str | None = None) -> dict[str, Any]:
    details: dict[str, str] = {
        "scheduledStartTime": "2026-07-15T15:00:00Z",
        "scheduledEndTime": "2026-07-15T17:00:00Z",
    }
    if started:
        details["actualStartTime"] = started
        details["concurrentViewers"] = "321"
    if ended:
        details["actualEndTime"] = ended
    return {
        "id": "AbCdEfGhI12",
        "snippet": {
            "channelId": "UC0000000000000000000000",
            "channelTitle": "Canal de teste",
            "title": "Live de teste",
            "liveBroadcastContent": broadcast,
        },
        "statistics": {"viewCount": "1000", "likeCount": "75", "commentCount": "12"},
        "liveStreamingDetails": details,
    }


def test_normalize_exposes_public_metrics_and_statuses() -> None:
    upcoming = normalize("AbCdEfGhI12", youtube_item(broadcast="upcoming"), 0.1, 200)
    live = normalize(
        "AbCdEfGhI12", youtube_item(broadcast="live", started="2026-07-15T15:00:00Z"), 0.1, 200
    )
    ended = normalize(
        "AbCdEfGhI12",
        youtube_item(broadcast="none", started="2026-07-15T15:00:00Z", ended="2026-07-15T16:30:00Z"),
        0.1,
        200,
    )
    assert upcoming["status"] == 1
    assert live["status"] == 2
    assert ended["status"] == 3
    assert live["total_views"] == 1000
    assert live["like_count"] == 75
    assert live["comment_count"] == 12
    assert live["scheduled_end"] == "2026-07-15T17:00:00Z"
    assert live["viewer_count_available"] == 1


def sample_info(viewers: int, views: int, likes: int = 50) -> dict[str, Any]:
    return {
        "video_id": "AbCdEfGhI12",
        "channel_id": "UC0000000000000000000000",
        "channel_name": "Canal de teste",
        "title": "Live de teste",
        "scheduled_start": "1970-01-01T00:15:00Z",
        "scheduled_end": "",
        "actual_start": "1970-01-01T00:15:00Z",
        "actual_end": "",
        "status": 2,
        "concurrent_viewers": viewers,
        "total_views": views,
        "like_count": likes,
        "comment_count": 5,
    }


def test_state_persists_peak_average_and_deltas(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    state = State(str(database))
    first = state.update("AbCdEfGhI12", sample_info(100, 1000), 1000.0)
    second = state.update("AbCdEfGhI12", sample_info(160, 1100, 60), 1060.0)
    assert first["peak_viewers"] == 100
    assert second["peak_viewers"] == 160
    assert second["average_viewers"] == 130
    assert second["viewer_change_per_minute"] == 60
    assert second["new_views_per_minute"] == 100
    assert second["likes_per_minute"] == 10
    assert second["viewer_change_percent"] == 60
    state.close()

    reopened = State(str(database))
    third = reopened.update("AbCdEfGhI12", sample_info(120, 1150, 65), 1120.0)
    assert third["peak_viewers"] == 160
    assert third["average_viewers"] == pytest.approx(126.6666667)
    reopened.close()


def test_state_calculates_views_and_likes_when_viewer_count_is_hidden(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    first = {**sample_info(100, 1000, 50), "concurrent_viewers": None}
    second = {**sample_info(100, 1120, 62), "concurrent_viewers": None}
    state.update("AbCdEfGhI12", first, 1000.0)
    result = state.update("AbCdEfGhI12", second, 1060.0)
    assert result["new_views_per_minute"] == 120
    assert result["likes_per_minute"] == 12
    assert result["average_viewers"] == 0
    state.close()


def test_state_migrates_v12_database(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    db = sqlite3.connect(database)
    db.execute(
        """CREATE TABLE lives (video_id TEXT PRIMARY KEY, channel_id TEXT, channel_name TEXT, title TEXT,
        scheduled_start TEXT, actual_start TEXT, actual_end TEXT, status INTEGER NOT NULL DEFAULT 0,
        last_view_count INTEGER, last_concurrent_viewers INTEGER, peak_viewers INTEGER NOT NULL DEFAULT 0,
        viewer_sum INTEGER NOT NULL DEFAULT 0, viewer_samples INTEGER NOT NULL DEFAULT 0, last_collection REAL)"""
    )
    db.execute(
        "CREATE TABLE samples (video_id TEXT NOT NULL, collected_at REAL NOT NULL, viewers INTEGER, views INTEGER, PRIMARY KEY(video_id,collected_at))"
    )
    db.commit()
    db.close()
    state = State(str(database))
    columns = {row["name"] for row in state.db.execute("PRAGMA table_info(lives)")}
    assert {"last_like_count", "last_comment_count", "peak_timestamp", "scheduled_end"} <= columns
    state.close()


def collector_config() -> dict[str, Any]:
    return {
        "interval": 15,
        "unknown_interval": 300,
        "error_backoff_initial": 300,
        "error_backoff_max": 3600,
        "schedule_poll": dict(monitor.DEFAULT_POLL_POLICY),
    }


@pytest.mark.parametrize(
    ("seconds_until_start", "expected"),
    [(90000, 21600), (30000, 3600), (7200, 900), (1800, 300), (600, 60), (-10, 30)],
)
def test_adaptive_schedule_intervals(seconds_until_start: int, expected: int) -> None:
    now = 1_700_000_000.0
    scheduled = datetime.fromtimestamp(now + seconds_until_start, timezone.utc).isoformat().replace("+00:00", "Z")
    info = {"status": 1, "scheduled_start": scheduled}
    assert State.next_interval(info, collector_config(), now) == expected


def test_live_interval_and_ended_finalization(tmp_path: Path) -> None:
    state = State(str(tmp_path / "state.db"))
    now = 1000.0
    state.mark_success("AbCdEfGhI12", {"status": 2}, collector_config(), now)
    assert not state.is_due("AbCdEfGhI12", now + 14)
    assert state.is_due("AbCdEfGhI12", now + 15)
    state.mark_success("AbCdEfGhI12", {"status": 3}, collector_config(), now + 15)
    assert not state.is_due("AbCdEfGhI12", now + 10_000_000)
    state.close()


def test_error_backoff_is_persistent(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    state = State(str(database))
    state.mark_failure("AbCdEfGhI12", collector_config(), 1000)
    assert not state.is_due("AbCdEfGhI12", 1299)
    assert state.is_due("AbCdEfGhI12", 1300)
    state.mark_failure("AbCdEfGhI12", collector_config(), 1300)
    state.close()
    reopened = State(str(database))
    assert not reopened.is_due("AbCdEfGhI12", 1899)
    assert reopened.is_due("AbCdEfGhI12", 1900)
    reopened.close()


def test_get_many_uses_one_request_for_multiple_ids() -> None:
    class Response:
        status_code = 200

        def __init__(self, ids: list[str]):
            self.ids = ids

        def json(self) -> dict[str, Any]:
            return {"items": [{"id": video_id} for video_id in self.ids]}

    class Session:
        calls = 0
        requested_ids = ""

        def get(self, *_args: Any, **kwargs: Any) -> Response:
            self.calls += 1
            self.requested_ids = kwargs["params"]["id"]
            return Response(self.requested_ids.split(","))

    client = YouTubeClient("fake-api-key", timeout=1, retries=0)
    session = Session()
    client.session = session  # type: ignore[assignment]
    result, _, _ = client.get_many(["AbCdEfGhI12", "XyZ98765432"])
    assert set(result) == {"AbCdEfGhI12", "XyZ98765432"}
    assert session.calls == 1
    assert session.requested_ids == "AbCdEfGhI12,XyZ98765432"


def test_quota_error_is_not_retried() -> None:
    class Response:
        status_code = 403

        @staticmethod
        def json() -> dict[str, Any]:
            return {"error": {"message": "YouTube API quota exceeded"}}

    class Session:
        calls = 0

        def get(self, *_args: Any, **_kwargs: Any) -> Response:
            self.calls += 1
            return Response()

    client = YouTubeClient("fake-api-key", timeout=1, retries=4)
    session = Session()
    client.session = session  # type: ignore[assignment]
    with pytest.raises(MonitorError, match="quota indisponível"):
        client.get("AbCdEfGhI12")
    assert session.calls == 1


def test_sender_omits_audience_metrics_before_live() -> None:
    info = {
        "video_id": "AbCdEfGhI12",
        "status": 1,
        "title": "Futura",
        "total_views": 1000,
        "like_count": 50,
        "concurrent_viewers": None,
    }
    lines = sender_lines("youtube-channel-test", "AbCdEfGhI12", info)
    assert any(",status]" in line for line in lines)
    assert any(",title]" in line for line in lines)
    assert not any(",total_views]" in line for line in lines)
    assert not any(",like_count]" in line for line in lines)


def test_sender_includes_new_metrics_while_live() -> None:
    info = {
        "video_id": "AbCdEfGhI12",
        "status": 2,
        "like_count": 50,
        "comment_count": 5,
        "engagement_rate": 2.5,
    }
    lines = sender_lines("youtube-channel-test", "AbCdEfGhI12", info)
    assert any(",like_count]" in line for line in lines)
    assert any(",comment_count]" in line for line in lines)
    assert any(",engagement_rate]" in line for line in lines)


def test_cycle_batches_due_lives_and_defers_scheduled_ones(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1_700_000_000.0
    scheduled = datetime.fromtimestamp(now + 7200, timezone.utc).isoformat().replace("+00:00", "Z")

    class Client:
        request_count = 0
        batches: list[list[str]] = []

        def get_many(self, ids: list[str]) -> tuple[dict[str, dict[str, Any]], float, int]:
            self.request_count += 1
            self.batches.append(ids)
            items = {}
            for video_id in ids:
                item = youtube_item(broadcast="upcoming")
                item["id"] = video_id
                item["liveStreamingDetails"]["scheduledStartTime"] = scheduled
                items[video_id] = item
            return items, 0.1, 200

    class Provisioner:
        def ensure(self, _info: dict[str, Any]) -> tuple[str, str]:
            return "youtube-channel-test", "1"

    cfg = {
        "youtube": {"api_key": "fake"},
        "collector": {**collector_config(), "timeout": 10, "retries": 0, "batch_size": 50},
        "zabbix": {},
        "lives": [
            {"url": "AbCdEfGhI12", "enabled": True},
            {"url": "XyZ98765432", "enabled": True},
        ],
    }
    sent: list[list[str]] = []
    monkeypatch.setattr(monitor.time, "time", lambda: now)
    monkeypatch.setattr(monitor, "send_batch", lambda lines, _zabbix: sent.append(lines))
    state = State(str(tmp_path / "state.db"))
    client = Client()

    assert monitor.cycle(cfg, state, client=client, provisioner=Provisioner()) == 0  # type: ignore[arg-type]
    assert client.batches == [["AbCdEfGhI12", "XyZ98765432"]]
    assert client.request_count == 1

    assert monitor.cycle(cfg, state, client=client, provisioner=Provisioner()) == 0  # type: ignore[arg-type]
    assert client.request_count == 1
    assert state.counter("scheduled_polls_skipped") == 2
    assert len(sent) == 2
    state.close()


def test_dashboard_is_portable_and_repeats_each_live() -> None:
    dashboard_path = Path(__file__).parents[1] / "grafana_dashboard_youtube_live.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    assert dashboard["apiVersion"] == "dashboard.grafana.app/v2"
    assert dashboard["metadata"] == {"name": "youtube-live-monitor"}
    first_row = dashboard["spec"]["layout"]["spec"]["rows"][0]["spec"]
    assert first_row["repeat"] == {"mode": "variable", "value": "live"}
    datasource = dashboard["spec"]["variables"][0]["spec"]["current"]
    assert datasource == {"text": "", "value": ""}
    serialized = json.dumps(dashboard)
    assert "createdBy" not in serialized
    assert "updatedBy" not in serialized
    assert "/var/lib/grafana" not in serialized
