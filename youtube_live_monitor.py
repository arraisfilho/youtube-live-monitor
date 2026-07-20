#!/usr/bin/env python3
"""Monitor public YouTube live streams and forward metrics to Zabbix."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import requests
import yaml

VERSION = "1.3.2"
DEFAULT_CONFIG = "/etc/youtube-live-monitor/config.yaml"
DEFAULT_DB = "/var/lib/youtube-live-monitor/state.db"


class MonitorError(RuntimeError):
    """Configuration or integration error with a user-actionable message."""


STATUS = {"unknown": 0, "scheduled": 1, "live": 2, "ended": 3}

# name: (Zabbix label, value_type, units)
METRICS: dict[str, tuple[str, int, str]] = {
    "concurrent_viewers": ("Concurrent viewers", 3, "viewers"),
    "peak_viewers": ("Peak viewers", 3, "viewers"),
    "average_viewers": ("Average viewers", 0, "viewers"),
    "viewer_change_per_minute": ("Viewer change per minute", 0, "viewers/min"),
    "viewer_change_percent": ("Viewer change percent", 0, "%"),
    "total_views": ("Total views", 3, "views"),
    "new_views_per_minute": ("New views per minute", 0, "views/min"),
    "like_count": ("Likes", 3, "likes"),
    "likes_per_minute": ("New likes per minute", 0, "likes/min"),
    "comment_count": ("Comments", 3, "comments"),
    "engagement_rate": ("Engagement rate", 0, "%"),
    "status": ("Status", 3, ""),
    "elapsed_seconds": ("Elapsed time", 3, "s"),
    "scheduled_delay_seconds": ("Start delay", 0, "s"),
    "time_to_peak_seconds": ("Time to peak", 3, "s"),
    "peak_timestamp": ("Peak timestamp", 3, "unixtime"),
    "viewer_count_available": ("Viewer count available", 3, ""),
    "title": ("Title", 4, ""),
    "channel_name": ("Channel name", 4, ""),
    "channel_id": ("Channel ID", 4, ""),
    "video_id": ("Video ID", 4, ""),
    "scheduled_start": ("Scheduled start", 4, ""),
    "scheduled_end": ("Scheduled end", 4, ""),
    "actual_start": ("Actual start", 4, ""),
    "actual_end": ("Actual end", 4, ""),
    "last_update": ("Last update", 3, "unixtime"),
    "api_latency": ("API latency", 0, "s"),
    "api_status": ("API status", 3, ""),
}

PRELIVE_METRICS = {
    "status",
    "title",
    "channel_name",
    "channel_id",
    "video_id",
    "scheduled_start",
    "scheduled_end",
    "actual_start",
    "actual_end",
    "last_update",
    "api_latency",
    "api_status",
    "viewer_count_available",
}

COLLECTOR_METRICS: dict[str, tuple[str, int, str]] = {
    "api_calls_total": ("YouTube API calls total", 3, "calls"),
    "api_calls_today": ("YouTube API calls today", 3, "calls"),
    "videos_per_batch": ("Videos per API call", 0, "videos"),
    "scheduled_polls_skipped": ("Scheduled polls skipped", 3, "polls"),
    "last_success_age": ("Age of last successful poll", 3, "s"),
    "consecutive_errors": ("Maximum consecutive errors", 3, ""),
    "cycle_duration": ("Collector cycle duration", 0, "s"),
    "zabbix_sender_failures": ("Zabbix sender failures", 3, "failures"),
    "db_size_bytes": ("State database size", 3, "B"),
    "enabled_lives": ("Enabled lives", 3, "lives"),
    "scheduled_lives": ("Scheduled lives", 3, "lives"),
    "live_lives": ("Live streams", 3, "lives"),
    "ended_lives": ("Ended lives", 3, "lives"),
}

DEFAULT_POLL_POLICY = {
    "more_than_24h": 21600,
    "more_than_6h": 3600,
    "more_than_1h": 900,
    "more_than_15m": 300,
    "near_start": 60,
    "overdue": 30,
}


def parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def extract_video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split(":", 1)[0]
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            candidate = parts[1] if len(parts) > 1 and parts[0] in {"live", "shorts", "embed"} else ""
    else:
        candidate = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise MonitorError(f"Video ID inválido: {value}")
    return candidate


video_id_from = extract_video_id


def _positive_number(value: Any, path: str, *, minimum: float = 0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} deve ser numérico") from exc
    if result < minimum:
        raise ValueError(f"{path} deve ser >= {minimum:g}")
    return result


def normalize_live_entries(entries: Any, source: str) -> list[dict[str, Any]]:
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise MonitorError(f"A lista de lives em {source} deve ser uma lista YAML")
    normalized = []
    for index, live in enumerate(entries, start=1):
        if isinstance(live, str):
            live = {"url": live}
        if not isinstance(live, dict) or not live.get("url"):
            raise MonitorError(f"Live inválida em {source}, posição {index}")
        enabled = live.get("enabled", True)
        if not isinstance(enabled, bool):
            raise MonitorError(f"enabled deve ser true ou false sem aspas em {source}, posição {index}")
        extract_video_id(str(live["url"]))
        normalized.append({**live, "enabled": enabled})
    return normalized


def load_lives_file(path: str) -> list[dict[str, Any]]:
    lives_path = Path(path)
    if not lives_path.is_absolute():
        raise MonitorError("lives_file deve usar um caminho absoluto")
    if not lives_path.is_file():
        raise MonitorError(f"Arquivo de lives não encontrado: {path}")
    data = yaml.safe_load(lives_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("lives", []), list):
        raise MonitorError("lives_file deve conter uma lista 'lives'")
    return normalize_live_entries(data.get("lives", []), path)


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).resolve()
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MonitorError(f"Não foi possível ler {path}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise MonitorError("A raiz do YAML deve ser um mapa")
    for section in ("youtube", "collector", "zabbix"):
        cfg.setdefault(section, {})
        if not isinstance(cfg[section], dict):
            raise MonitorError(f"A seção {section} deve ser um mapa YAML")
    env_map = {
        "YOUTUBE_API_KEY": ("youtube", "api_key", str),
        "ZABBIX_SERVER": ("zabbix", "server", str),
        "ZABBIX_PORT": ("zabbix", "port", int),
        "ZABBIX_API_URL": ("zabbix", "api_url", str),
        "ZABBIX_API_TOKEN": ("zabbix", "api_token", str),
    }
    for env, (section, key, cast) in env_map.items():
        if env in os.environ:
            try:
                cfg[section][key] = cast(os.environ[env])
            except ValueError as exc:
                raise MonitorError(f"Valor inválido em {env}") from exc
    if os.environ.get("YOUTUBE_LIVES_FILE"):
        cfg["lives_file"] = os.environ["YOUTUBE_LIVES_FILE"]
    collector = cfg.setdefault("collector", {})
    collector.setdefault("interval", 15)
    collector.setdefault("timeout", 10)
    collector.setdefault("retries", 2)
    collector.setdefault("batch_size", 50)
    collector.setdefault("unknown_interval", 300)
    collector.setdefault("error_backoff_initial", 300)
    collector.setdefault("error_backoff_max", 3600)
    collector.setdefault("log_api_state", False)
    policy = collector.setdefault("schedule_poll", {})
    if not isinstance(policy, dict):
        raise ValueError("collector.schedule_poll deve ser um mapa")
    for key, default in DEFAULT_POLL_POLICY.items():
        policy.setdefault(key, default)

    collector["interval"] = _positive_number(collector["interval"], "collector.interval", minimum=5)
    collector["timeout"] = _positive_number(collector["timeout"], "collector.timeout", minimum=1)
    collector["retries"] = int(_positive_number(collector["retries"], "collector.retries"))
    collector["batch_size"] = int(_positive_number(collector["batch_size"], "collector.batch_size", minimum=1))
    if collector["batch_size"] > 50:
        raise ValueError("collector.batch_size deve estar entre 1 e 50")
    collector["unknown_interval"] = _positive_number(
        collector["unknown_interval"], "collector.unknown_interval", minimum=30
    )
    collector["error_backoff_initial"] = _positive_number(
        collector["error_backoff_initial"], "collector.error_backoff_initial", minimum=30
    )
    collector["error_backoff_max"] = _positive_number(
        collector["error_backoff_max"], "collector.error_backoff_max", minimum=30
    )
    if collector["error_backoff_max"] < collector["error_backoff_initial"]:
        raise ValueError("collector.error_backoff_max deve ser >= error_backoff_initial")
    if not isinstance(collector["log_api_state"], bool):
        raise ValueError("collector.log_api_state deve ser true ou false sem aspas")
    for key in DEFAULT_POLL_POLICY:
        policy[key] = _positive_number(policy[key], f"collector.schedule_poll.{key}", minimum=15)

    zabbix = cfg.setdefault("zabbix", {})
    zabbix.setdefault("server", "127.0.0.1")
    zabbix.setdefault("port", 10051)
    zabbix.setdefault("sender_path", "/usr/bin/zabbix_sender")
    try:
        zabbix["port"] = int(zabbix["port"])
    except (TypeError, ValueError) as exc:
        raise MonitorError("zabbix.port deve ser inteiro") from exc
    if not 1 <= zabbix["port"] <= 65535:
        raise MonitorError("zabbix.port fora do intervalo válido")
    zabbix["tls_connect"] = str(zabbix.get("tls_connect", "unencrypted")).lower()
    if zabbix["tls_connect"] not in {"unencrypted", "psk", "cert"}:
        raise ValueError("zabbix.tls_connect deve ser unencrypted, psk ou cert")

    lives: list[dict[str, Any]] = []
    if cfg.get("lives_file"):
        lives_path = Path(str(cfg["lives_file"]))
        if not lives_path.is_absolute():
            lives_path = config_path.parent / lives_path
        lives.extend(load_lives_file(str(lives_path.resolve())))
    lives.extend(normalize_live_entries(cfg.get("lives", []), path))

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for live in lives:
        video_id = extract_video_id(str(live["url"]))
        if video_id in seen:
            continue
        seen.add(video_id)
        normalized.append({**live, "enabled": live.get("enabled", True)})
    cfg["lives"] = normalized
    if not cfg["youtube"].get("api_key"):
        raise MonitorError("youtube.api_key ou YOUTUBE_API_KEY é obrigatório")
    return cfg


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS lives (
                video_id TEXT PRIMARY KEY, channel_id TEXT, channel_name TEXT, title TEXT,
                scheduled_start TEXT, actual_start TEXT, actual_end TEXT,
                status INTEGER NOT NULL DEFAULT 0, last_view_count INTEGER,
                last_concurrent_viewers INTEGER, peak_viewers INTEGER NOT NULL DEFAULT 0,
                viewer_sum INTEGER NOT NULL DEFAULT 0, viewer_samples INTEGER NOT NULL DEFAULT 0,
                last_collection REAL, last_like_count INTEGER, last_comment_count INTEGER,
                peak_timestamp REAL, scheduled_end TEXT
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS samples (
                video_id TEXT, collected_at REAL, viewers INTEGER, views INTEGER, likes INTEGER
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS poll_schedule (
                video_id TEXT PRIMARY KEY, next_poll REAL NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0,
                last_attempt REAL, last_success REAL, last_status INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS collector_counters (
                key TEXT PRIMARY KEY, value REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS api_usage (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self._ensure_column("lives", "last_like_count", "INTEGER")
        self._ensure_column("lives", "last_comment_count", "INTEGER")
        self._ensure_column("lives", "peak_timestamp", "REAL")
        self._ensure_column("lives", "scheduled_end", "TEXT")
        self._ensure_column("samples", "likes", "INTEGER")
        self._ensure_column("poll_schedule", "last_status", "INTEGER NOT NULL DEFAULT 0")
        self.db.execute("CREATE INDEX IF NOT EXISTS samples_lookup ON samples(video_id, collected_at)")
        self.db.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self) -> None:
        self.db.close()

    def is_due(self, video_id: str, now: float) -> bool:
        row = self.db.execute(
            "SELECT next_poll, finalized FROM poll_schedule WHERE video_id=?", (video_id,)
        ).fetchone()
        return row is None or (not row["finalized"] and row["next_poll"] <= now)

    def is_adaptively_deferred(self, video_id: str, now: float) -> bool:
        row = self.db.execute(
            "SELECT next_poll, finalized FROM poll_schedule WHERE video_id=?", (video_id,)
        ).fetchone()
        return bool(row and not row["finalized"] and row["next_poll"] > now)

    def last_status(self, video_id: str) -> int | None:
        row = self.db.execute(
            "SELECT last_status FROM poll_schedule WHERE video_id=?", (video_id,)
        ).fetchone()
        if row is not None:
            return int(row["last_status"])
        row = self.db.execute("SELECT status FROM lives WHERE video_id=?", (video_id,)).fetchone()
        return int(row["status"]) if row is not None else None

    def mark_attempt(self, video_id: str, now: float) -> None:
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, last_attempt) VALUES(?, ?)
               ON CONFLICT(video_id) DO UPDATE SET last_attempt=excluded.last_attempt""",
            (video_id, now),
        )
        self.db.commit()

    @staticmethod
    def next_interval(info: dict[str, Any], collector: dict[str, Any], now: float) -> float:
        status = int(info.get("status", 0))
        if status == STATUS["live"]:
            return float(collector["interval"])
        if status == STATUS["scheduled"]:
            scheduled = parse_iso(info.get("scheduled_start"))
            if scheduled is None:
                return float(collector["unknown_interval"])
            until = scheduled - now
            policy = collector["schedule_poll"]
            if until > 86400:
                return float(policy["more_than_24h"])
            if until > 21600:
                return float(policy["more_than_6h"])
            if until > 3600:
                return float(policy["more_than_1h"])
            if until > 900:
                return float(policy["more_than_15m"])
            if until > 0:
                return float(policy["near_start"])
            return float(policy["overdue"])
        return float(collector["unknown_interval"])

    def mark_success(self, video_id: str, info: dict[str, Any], collector: dict[str, Any], now: float) -> None:
        ended = int(info.get("status", 0)) == STATUS["ended"]
        next_poll = now + self.next_interval(info, collector, now)
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, next_poll, failure_count, finalized,
                                            last_attempt, last_success, last_status)
               VALUES(?, ?, 0, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET next_poll=excluded.next_poll,
                   failure_count=0, finalized=excluded.finalized,
                   last_attempt=excluded.last_attempt, last_success=excluded.last_success,
                   last_status=excluded.last_status""",
            (video_id, next_poll, int(ended), now, now, int(info.get("status", 0))),
        )
        self.db.commit()

    def mark_failure(self, video_id: str, collector: dict[str, Any], now: float) -> None:
        row = self.db.execute(
            "SELECT failure_count FROM poll_schedule WHERE video_id=?", (video_id,)
        ).fetchone()
        failures = (int(row["failure_count"]) if row else 0) + 1
        delay = min(
            float(collector["error_backoff_max"]),
            float(collector["error_backoff_initial"]) * (2 ** (failures - 1)),
        )
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, next_poll, failure_count, last_attempt)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET next_poll=excluded.next_poll,
                   failure_count=excluded.failure_count, last_attempt=excluded.last_attempt""",
            (video_id, now + delay, failures, now),
        )
        self.db.commit()

    def record_api_calls(self, calls: int, now: float) -> None:
        if calls <= 0:
            return
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        self.db.execute(
            """INSERT INTO api_usage(day, calls) VALUES(?, ?)
               ON CONFLICT(day) DO UPDATE SET calls=calls+excluded.calls""",
            (day, calls),
        )
        self.increment("api_calls_total", calls, now, commit=False)
        self.db.commit()

    def increment(self, key: str, amount: float = 1, now: float | None = None, *, commit: bool = True) -> None:
        now = now or time.time()
        self.db.execute(
            """INSERT INTO collector_counters(key, value, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=value+excluded.value, updated_at=excluded.updated_at""",
            (key, amount, now),
        )
        if commit:
            self.db.commit()

    def counter(self, key: str) -> float:
        row = self.db.execute("SELECT value FROM collector_counters WHERE key=?", (key,)).fetchone()
        return float(row["value"]) if row else 0.0

    def update(self, video_id: str, info: dict[str, Any], now: float) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM lives WHERE video_id=?", (video_id,)).fetchone()
        viewers = info.get("concurrent_viewers")
        views = info.get("total_views")
        likes = info.get("like_count")
        comments = info.get("comment_count")
        is_live = int(info.get("status", 0)) == STATUS["live"]
        audience_sample = is_live and viewers is not None

        peak = int(row["peak_viewers"]) if row else 0
        total = float(row["viewer_sum"]) if row else 0.0
        samples = int(row["viewer_samples"]) if row else 0
        peak_timestamp = float(row["peak_timestamp"]) if row and row["peak_timestamp"] is not None else None

        if audience_sample:
            if peak_timestamp is None or int(viewers) > peak:
                peak = int(viewers)
                peak_timestamp = now
            total += int(viewers)
            samples += 1

        previous = self.db.execute(
            """SELECT viewers, views, likes, collected_at FROM samples
               WHERE video_id=? AND collected_at BETWEEN ? AND ?
               ORDER BY ABS(collected_at-?) LIMIT 1""",
            (video_id, now - 90, now - 45, now - 60),
        ).fetchone()
        viewer_delta = views_delta = likes_delta = None
        viewer_percent = None
        if previous and is_live:
            minutes = max((now - float(previous["collected_at"])) / 60.0, 0.01)
            if viewers is not None and previous["viewers"] is not None:
                viewer_delta = (int(viewers) - int(previous["viewers"])) / minutes
                if int(previous["viewers"]) > 0:
                    viewer_percent = (int(viewers) - int(previous["viewers"])) * 100.0 / int(previous["viewers"])
            if views is not None and previous["views"] is not None:
                views_delta = max(0.0, (int(views) - int(previous["views"])) / minutes)
            if likes is not None and previous["likes"] is not None:
                likes_delta = max(0.0, (int(likes) - int(previous["likes"])) / minutes)

        if is_live and any(value is not None for value in (viewers, views, likes)):
            self.db.execute(
                "INSERT OR REPLACE INTO samples(video_id, collected_at, viewers, views, likes) VALUES(?,?,?,?,?)",
                (video_id, now, viewers, views, likes),
            )
            self.db.execute("DELETE FROM samples WHERE collected_at < ?", (now - 172800,))

        self.db.execute(
            """INSERT INTO lives(video_id, channel_id, channel_name, title, scheduled_start,
                                  scheduled_end, actual_start, actual_end, status, last_view_count,
                                  last_concurrent_viewers, peak_viewers, viewer_sum, viewer_samples,
                                  last_collection, last_like_count, last_comment_count, peak_timestamp)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,
                   channel_name=excluded.channel_name, title=excluded.title,
                   scheduled_start=excluded.scheduled_start, scheduled_end=excluded.scheduled_end,
                   actual_start=excluded.actual_start, actual_end=excluded.actual_end,
                   status=excluded.status, last_view_count=excluded.last_view_count,
                   last_concurrent_viewers=excluded.last_concurrent_viewers,
                   peak_viewers=excluded.peak_viewers, viewer_sum=excluded.viewer_sum,
                   viewer_samples=excluded.viewer_samples, last_collection=excluded.last_collection,
                   last_like_count=excluded.last_like_count,
                   last_comment_count=excluded.last_comment_count,
                   peak_timestamp=excluded.peak_timestamp""",
            (
                video_id, info.get("channel_id"), info.get("channel_name"), info.get("title"),
                info.get("scheduled_start"), info.get("scheduled_end"), info.get("actual_start"),
                info.get("actual_end"), info.get("status", 0), views, viewers, peak, total, samples,
                now, likes, comments, peak_timestamp,
            ),
        )
        self.db.commit()

        scheduled = parse_iso(info.get("scheduled_start"))
        actual = parse_iso(info.get("actual_start"))
        actual_end = parse_iso(info.get("actual_end"))
        scheduled_delay = actual - scheduled if scheduled is not None and actual is not None else None
        elapsed_target = actual_end if actual_end is not None else now
        elapsed = max(0, int(elapsed_target - actual)) if actual is not None else 0
        time_to_peak = max(0, int(peak_timestamp - actual)) if peak_timestamp is not None and actual is not None else None
        engagement = (int(likes) * 100.0 / int(views)) if likes is not None and views else None
        return {
            "peak_viewers": peak,
            "average_viewers": total / samples if samples else 0,
            "viewer_change_per_minute": viewer_delta,
            "viewer_change_percent": viewer_percent,
            "new_views_per_minute": views_delta,
            "likes_per_minute": likes_delta,
            "engagement_rate": engagement,
            "elapsed_seconds": elapsed,
            "scheduled_delay_seconds": scheduled_delay,
            "peak_timestamp": int(peak_timestamp) if peak_timestamp is not None else None,
            "time_to_peak_seconds": time_to_peak,
        }

    def health(self, video_ids: list[str], now: float, cycle_duration: float, due_count: int, api_calls: int) -> dict[str, Any]:
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        today = self.db.execute("SELECT calls FROM api_usage WHERE day=?", (day,)).fetchone()
        placeholders = ",".join("?" for _ in video_ids)
        rows = (
            self.db.execute(
                f"SELECT failure_count, last_success, last_status FROM poll_schedule WHERE video_id IN ({placeholders})",
                video_ids,
            ).fetchall()
            if video_ids
            else []
        )
        statuses = [int(row["last_status"]) for row in rows]
        successes = [float(row["last_success"]) for row in rows if row["last_success"] is not None]
        db_size = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.path}{suffix}")
            if candidate.exists():
                db_size += candidate.stat().st_size
        return {
            "api_calls_total": int(self.counter("api_calls_total")),
            "api_calls_today": int(today["calls"]) if today else 0,
            "videos_per_batch": due_count / api_calls if api_calls else 0,
            "scheduled_polls_skipped": int(self.counter("scheduled_polls_skipped")),
            "last_success_age": int(now - max(successes)) if successes else None,
            "consecutive_errors": max((int(row["failure_count"]) for row in rows), default=0),
            "cycle_duration": cycle_duration,
            "zabbix_sender_failures": int(self.counter("zabbix_sender_failures")),
            "db_size_bytes": db_size,
            "enabled_lives": len(video_ids),
            "scheduled_lives": statuses.count(STATUS["scheduled"]),
            "live_lives": statuses.count(STATUS["live"]),
            "ended_lives": statuses.count(STATUS["ended"]),
        }


class YouTubeClient:
    def __init__(self, api_key: str, timeout: float, retries: int):
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.request_count = 0

    def get_many(self, video_ids: list[str]) -> tuple[dict[str, dict[str, Any]], float, int]:
        if not video_ids or len(video_ids) > 50:
            raise ValueError("get_many requer entre 1 e 50 IDs")
        params = {
            "part": "snippet,statistics,liveStreamingDetails,status",
            "id": ",".join(video_ids),
            "key": self.api_key,
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            try:
                self.request_count += 1
                response = self.session.get(
                    "https://www.googleapis.com/youtube/v3/videos", params=params, timeout=self.timeout
                )
                latency = time.monotonic() - started
                reason = self._reason(response)
                if response.status_code == 403 and "quota" in reason.lower():
                    raise MonitorError(f"YouTube API: quota indisponível: {reason}")
                if response.status_code in {403, 404}:
                    raise MonitorError(f"YouTube API HTTP {response.status_code}: {reason}")
                if response.status_code not in {200, 429} and response.status_code < 500:
                    raise MonitorError(f"YouTube API HTTP {response.status_code}: {reason}")
                if response.status_code != 200:
                    response.raise_for_status()
                items = response.json().get("items", [])
                return {item["id"]: item for item in items}, latency, response.status_code
            except (requests.RequestException, RuntimeError, MonitorError) as exc:
                last_error = exc
                if isinstance(exc, MonitorError) or "quota" in str(exc).lower() or attempt >= self.retries:
                    break
                time.sleep(min(2**attempt, 5))
        if isinstance(last_error, MonitorError):
            raise last_error
        raise MonitorError(f"Falha na YouTube Data API: {last_error}")

    @staticmethod
    def _reason(response: requests.Response) -> str:
        try:
            error = response.json().get("error", {})
            return str(error.get("message") or error.get("errors", [{}])[0].get("reason") or "erro desconhecido")
        except (ValueError, IndexError, AttributeError):
            return "resposta inválida"

    def get(self, video_id: str) -> tuple[dict[str, Any], float, int]:
        items, latency, status = self.get_many([video_id])
        if video_id not in items:
            raise MonitorError(f"Vídeo não encontrado ou não público: {video_id}")
        return items[video_id], latency, status


def normalize(video_id: str, item: dict[str, Any], latency: float, api_status: int) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    details = item.get("liveStreamingDetails", {})
    broadcast = snippet.get("liveBroadcastContent")
    if details.get("actualEndTime"):
        state = "ended"
    elif broadcast == "live":
        state = "live"
    elif broadcast == "upcoming":
        state = "scheduled"
    elif broadcast == "none" and details.get("actualStartTime"):
        state = "ended"
    elif details.get("actualStartTime"):
        state = "live"
    elif details.get("scheduledStartTime"):
        state = "scheduled"
    else:
        state = "unknown"

    def integer(source: dict[str, Any], key: str) -> int | None:
        value = source.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "channel_name": snippet.get("channelTitle", ""),
        "channel_id": snippet.get("channelId", ""),
        "concurrent_viewers": integer(details, "concurrentViewers"),
        "viewer_count_available": int(details.get("concurrentViewers") is not None),
        "total_views": integer(statistics, "viewCount"),
        "like_count": integer(statistics, "likeCount"),
        "comment_count": integer(statistics, "commentCount"),
        "status": STATUS[state],
        "scheduled_start": details.get("scheduledStartTime", ""),
        "scheduled_end": details.get("scheduledEndTime", ""),
        "actual_start": details.get("actualStartTime", ""),
        "actual_end": details.get("actualEndTime", ""),
        "last_update": int(time.time()),
        "api_latency": round(latency, 3),
        "api_status": api_status,
    }


def api_state_snapshot(
    video_id: str,
    item: dict[str, Any],
    info: dict[str, Any],
    previous_status: int | None = None,
) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    details = item.get("liveStreamingDetails", {})
    status_names = {value: key for key, value in STATUS.items()}
    current_status = int(info["status"])
    return {
        "video_id": video_id,
        "status_anterior": previous_status,
        "status_normalizado": current_status,
        "status_nome": status_names.get(current_status, "unknown"),
        "liveBroadcastContent": snippet.get("liveBroadcastContent"),
        "scheduledStartTime": details.get("scheduledStartTime"),
        "actualStartTime": details.get("actualStartTime"),
        "actualEndTime": details.get("actualEndTime"),
        "concurrentViewers": details.get("concurrentViewers"),
        "activeLiveChatId": details.get("activeLiveChatId"),
    }


class ZabbixAPI:
    def __init__(self, url: str, token: str, verify_tls: bool = True):
        self.url = url if url.rstrip("/").endswith("api_jsonrpc.php") else url.rstrip("/") + "/api_jsonrpc.php"
        self.token = token
        self.verify_tls = verify_tls
        self.session = requests.Session()
        self.request_id = 0

    def call(self, method: str, params: Any) -> Any:
        self.request_id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.request_id}
        headers = {"Content-Type": "application/json-rpc", "Authorization": f"Bearer {self.token}"}
        response = self.session.post(self.url, json=payload, headers=headers, timeout=15, verify=self.verify_tls)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            message = body["error"].get("data") or body["error"].get("message")
            raise RuntimeError(f"Zabbix API {method}: {message}")
        return body["result"]


class Provisioner:
    def __init__(self, api: ZabbixAPI):
        self.api = api
        self.group_id = self._ensure_host_group("YouTube Live Monitor")
        self.template_group_id = self._ensure_template_group("YouTube Live Monitor")
        self.template_id = self._ensure_template("YouTube Live Monitor")
        self.status_map_id = self._ensure_status_map()
        self.cache: dict[str, tuple[str, str]] = {}
        self.collector_host_id = self._ensure_collector()

    def _ensure_host_group(self, name: str) -> str:
        found = self.api.call("hostgroup.get", {"filter": {"name": [name]}})
        return found[0]["groupid"] if found else self.api.call("hostgroup.create", {"name": name})["groupids"][0]

    def _ensure_template_group(self, name: str) -> str:
        found = self.api.call("templategroup.get", {"filter": {"name": [name]}})
        return found[0]["groupid"] if found else self.api.call("templategroup.create", {"name": name})["groupids"][0]

    def _ensure_template(self, name: str) -> str:
        found = self.api.call("template.get", {"filter": {"host": [name]}})
        if found:
            return found[0]["templateid"]
        return self.api.call(
            "template.create", {"host": name, "name": name, "groups": [{"groupid": self.template_group_id}]}
        )["templateids"][0]

    def _ensure_status_map(self) -> str:
        found = self.api.call("valuemap.get", {"hostids": self.template_id, "filter": {"name": ["YouTube live status"]}})
        if found:
            return found[0]["valuemapid"]
        result = self.api.call(
            "valuemap.create",
            {
                "name": "YouTube live status",
                "hostid": self.template_id,
                "mappings": [
                    {"type": "0", "value": "0", "newvalue": "Desconhecido"},
                    {"type": "0", "value": "1", "newvalue": "Agendada"},
                    {"type": "0", "value": "2", "newvalue": "Ao vivo"},
                    {"type": "0", "value": "3", "newvalue": "Encerrada"},
                ],
            },
        )
        return result["valuemapids"][0]

    def _ensure_host(self, technical: str, visible: str, group_id: str, template_id: str) -> str:
        found = self.api.call("host.get", {"filter": {"host": [technical]}})
        if found:
            host_id = found[0]["hostid"]
            self.api.call(
                "host.update",
                {"hostid": host_id, "name": visible, "groups": [{"groupid": group_id}], "templates": [{"templateid": template_id}]},
            )
            return host_id
        return self.api.call(
            "host.create",
            {
                "host": technical,
                "name": visible,
                "status": 0,
                "groups": [{"groupid": group_id}],
                "templates": [{"templateid": template_id}],
                "interfaces": [],
            },
        )["hostids"][0]

    def _ensure_items(
        self, host_id: str, definitions: dict[str, tuple[str, int, str]], key_prefix: str, key_id: str | None = None
    ) -> None:
        existing = self.api.call("item.get", {"hostids": host_id, "output": ["itemid", "key_"]})
        keys = {entry["key_"] for entry in existing}
        for metric, (label, value_type, units) in definitions.items():
            key = f"{key_prefix}[{key_id},{metric}]" if key_id else f"{key_prefix}[{metric}]"
            if key in keys:
                continue
            payload: dict[str, Any] = {
                "hostid": host_id,
                "name": label,
                "key_": key,
                "type": 2,
                "value_type": value_type,
                "delay": "0",
                "history": "90d",
                "trends": "365d" if value_type in {0, 3} else "0",
            }
            if units:
                payload["units"] = units
            if metric == "status":
                maps = self.api.call("valuemap.get", {"hostids": host_id, "filter": {"name": ["YouTube Live status"]}})
                if maps:
                    payload["valuemapid"] = maps[0]["valuemapid"]
            try:
                self.api.call("item.create", payload)
            except RuntimeError as exc:
                if "already exists" not in str(exc).lower():
                    raise

    def _ensure_collector(self) -> str:
        group_id = self._ensure_host_group("YouTube Live Monitor Internal")
        template_id = self._ensure_template("Template YouTube Live Collector")
        host_id = self._ensure_host("youtube-live-monitor-collector", "YouTube Live Monitor Collector", group_id, template_id)
        self._ensure_items(host_id, COLLECTOR_METRICS, "youtube.collector")
        return host_id

    def ensure(self, info: dict[str, Any]) -> tuple[str, str]:
        video_id = str(info["video_id"])
        channel_id = str(info["channel_id"] or "unknown")
        if video_id in self.cache:
            return self.cache[video_id]
        technical = f"youtube-channel-{channel_id}"
        visible = str(info["channel_name"] or technical)
        host_id = self._ensure_host(technical, visible, self.group_id, self.template_id)
        self._ensure_live_items(host_id, info)
        self.cache[video_id] = (technical, host_id)
        return technical, host_id

    def _ensure_live_items(self, host_id: str, info: dict[str, Any]) -> None:
        video_id = str(info["video_id"])
        existing = self.api.call(
            "item.get", {"hostids": host_id, "output": ["itemid", "key_", "name", "trends"]}
        )
        by_key = {entry["key_"]: entry for entry in existing}
        source = parse_iso(info.get("scheduled_start")) or parse_iso(info.get("actual_start"))
        date = datetime.fromtimestamp(source, timezone.utc).strftime("%d/%m/%Y") if source else datetime.now(timezone.utc).strftime("%d/%m/%Y")
        live_name = f"{info['title']} — {date}"
        for metric, (label, value_type, units) in METRICS.items():
            key = f"youtube.live[{video_id},{metric}]"
            name = f"{live_name}: {label}"
            if key in by_key:
                update = {"itemid": by_key[key]["itemid"]}
                if by_key[key].get("name") != name:
                    update["name"] = name
                if metric == "status" and str(by_key[key].get("trends")) != "0":
                    update["trends"] = "0"
                if len(update) > 1:
                    self.api.call("item.update", update)
                continue
            payload: dict[str, Any] = {
                "hostid": host_id,
                "name": name,
                "key_": key,
                "type": 2,
                "value_type": value_type,
                "delay": "0",
                "history": "90d",
                "trends": "0" if metric == "status" or value_type == 4 else "365d",
                "tags": [
                    {"tag": "channel", "value": str(info.get("channel_name", ""))},
                    {"tag": "video_id", "value": video_id},
                    {"tag": "live", "value": live_name},
                ],
            }
            if units:
                payload["units"] = units
            if metric == "status":
                maps = self.api.call("valuemap.get", {"hostids": host_id, "filter": {"name": ["YouTube Live status"]}})
                if maps:
                    payload["valuemapid"] = maps[0]["valuemapid"]
            try:
                self.api.call("item.create", payload)
            except RuntimeError as exc:
                if "already exists" not in str(exc).lower():
                    raise


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def sender_lines(host: str, video_id: str, info: dict[str, Any]) -> list[str]:
    allowed = set(METRICS) if int(info.get("status", 0)) in {STATUS["live"], STATUS["ended"]} else PRELIVE_METRICS
    lines = []
    for metric in METRICS:
        if metric not in allowed or metric not in info or info[metric] is None:
            continue
        value = info[metric]
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            continue
        lines.append(f"{json.dumps(host)} youtube.live[{video_id},{metric}] {json.dumps(value, ensure_ascii=False)}")
    return lines


def collector_sender_lines(info: dict[str, Any]) -> list[str]:
    return [
        f'{json.dumps("youtube-live-monitor-collector")} youtube.collector[{metric}] {json.dumps(info[metric])}'
        for metric in COLLECTOR_METRICS
        if metric in info and info[metric] is not None
    ]


def send_batch(lines: list[str], zabbix: dict[str, Any]) -> None:
    if not lines:
        return
    command = [
        zabbix.get("sender_path", "/usr/bin/zabbix_sender"),
        "-z",
        zabbix.get("server", "127.0.0.1"),
        "-p",
        str(zabbix.get("port", 10051)),
        "-i",
        "-",
    ]
    tls = zabbix.get("tls_connect", "unencrypted")
    if tls != "unencrypted":
        command += ["--tls-connect", tls]
    if tls == "psk":
        command += ["--tls-psk-identity", zabbix["tls_psk_identity"], "--tls-psk-file", zabbix["tls_psk_file"]]
    if tls == "cert":
        command += ["--tls-ca-file", zabbix["tls_ca_file"], "--tls-cert-file", zabbix["tls_cert_file"], "--tls-key-file", zabbix["tls_key_file"]]
    result = subprocess.run(command, input="\n".join(lines) + "\n", text=True, capture_output=True, timeout=30, check=False)
    output = " ".join(filter(None, [result.stdout.strip(), result.stderr.strip()]))
    if result.returncode != 0 or re.search(r"failed:\s*[1-9]", output):
        raise RuntimeError(f"zabbix_sender falhou: {output}")
    logging.info("Lote enviado: %s", output)


def cycle(
    cfg: dict[str, Any],
    state: State,
    test: bool = False,
    inspect_api: bool = False,
    client: YouTubeClient | None = None,
    provisioner: Provisioner | None = None,
) -> int:
    started = time.monotonic()
    now = time.time()
    enabled = [live for live in cfg.get("lives", []) if live.get("enabled", True)]
    video_ids = list(dict.fromkeys(extract_video_id(str(live["url"])) for live in enabled))
    collector_cfg = cfg["collector"]
    due = video_ids if test else [video_id for video_id in video_ids if state.is_due(video_id, now)]
    deferred = len(video_ids) - len(due)
    adaptive_skips = 0 if test else sum(state.is_adaptively_deferred(video_id, now) for video_id in video_ids)
    if adaptive_skips:
        state.increment("scheduled_polls_skipped", adaptive_skips, now)

    yt = client or YouTubeClient(
        str(cfg.get("youtube", {}).get("api_key", "")), float(collector_cfg["timeout"]), int(collector_cfg["retries"])
    )
    cycle_request_start = yt.request_count
    if not test and provisioner is None:
        zabbix = cfg.get("zabbix", {})
        provisioner = Provisioner(
            ZabbixAPI(zabbix["api_url"], zabbix["api_token"], bool(zabbix.get("verify_tls", True)))
        )

    lines: list[str] = []
    failures = 0
    successful = 0
    quota_blocked = False
    attempted_ids: set[str] = set()
    for batch in chunks(due, int(collector_cfg["batch_size"])):
        attempted_ids.update(batch)
        for video_id in batch:
            if not test:
                state.mark_attempt(video_id, now)
        try:
            items, latency, api_status = yt.get_many(batch)
        except Exception as exc:  # each ID receives its own persistent backoff
            logging.error("Falha ao consultar lote de %d live(s): %s", len(batch), exc)
            failures += len(batch)
            if not test:
                for video_id in batch:
                    state.mark_failure(video_id, collector_cfg, now)
            quota_blocked = "quota" in str(exc).lower()
            if quota_blocked:
                break
            continue

        for video_id in batch:
            item = items.get(video_id)
            if item is None:
                failures += 1
                logging.error("Vídeo não encontrado ou não público: %s", video_id)
                if not test:
                    state.mark_failure(video_id, collector_cfg, now)
                continue
            info = normalize(video_id, item, latency, api_status)
            if test:
                if inspect_api:
                    print(json.dumps(api_state_snapshot(video_id, item, info), ensure_ascii=False, indent=2))
                else:
                    print(
                        f"OK video_id={video_id} título={info['title']!r} canal={info['channel_name']!r} "
                        f"status={info['status']} api={api_status}"
                    )
                successful += 1
                continue
            try:
                previous_status = state.last_status(video_id)
                if bool(collector_cfg.get("log_api_state", False)) or previous_status != int(info["status"]):
                    logging.info(
                        "Estado YouTube: %s",
                        json.dumps(
                            api_state_snapshot(video_id, item, info, previous_status),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                info.update(state.update(video_id, info, now))
                state.mark_success(video_id, info, collector_cfg, now)
                assert provisioner is not None
                host, _ = provisioner.ensure(info)
                lines.extend(sender_lines(host, video_id, info))
                successful += 1
            except Exception as exc:
                failures += 1
                state.mark_failure(video_id, collector_cfg, now)
                logging.error("Falha ao processar live %s: %s", video_id, exc)

    api_calls = yt.request_count - cycle_request_start
    if not test:
        state.record_api_calls(api_calls, now)
    if quota_blocked:
        not_attempted = [video_id for video_id in due if video_id not in attempted_ids]
        failures += len(not_attempted)
        if not test:
            for video_id in not_attempted:
                state.mark_failure(video_id, collector_cfg, now)

    if not test:
        health = state.health(video_ids, now, time.monotonic() - started, len(due), api_calls)
        lines.extend(collector_sender_lines(health))
        try:
            send_batch(lines, cfg["zabbix"])
        except Exception:
            state.increment("zabbix_sender_failures", 1, now)
            raise
        logging.info(
            "Ciclo: habilitadas=%d consultadas=%d adiadas=%d chamadas_api=%d sucesso=%d falhas=%d",
            len(video_ids), len(due), deferred, api_calls, successful, failures,
        )
    return failures


def valid_credentials(cfg: dict[str, Any]) -> bool:
    api_key = str(cfg.get("youtube", {}).get("api_key", ""))
    token = str(cfg.get("zabbix", {}).get("api_token", ""))
    placeholders = ("CHANGE_ME", "YOUR_", "SUA_", "SEU_", "INSIRA", "SUBSTITUA", "XXXXXXXX")
    return bool(api_key and token and not any(marker in api_key.upper() + token.upper() for marker in placeholders))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--test", action="store_true", help="Valida a configuração e consulta todas as lives uma vez")
    parser.add_argument(
        "--inspect-api",
        action="store_true",
        help="Mostra os campos públicos de estado retornados pelo YouTube, sem acessar o Zabbix",
    )
    parser.add_argument("--once", action="store_true", help="Executa um único ciclo completo")
    parser.add_argument("--check-config", action="store_true", help="Valida os arquivos sem acessar serviços externos")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load_config(args.config)
        enabled_count = sum(1 for live in cfg["lives"] if live.get("enabled", True))
        if args.check_config:
            print(f"Configuração válida: {enabled_count} live(s) habilitada(s), {len(cfg['lives'])} cadastrada(s)")
            return 0
        api_only = args.test or args.inspect_api
        if not api_only and not valid_credentials(cfg):
            raise MonitorError("Credenciais reais de YouTube e Zabbix são obrigatórias")
        if not api_only and not cfg.get("zabbix", {}).get("api_url"):
            raise MonitorError("zabbix.api_url é obrigatória")
        if api_only and not cfg.get("youtube", {}).get("api_key"):
            raise ValueError("youtube.api_key é obrigatória")
        state = State(args.database)
        try:
            client = YouTubeClient(
                str(cfg["youtube"]["api_key"]), float(cfg["collector"]["timeout"]), int(cfg["collector"]["retries"])
            )
            if api_only:
                return 1 if cycle(cfg, state, test=True, inspect_api=args.inspect_api, client=client) else 0
            zabbix = cfg["zabbix"]
            provisioner = Provisioner(
                ZabbixAPI(zabbix["api_url"], zabbix["api_token"], bool(zabbix.get("verify_tls", True)))
            )
            interval = float(cfg["collector"]["interval"])
            while True:
                loop_started = time.monotonic()
                try:
                    failures = cycle(cfg, state, client=client, provisioner=provisioner)
                except Exception as exc:
                    logging.error("Ciclo interrompido: %s", exc)
                    failures = 1
                if args.once:
                    return 1 if failures else 0
                time.sleep(max(0.0, interval - (time.monotonic() - loop_started)))
        finally:
            state.close()
    except (RuntimeError, OSError, ValueError, yaml.YAMLError, sqlite3.Error, requests.RequestException) as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
