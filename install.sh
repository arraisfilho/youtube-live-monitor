#!/usr/bin/env bash
# Instala o coletor como serviço systemd (Linux). VictoriaMetrics e Grafana
# podem vir do docker compose deste repositório ou de uma instalação própria.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    *) echo "Uso: sudo $0 [--yes]" >&2; exit 2 ;;
  esac
done

if (( EUID != 0 )); then
  echo "ERRO: execute como root (sudo)." >&2
  exit 1
fi
command -v systemctl >/dev/null 2>&1 || { echo "ERRO: systemd não encontrado. Use o docker compose." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERRO: python3 não encontrado." >&2; exit 1; }
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
  echo "ERRO: Python 3.12+ requerido; encontrado $(python3 --version 2>&1)." >&2
  exit 1
fi

echo "Plano:"
echo "  1. Criar usuário youtube-monitor e diretórios em /opt, /etc e /var/lib."
echo "  2. Criar venv e instalar dependências (python3-venv é instalado via apt se faltar)."
echo "  3. Copiar o coletor e registrar o serviço systemd, sem sobrescrever config.yaml e lives.yaml."
echo "  4. Iniciar o serviço; métricas em http://127.0.0.1:9877/metrics."
if (( ! ASSUME_YES )); then
  read -r -p "Continuar? [s/N] " answer
  [[ "$answer" =~ ^[sS]$ ]] || { echo "Cancelado sem alterações."; exit 0; }
fi

if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
  command -v apt-get >/dev/null 2>&1 || { echo "ERRO: instale o módulo venv do Python." >&2; exit 1; }
  apt-get update
  apt-get install -y --no-install-recommends python3-venv
fi

getent group youtube-monitor >/dev/null || groupadd --system youtube-monitor
id youtube-monitor >/dev/null 2>&1 || useradd --system --gid youtube-monitor --home-dir /var/lib/youtube-live-monitor --shell /usr/sbin/nologin youtube-monitor
install -d -o root -g youtube-monitor -m 0750 /etc/youtube-live-monitor
install -d -o youtube-monitor -g youtube-monitor -m 0750 /var/lib/youtube-live-monitor
install -d -o root -g root -m 0755 /opt/youtube-live-monitor /usr/share/doc/youtube-live-monitor

# Cada versão do venv ganha seu próprio diretório; o link "venv" troca de forma atômica
# e os scripts do venv (pip incluso) continuam apontando para um caminho válido.
release="venv-$(date +%Y%m%d%H%M%S)"
python3 -m venv "/opt/youtube-live-monitor/$release"
"/opt/youtube-live-monitor/$release/bin/pip" install --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt"
if [[ -d /opt/youtube-live-monitor/venv && ! -L /opt/youtube-live-monitor/venv ]]; then
  rm -rf /opt/youtube-live-monitor/venv  # venv da versão 1.x, criado como diretório
fi
ln -sfn "$release" /opt/youtube-live-monitor/venv.new
mv -T /opt/youtube-live-monitor/venv.new /opt/youtube-live-monitor/venv
find /opt/youtube-live-monitor -maxdepth 1 -name 'venv-*' ! -name "$release" -exec rm -rf {} +

install -o root -g root -m 0755 "$SCRIPT_DIR/youtube_live_monitor.py" /opt/youtube-live-monitor/youtube_live_monitor.py
install -o root -g root -m 0644 "$SCRIPT_DIR/README.md" "$SCRIPT_DIR/LICENSE" /usr/share/doc/youtube-live-monitor/
for name in config lives; do
  if [[ ! -e "/etc/youtube-live-monitor/$name.yaml" ]]; then
    install -o root -g youtube-monitor -m 0640 "$SCRIPT_DIR/$name.example.yaml" "/etc/youtube-live-monitor/$name.yaml"
  else
    echo "Preservado: /etc/youtube-live-monitor/$name.yaml"
  fi
done
install -o root -g root -m 0644 "$SCRIPT_DIR/youtube-live-monitor.service" /etc/systemd/system/youtube-live-monitor.service

systemctl daemon-reload
systemctl enable youtube-live-monitor.service
systemctl restart youtube-live-monitor.service
echo "Instalação concluída."
if [[ ! -s /etc/youtube-live-monitor/youtube_api_key ]]; then
  echo "Falta a chave: grave-a em /etc/youtube-live-monitor/youtube_api_key (dono root:youtube-monitor, modo 0640)."
  echo "O coletor relê o arquivo a cada ciclo; não precisa reiniciar."
fi
