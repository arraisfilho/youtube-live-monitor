# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased] - 2.0.0

### Added
- Prometheus-format `/metrics` endpoint; the stack runs on VictoriaMetrics and Grafana.
- Docker Compose setup with the collector, VictoriaMetrics and Grafana provisioned, for Linux and macOS.
- `unavailable` status (4) for private or removed videos, re-checked every 30 min.
- Metrics `youtube_live_views_since_start`, `youtube_live_comments_per_minute`, `youtube_live_seconds_until_start` and `youtube_live_overdue_seconds`.
- Quota metrics: calls per quota day, configured limit (`youtube.daily_quota`) and pause state.
- API key file support (`youtube.api_key_file`), re-read on every cycle.
- Hot reload of `config.yaml` and `lives.yaml`.
- `display_timezone` setting for live display names.
- URL formats from `music.youtube.com`, `youtube-nocookie.com`, `studio.youtube.com` and `/v/`.
- Single-instance lock per state database.
- Migration guide from 1.x in [MIGRACAO.md](MIGRACAO.md).

### Changed
- Grafana dashboard queries moved to PromQL; panels and metrics are unchanged.
- The API key is sent in the `X-Goog-Api-Key` header.
- Quota usage is tracked per Pacific Time day; polling pauses until the daily reset when the quota is exhausted.
- Scheduled lives past their start time are polled with increasing intervals (30 s, 5 min, 1 h, 6 h).
- A live is finalized after `actualEndTime` or two consecutive ended readings.
- Peak and average viewers are omitted when the channel hides the viewer count.
- Per-minute rates adapt to `collector.interval`.
- Duplicate entries in `lives.yaml` are enabled if any copy is enabled; an empty `lives:` list is accepted.
- Each live is identified by its video ID in the dashboard.
- The systemd service logs to the journal.
- `install.sh` installs the collector only and swaps the virtualenv through a symlink.

### Removed
- Zabbix integration: API provisioning, `zabbix_sender`, template, value map and API token.
- `zabbix_template_youtube_live.yaml`, `grafana-youtube-live-provider.yaml`, `youtube-live-monitor.logrotate` and `environment.example`.

## [1.0.0] - 2026-07-20

### Added
- First public release, sending metrics to Zabbix with a Grafana dashboard.
