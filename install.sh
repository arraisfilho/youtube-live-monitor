#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ASSUME_YES=0
ALLOW_UNSUPPORTED=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --allow-unsupported) ALLOW_UNSUPPORTED=1 ;;
    *) echo "Uso: sudo $0 [--yes] [--allow-unsupported]" >&2; exit 2 ;;
  esac
done

echo "Pré-verificação (nenhuma alteração realizada)"
if [[ -r /etc/os-release ]]; then
  # Arquivo padrão do sistema alvo.
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "Sistema: ${PRETTY_NAME:-desconhecido}"
else
  echo "Sistema: /etc/os-release ausente"
  ID=unknown; VERSION_ID=unknown
fi
echo "Kernel: $(uname -srmo)"
echo "Python: $(python3 --version 2>&1 || echo ausente)"
echo "Zabbix server: $(zabbix_server --version 2>/dev/null | head -1 || echo binário ausente)"
echo "Zabbix sender: $(zabbix_sender --version 2>/dev/null | head -1 || echo binário ausente)"
echo "Grafana: $(grafana-server -v 2>/dev/null || echo binário ausente)"
echo "Configurações Zabbix encontradas:"
find /etc/zabbix -maxdepth 2 -type f 2>/dev/null | sort || true
echo "Configurações Grafana encontradas:"
find /etc/grafana -maxdepth 3 -type f 2>/dev/null | sort || true

if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
  if (( ! ALLOW_UNSUPPORTED )); then
    echo "ERRO: este instalador requer Ubuntu 24.04. Use --allow-unsupported apenas em ambiente de teste." >&2
    exit 1
  fi
fi
missing_server=0
for binary in python3 zabbix_server grafana-server; do
  if ! command -v "$binary" >/dev/null 2>&1; then
    echo "ERRO: pré-requisito existente não encontrado: $binary" >&2
    missing_server=1
  fi
done
(( missing_server == 0 )) || exit 1
zabbix_version_line="$(zabbix_server --version 2>/dev/null | head -1 || true)"
zabbix_version="$(printf '%s\n' "$zabbix_version_line" | grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1 || true)"
grafana_version="$(grafana-server -v 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1 || true)"
if (( ! ALLOW_UNSUPPORTED )); then
  if [[ -z "$zabbix_version" || "$(printf '%s\n' 7.0.0 "$zabbix_version" | sort -V | head -1)" != 7.0.0 ]]; then
    echo "ERRO: Zabbix 7.0+ requerido; detectado ${zabbix_version:-desconhecido}." >&2
    exit 1
  fi
  if [[ -z "$grafana_version" || "$(printf '%s\n' 13.0.0 "$grafana_version" | sort -V | head -1)" != 13.0.0 ]]; then
    echo "ERRO: Grafana 13.0+ requerido pelo dashboard V2; detectado ${grafana_version:-desconhecido}." >&2
    exit 1
  fi
fi
if [[ "$zabbix_version_line" =~ [Aa]lpha|[Bb]eta|[Rr][Cc] ]]; then
  echo "AVISO: Zabbix pré-lançamento detectado (${zabbix_version_line}). Faça backup e valide em homologação antes de produção." >&2
fi
if (( EUID != 0 )); then
  echo "ERRO: execute como root (sudo)." >&2
  exit 1
fi

echo
echo "Plano de alteração:"
echo "  1. Instalar somente dependências ausentes (python3-venv, zabbix-sender, curl)."
echo "  2. Criar usuário de sistema youtube-monitor e diretórios em /opt, /etc, /var/lib e /var/log."
echo "  3. Criar venv, instalar requirements e copiar coletor/artefatos."
echo "  4. Registrar serviço systemd e logrotate, sem sobrescrever config.yaml existente."
echo "  5. Provisionar o dashboard Grafana e instalar seu plugin Zabbix se necessário."
echo "  6. Habilitar o serviço; ele só será iniciado se a configuração já tiver credenciais reais."
if (( ! ASSUME_YES )); then
  read -r -p "Continuar? [s/N] " answer
  [[ "$answer" =~ ^[sS]$ ]] || { echo "Cancelado sem alterações."; exit 0; }
fi

export DEBIAN_FRONTEND=noninteractive
packages=()
dpkg-query -W -f='${Status}' python3-venv 2>/dev/null | grep -q '^install ok installed$' || packages+=(python3-venv)
python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python_venv_package="python${python_version}-venv"
dpkg-query -W -f='${Status}' "$python_venv_package" 2>/dev/null | grep -q '^install ok installed$' || packages+=("$python_venv_package")
command -v zabbix_sender >/dev/null 2>&1 || packages+=(zabbix-sender)
command -v curl >/dev/null 2>&1 || packages+=(curl)
if ((${#packages[@]})); then
  apt-get update
  apt-get install -y --no-install-recommends "${packages[@]}"
fi

getent group youtube-monitor >/dev/null || groupadd --system youtube-monitor
id youtube-monitor >/dev/null 2>&1 || useradd --system --gid youtube-monitor --home-dir /var/lib/youtube-live-monitor --shell /usr/sbin/nologin youtube-monitor
install -d -o root -g youtube-monitor -m 0750 /etc/youtube-live-monitor
install -d -o youtube-monitor -g youtube-monitor -m 0750 /var/lib/youtube-live-monitor /var/log/youtube-live-monitor
install -d -o root -g root -m 0755 /opt/youtube-live-monitor /usr/share/doc/youtube-live-monitor
venv_new="/opt/youtube-live-monitor/.venv-new-$$"
rm -rf "$venv_new"
trap 'rm -rf "$venv_new"' EXIT
python3 -m venv "$venv_new"
"$venv_new/bin/pip" install --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt"
rm -rf /opt/youtube-live-monitor/venv
mv "$venv_new" /opt/youtube-live-monitor/venv
trap - EXIT
install -o root -g root -m 0755 "$SCRIPT_DIR/youtube_live_monitor.py" /opt/youtube-live-monitor/youtube_live_monitor.py
install -o root -g root -m 0644 "$SCRIPT_DIR/requirements.txt" /opt/youtube-live-monitor/requirements.txt
install -o root -g root -m 0644 "$SCRIPT_DIR/README.md" /usr/share/doc/youtube-live-monitor/README.md
install -o root -g root -m 0644 "$SCRIPT_DIR/LICENSE" /usr/share/doc/youtube-live-monitor/LICENSE
install -o root -g root -m 0644 "$SCRIPT_DIR/zabbix_template_youtube_live.yaml" /usr/share/doc/youtube-live-monitor/
if [[ ! -e /etc/youtube-live-monitor/config.yaml ]]; then
  install -o root -g youtube-monitor -m 0640 "$SCRIPT_DIR/config.example.yaml" /etc/youtube-live-monitor/config.yaml
else
  echo "Preservado: /etc/youtube-live-monitor/config.yaml"
fi
if [[ ! -e /etc/youtube-live-monitor/lives.yaml ]]; then
  install -o root -g youtube-monitor -m 0640 "$SCRIPT_DIR/lives.example.yaml" /etc/youtube-live-monitor/lives.yaml
else
  echo "Preservado: /etc/youtube-live-monitor/lives.yaml"
fi
install -o root -g root -m 0644 "$SCRIPT_DIR/youtube-live-monitor.service" /etc/systemd/system/youtube-live-monitor.service
install -o root -g root -m 0644 "$SCRIPT_DIR/youtube-live-monitor.logrotate" /etc/logrotate.d/youtube-live-monitor

if command -v grafana-cli >/dev/null 2>&1; then
  if ! grafana-cli plugins ls 2>/dev/null | grep -q alexanderzobnin-zabbix-app; then
    grafana-cli plugins install alexanderzobnin-zabbix-app
  fi
  install -d -o grafana -g grafana -m 0755 /var/lib/grafana/dashboards/youtube-live-monitor
  if [[ -e /var/lib/grafana/dashboards/youtube-live-monitor/dashboard.json ]]; then
    cp -a /var/lib/grafana/dashboards/youtube-live-monitor/dashboard.json \
      "/var/lib/grafana/dashboards/youtube-live-monitor/dashboard.json.bak-$(date +%Y%m%d-%H%M%S)"
  fi
  install -o grafana -g grafana -m 0644 "$SCRIPT_DIR/grafana_dashboard_youtube_live.json" /var/lib/grafana/dashboards/youtube-live-monitor/dashboard.json
  install -d -o root -g grafana -m 0755 /etc/grafana/provisioning/dashboards
  install -o root -g grafana -m 0644 "$SCRIPT_DIR/grafana-youtube-live-provider.yaml" /etc/grafana/provisioning/dashboards/youtube-live-monitor.yaml
  systemctl try-restart grafana-server.service || true
else
  echo "AVISO: grafana-cli ausente; dashboard não provisionado."
fi

systemctl daemon-reload
systemctl enable youtube-live-monitor.service
if ! grep -qE 'SUA_API_KEY|SEU_TOKEN_DA_API_ZABBIX|XXXXXXXX' /etc/youtube-live-monitor/config.yaml /etc/youtube-live-monitor/lives.yaml; then
  systemctl restart youtube-live-monitor.service
else
  echo "Serviço não iniciado: edite /etc/youtube-live-monitor/config.yaml e execute:"
  echo "  sudo systemctl restart youtube-live-monitor"
fi
echo "Instalação concluída."
