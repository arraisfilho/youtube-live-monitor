# Migração da 1.x para a 2.0

A 2.0 deixa de enviar métricas ao Zabbix. O coletor expõe `/metrics` no formato Prometheus, o VictoriaMetrics guarda as séries e o Grafana lê do VictoriaMetrics.

## O que muda

| | 1.x | 2.0 |
|---|---|---|
| Armazenamento | Zabbix (itens trapper) | VictoriaMetrics |
| Envio | `zabbix_sender` a cada ciclo | VictoriaMetrics lê `http://<host>:9877/metrics` a cada 15 s |
| Cadastro no destino | host e itens criados via API do Zabbix, com token | nenhum: uma live é só o valor do rótulo `video_id` |
| Dashboard | datasource do plugin Zabbix | datasource Prometheus apontando para o VictoriaMetrics |
| Chave da YouTube API | na query string da URL | no header `X-Goog-Api-Key`, lida de arquivo |
| Log (systemd) | `/var/log/youtube-live-monitor/monitor.log` | journal (`journalctl -u youtube-live-monitor`) |
| Instalador | exigia Zabbix e Grafana na máquina | instala só o coletor; ambiente completo via `docker compose` |

O histórico gravado no Zabbix não é migrado. O banco local (`state.db`) é aproveitado: pico, média e agenda continuam de onde pararam.

## Passo a passo (instalação systemd da 1.x)

1. Atualize o código e reinstale o coletor. `config.yaml` e `lives.yaml` são preservados e a seção `zabbix:` passa a ser ignorada.

   ```bash
   git pull --ff-only
   sudo ./install.sh
   ```

2. Mova a chave para um arquivo, que é relido a cada ciclo. Cole a chave e tecle Ctrl-D:

   ```bash
   sudo install -o root -g youtube-monitor -m 0640 /dev/stdin /etc/youtube-live-monitor/youtube_api_key
   ```

   Em seguida acrescente `api_key_file: /etc/youtube-live-monitor/youtube_api_key` na seção `youtube:` do `config.yaml` e apague a linha `api_key`.

3. Aponte o VictoriaMetrics (ou Prometheus) para o coletor. Se ele estiver em outra máquina, defina `exporter.listen: 0.0.0.0` no `config.yaml` e restrinja a porta 9877 no firewall.

   ```yaml
   scrape_configs:
     - job_name: youtube-live-monitor
       static_configs:
         - targets: ["<host-do-coletor>:9877"]
   ```

4. No Grafana, crie um datasource do tipo Prometheus com a URL do VictoriaMetrics (`http://<host>:8428`) e importe `grafana_dashboard_youtube_live.json`.

5. Remova o que sobrou da 1.x:

   ```bash
   sudo rm -f /etc/logrotate.d/youtube-live-monitor
   sudo rm -rf /var/log/youtube-live-monitor
   sudo rm -f /etc/grafana/provisioning/dashboards/youtube-live-monitor.yaml
   sudo rm -rf /var/lib/grafana/dashboards/youtube-live-monitor
   sudo systemctl try-restart grafana-server
   ```

   No arquivo `/etc/youtube-live-monitor/environment`, se existir, as variáveis `ZABBIX_*` não são mais lidas e podem ser apagadas.

6. Confira:

   ```bash
   curl -s 127.0.0.1:9877/metrics | grep youtube_collector_api_key_configured
   sudo journalctl -u youtube-live-monitor -n 20 --no-pager
   ```

## Objetos no Zabbix

O coletor não remove nada do Zabbix. Se não for mais usá-los, apague pela interface ou pela API:

- grupos `YouTube Live Monitor` e `YouTube Live Monitor Internal`;
- hosts `youtube-channel-*` e `youtube-live-monitor-collector`;
- templates `YouTube Live Monitor` e `Template YouTube Live Collector`;
- o token de API criado para o coletor.

## Correspondência de métricas

Na 2.0 todas as métricas por live têm o rótulo `video_id`. Título e canal ficam em `youtube_live_info`.

| Item 1.x (`youtube.live[ID,…]`) | Métrica 2.0 |
|---|---|
| `concurrent_viewers` | `youtube_live_concurrent_viewers` |
| `peak_viewers` | `youtube_live_peak_viewers` |
| `average_viewers` | `youtube_live_average_viewers` |
| `viewer_change_per_minute` | `youtube_live_viewer_change_per_minute` |
| `viewer_change_percent` | `youtube_live_viewer_change_percent` |
| `total_views` | `youtube_live_views` |
| `new_views_per_minute` | `youtube_live_new_views_per_minute` |
| `like_count` | `youtube_live_likes` |
| `likes_per_minute` | `youtube_live_likes_per_minute` |
| `comment_count` | `youtube_live_comments` |
| `engagement_rate` | `youtube_live_engagement_rate_percent` |
| `status` | `youtube_live_status` (novo valor 4: indisponível) |
| `elapsed_seconds` | `youtube_live_elapsed_seconds` |
| `scheduled_delay_seconds` | `youtube_live_start_delay_seconds` |
| `time_to_peak_seconds` | `youtube_live_time_to_peak_seconds` |
| `peak_timestamp` | `youtube_live_peak_timestamp_seconds` |
| `viewer_count_available` | `youtube_live_viewer_count_available` |
| `scheduled_start`, `scheduled_end`, `actual_start`, `actual_end` | `youtube_live_*_timestamp_seconds` |
| `title`, `channel_name`, `channel_id`, `video_id` | rótulos de `youtube_live_info` |
| `last_update`, `api_latency`, `api_status` | `youtube_live_last_update_timestamp_seconds`, `_api_latency_seconds`, `_api_status` |

| Item 1.x (`youtube.collector[…]`) | Métrica 2.0 |
|---|---|
| `api_calls_total`, `api_calls_today` | `youtube_collector_api_calls_total`, `youtube_collector_api_calls_today` (dia do Pacífico) |
| `videos_per_batch` | `increase(youtube_collector_videos_polled_total[1h]) / increase(youtube_collector_api_calls_total[1h])` |
| `scheduled_polls_skipped` | `youtube_collector_scheduled_polls_skipped_total` |
| `last_success_age` | `youtube_collector_last_success_age_seconds` |
| `consecutive_errors` | `youtube_collector_consecutive_errors` |
| `db_size_bytes` | `youtube_collector_db_size_bytes` |
| `enabled_lives`, `scheduled_lives`, `live_lives`, `ended_lives` | `youtube_collector_lives{status="enabled\|scheduled\|live\|ended"}` |
| `cycle_duration`, `zabbix_sender_failures` | removidas |
