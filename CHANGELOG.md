# Changelog

Versionamento semântico.

## 1.0.0 - 2026-07-20

Primeira versão pública.

- Coletor Python com serviço systemd, logrotate e instalador idempotente para Ubuntu 24.04.
- Consulta apenas `videos.list`, em lotes de até 50 IDs. Como a chamada custa uma unidade de quota independente da quantidade de vídeos, monitorar dez lives custa o mesmo que monitorar uma.
- Agenda adaptativa: lives distantes são consultadas de hora em hora, ao vivo a cada 15 s, encerradas nunca mais. Backoff progressivo para vídeo indisponível.
- Estado, amostras, agenda e contadores ficam no SQLite, então reiniciar o serviço não desperdiça quota.
- Lista de transmissões em `lives.yaml`, com controle `enabled` por entrada. Aceita ID puro ou URL nos formatos `watch`, `youtu.be`, `/live`, `shorts` e `embed`.
- Métricas por live: audiência simultânea, pico e momento do pico, média, variação por minuto, visualizações, curtidas, comentários, engajamento, tempo decorrido, atraso em relação ao horário agendado e estado. Audiência só é gravada com a live ao vivo.
- Host Zabbix interno com as métricas do próprio coletor: quota do dia, eficiência dos lotes, duração do ciclo, idade do último sucesso e falhas do `zabbix_sender`. Fica fora do grupo dos canais para não sujar o filtro do dashboard.
- Provisionamento idempotente no Zabbix: grupo, template, value map, um host por canal e itens trapper por vídeo.
- Dashboard Grafana 13 no formato V2 Resource, com uma linha repetida por live e filtros `Canal`/`Live`. Sai sem UID de datasource e sem metadado da instância onde foi construído.
- `--check-config` valida os arquivos sem chamada externa; `--test` e `--once` executam sem provisionar; `--inspect-api` mostra os campos da API usados para classificar a transmissão.
- Nenhuma credencial, UID ou dado de instância real nos arquivos versionados.
