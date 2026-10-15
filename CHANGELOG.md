# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), versionamento semântico.

## [Não lançado] - 2.0.0

### Added
- Endpoint `/metrics` no formato Prometheus, lido pelo VictoriaMetrics ou por um Prometheus.
- Docker Compose com coletor, VictoriaMetrics 1.154 e Grafana 13.2 já provisionados, para Linux e macOS.
- Estado "indisponível" (4) para vídeo privado ou removido, consultado a cada 30 min sem contar como erro.
- Métricas `youtube_live_views_since_start`, `youtube_live_comments_per_minute`, `youtube_live_seconds_until_start` e `youtube_live_overdue_seconds`.
- Métricas de quota: chamadas no dia do Pacífico, limite configurado (`youtube.daily_quota`) e pausa ativa.
- Chave da API lida de arquivo (`youtube.api_key_file`), relido a cada ciclo.
- `lives.yaml` e `config.yaml` passaram a ser recarregados sem reiniciar o serviço.
- `display_timezone` para a data exibida no nome da live.
- Novos formatos de URL: `music.youtube.com`, `youtube-nocookie.com`, `studio.youtube.com` e `/v/`.
- Trava contra duas instâncias usando o mesmo banco.

### Changed
- O dashboard passou a consultar o VictoriaMetrics em PromQL, com os mesmos painéis.
- A chave da API passou a ir no header `X-Goog-Api-Key` e não aparece mais em URL nem em log.
- A quota passou a ser contada no dia do Pacífico; ao esgotar, as consultas pausam até a virada.
- Live agendada com horário vencido passou a ser consultada com intervalo crescente (30 s, 5 min, 1 h, 6 h).
- "Encerrada" passou a exigir `actualEndTime` ou duas leituras seguidas.
- Duplicatas em `lives.yaml` ficam habilitadas se qualquer cópia estiver habilitada.
- O log do serviço systemd passou a ir para o journal.
- `install.sh` passou a instalar só o coletor, sem exigir Zabbix nem Grafana na máquina.

### Fixed
- Pico e média deixaram de ser enviados como 0 quando o canal oculta a audiência.
- As taxas por minuto voltaram a funcionar com `collector.interval` acima de 90 s.
- Um `lives.yaml` com todas as entradas comentadas deixou de ser rejeitado.
- O dashboard deixou de mostrar "Desconhecida" para lives agendadas distantes e encerradas.
- Duas lives com o mesmo título no mesmo dia deixaram de se misturar no dashboard.
- O `pip` do venv instalado deixou de ficar com interpretador inválido.

### Removed
- Integração com Zabbix: provisionamento via API, `zabbix_sender`, template, value map e token.
- Arquivos `zabbix_template_youtube_live.yaml`, `grafana-youtube-live-provider.yaml`, `youtube-live-monitor.logrotate` e `environment.example`.

## 1.0.0 - 2026-07-20

Primeira versão pública, com envio ao Zabbix e dashboard Grafana 13.
