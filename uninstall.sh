#!/usr/bin/env bash
set -Eeuo pipefail

PURGE=0
[[ "${1:-}" == --purge ]] && PURGE=1
if (( EUID != 0 )); then echo "Execute como root (sudo)." >&2; exit 1; fi

systemctl disable --now youtube-live-monitor.service 2>/dev/null || true
rm -f /etc/systemd/system/youtube-live-monitor.service /etc/logrotate.d/youtube-live-monitor
rm -rf /etc/systemd/system/youtube-live-monitor.service.d
rm -rf /opt/youtube-live-monitor /usr/share/doc/youtube-live-monitor
rm -f /etc/grafana/provisioning/dashboards/youtube-live-monitor.yaml
rm -rf /var/lib/grafana/dashboards/youtube-live-monitor
systemctl daemon-reload
systemctl try-restart grafana-server.service 2>/dev/null || true
if (( PURGE )); then
  rm -rf /etc/youtube-live-monitor /var/lib/youtube-live-monitor /var/log/youtube-live-monitor
  userdel youtube-monitor 2>/dev/null || true
  groupdel youtube-monitor 2>/dev/null || true
  echo "Desinstalado, incluindo configuração e estado (--purge)."
else
  echo "Desinstalado. Configuração, banco e logs foram preservados. Use --purge para removê-los."
fi
