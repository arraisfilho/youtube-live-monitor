# youtube-live-monitor

Coletor de métricas de transmissões públicas do YouTube. Consulta a YouTube Data API v3 (`videos.list`), guarda estado em SQLite e expõe as métricas em `/metrics` no formato Prometheus. O VictoriaMetrics armazena as séries e o Grafana mostra o dashboard.

Não lê chat, não baixa vídeo e não acessa nada privado.

## Requisitos

- Docker com Compose (Linux ou macOS), para o ambiente completo
- ou Python 3.12+ com systemd, para instalar só o coletor no Linux
- Uma chave da YouTube Data API v3

## Instalação

### Docker Compose (coletor, VictoriaMetrics 1.154 e Grafana 13.2)

```bash
git clone https://github.com/arraisfilho/youtube-live-monitor.git
cd youtube-live-monitor
mkdir -p secrets
read -rs CHAVE && printf '%s\n' "$CHAVE" > secrets/youtube_api_key && unset CHAVE
cp lives.example.yaml config/lives.yaml   # edite a lista de lives
docker compose up -d --build
```

| Serviço | Endereço |
|---|---|
| Grafana (leitura sem login; admin/admin para editar) | http://127.0.0.1:3000/d/youtube-live-monitor |
| VictoriaMetrics | http://127.0.0.1:8428 |
| Métricas do coletor | http://127.0.0.1:9877/metrics |

### Somente o coletor, como serviço systemd

```bash
sudo ./install.sh
sudo install -o root -g youtube-monitor -m 0640 /dev/stdin /etc/youtube-live-monitor/youtube_api_key
```

O segundo comando lê a chave da entrada padrão: cole-a e tecle Ctrl-D. Configure seu VictoriaMetrics ou Prometheus para ler `http://<host>:9877/metrics`, e altere `exporter.listen` se ele estiver em outra máquina.

## Configuração

`config/config.yaml` (Compose) ou `/etc/youtube-live-monitor/config.yaml` (systemd). Veja todos os campos em [config.example.yaml](config.example.yaml).

`lives.yaml`:

```yaml
lives:
  - url: https://www.youtube.com/watch?v=AbCdEfGhI12
    enabled: true
  - url: https://youtu.be/XXXXXXXXXXX
    enabled: false
```

O campo `url` aceita o ID ou URLs `watch`, `youtu.be`, `/live`, `shorts`, `embed`, `music.youtube.com`, `youtube-nocookie.com` e `studio.youtube.com`. `enabled` é booleano YAML, sem aspas. Mudanças em `lives.yaml` e `config.yaml` valem no ciclo seguinte, sem reiniciar.

A chave é lida, nesta ordem, de `youtube.api_key_file`, `youtube.api_key` ou das variáveis `YOUTUBE_API_KEY_FILE`/`YOUTUBE_API_KEY`. O arquivo é relido a cada ciclo. Também existem as variáveis `YOUTUBE_LIVES_FILE`, `EXPORTER_LISTEN`, `EXPORTER_PORT` e `DISPLAY_TIMEZONE`.

### Agenda de consultas

| Situação | Próxima consulta |
|---|---:|
| Mais de 24 h para o início | 6 h |
| 6 a 24 h | 1 h |
| 1 a 6 h | 15 min |
| 15 a 60 min | 5 min |
| Até 15 min | 1 min |
| Atrasada até 1 h | 30 s |
| Atrasada de 1 a 6 h | 5 min |
| Atrasada de 6 a 48 h | 1 h |
| Atrasada há mais de 48 h | 6 h |
| Ao vivo | 15 s |
| Encerrada | nunca mais (após `actualEndTime` ou duas leituras seguidas) |
| Indisponível (privada ou removida) | 30 min |
| Erro | 5, 10, 20, 40, até 60 min |

Até 50 vídeos vão na mesma chamada, que custa 1 unidade de quota. A quota é contada no dia do Pacífico, que é quando o YouTube a renova. Ao esgotar, o coletor pausa até a virada.

## Uso

```bash
# valida os arquivos (avisa se a chave falta ou é o valor de exemplo)
docker compose run --rm collector --config /etc/youtube-live-monitor/config.yaml --check-config

# consulta todas as lives uma vez, sem gravar estado
docker compose run --rm collector --config /etc/youtube-live-monitor/config.yaml --test

# mostra os campos da API usados para classificar o estado
docker compose run --rm collector --config /etc/youtube-live-monitor/config.yaml --inspect-api

docker compose logs -f collector
```

Fora do Docker, use os mesmos parâmetros com `/opt/youtube-live-monitor/venv/bin/python /opt/youtube-live-monitor/youtube_live_monitor.py`. `--once` executa um ciclo e imprime as métricas.

### Métricas

Todas as métricas por live têm o rótulo `video_id`. Título, canal, nome de exibição e URL ficam em `youtube_live_info`.

| Métrica | Conteúdo |
|---|---|
| `youtube_live_status` | 0 desconhecida, 1 agendada, 2 ao vivo, 3 encerrada, 4 indisponível |
| `youtube_live_concurrent_viewers`, `_peak_viewers`, `_average_viewers` | audiência atual, pico e média |
| `youtube_live_viewer_change_per_minute`, `_viewer_change_percent` | variação de audiência |
| `youtube_live_views`, `_new_views_per_minute`, `_views_since_start` | visualizações |
| `youtube_live_likes`, `_likes_per_minute`, `_comments`, `_comments_per_minute` | curtidas e comentários |
| `youtube_live_engagement_rate_percent` | curtidas por visualização |
| `youtube_live_elapsed_seconds`, `_start_delay_seconds`, `_time_to_peak_seconds`, `_peak_timestamp_seconds` | tempos |
| `youtube_live_seconds_until_start`, `_overdue_seconds` | contagem regressiva e atraso de lives agendadas |
| `youtube_collector_*` | chamadas e quota do dia, pausa por quota, consultas evitadas, erros, lives por estado, banco |

Pico e média ficam vazios quando o canal oculta a audiência.

## Desenvolvimento

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
make check
```

Veja [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) e [CHANGELOG.md](CHANGELOG.md).

## Licença

MIT. Veja [LICENSE](LICENSE).
