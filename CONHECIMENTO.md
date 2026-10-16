# Base de conhecimento

Contexto para retomar o projeto do zero. Atualizado em 15/10/2026.

## Estado atual

- A versão 2.0.0 está no branch `feat/prometheus-exporter`, com PR aberto para o `main`. O PR #1 (branch `versao-2.0`) foi fechado e substituído; o GitHub não permite apagar PRs. O `main` segue em `5e1af29` (versão 1.0, com Zabbix).
- O processo combinado é trabalhar e commitar localmente no `feat/prometheus-exporter` e só fazer push quando o usuário pedir.
- Tudo o que vai para o GitHub (commits, título e corpo de PR, comentários, CHANGELOG) é escrito em inglês, técnico e conciso, descrevendo só as alterações, sem citar problemas de versões anteriores. As docs do repositório continuam em português.
- As docs não citam versões das ferramentas; dizem apenas que a stack funciona com VictoriaMetrics e Grafana. As versões ficam só nas imagens do `docker-compose.yml`.
- `MIGRACAO.md` documenta a troca do Zabbix pelo VictoriaMetrics e a correspondência de métricas entre as versões.
- O ambiente roda via `docker compose up -d --build`: coletor, VictoriaMetrics e Grafana. As versões das imagens ficam fixadas no `docker-compose.yml`.
- A live monitorada é `1gxyDkm6Xqw`, em `config/lives.yaml`.
- A chave da API fica em `secrets/youtube_api_key`. O arquivo está fora do Git e o Claude não consegue lê-lo, por causa do sandbox.
- A análise da versão 1.0 está em `analise/ANALISE.md`. `analise/test_emulacoes.py` reproduz os bugs da 1.0 e não roda contra a 2.0.

## Arquitetura

```text
YouTube Data API ◄── coletor (daemon Python, youtube_live_monitor.py)
                       ├─ SQLite: agenda, estado, pico/média, amostras de 48 h
                       └─ HTTP :9877/metrics
VictoriaMetrics ── lê /metrics a cada 15 s (deploy/victoriametrics/scrape.yml)
Grafana ── datasource Prometheus apontando para o VictoriaMetrics (uid victoriametrics)
```

Decisões e motivos:

- **Zabbix → VictoriaMetrics.** No Zabbix cada live virava host com 28 itens criados pela API, com token de Super admin, e daí vinha a maior parte dos bugs. No VictoriaMetrics uma live é só o valor de um rótulo.
- **Pull em vez de push.** O coletor expõe sempre o último estado de todas as lives habilitadas. Se o banco cair, perde-se só o trecho em que ficou fora, e o estado final nunca se perde.
- **O coletor continua decidindo quando consultar o YouTube.** Um raspador genérico (json_exporter, Telegraf) consulta a API em todo intervalo e gasta quota mesmo sem live.
- **Metadados em `youtube_live_info`.** Título, canal e nome de exibição ficam nessa métrica; as outras séries só têm `video_id`, então trocar o título não quebra o histórico.
- **Chave no header `X-Goog-Api-Key`.** Na 1.0 a chave ia na URL e vazava no log em erros 429, 5xx e de conexão.
- **Quota no dia de `America/Los_Angeles`.** É quando a quota é renovada. Com `quotaExceeded`, o coletor pausa até a meia-noite do Pacífico mais 2 min.

## Arquivos

| Caminho | Papel |
|---|---|
| `youtube_live_monitor.py` | coletor, exporter e CLI (`--check-config`, `--test`, `--inspect-api`, `--once`) |
| `tests/test_youtube_live_monitor.py` | testes unitários (44) |
| `grafana_dashboard_youtube_live.json` | dashboard Grafana V2 (`dashboard.grafana.app/v2`), uid `youtube-live-monitor` |
| `docker-compose.yml`, `Dockerfile` | ambiente completo; portas só em 127.0.0.1 |
| `config/config.yaml` | config usada pelo Compose (versionada) |
| `config/lives.yaml` | lista de lives local (fora do Git) |
| `deploy/` | scrape do VictoriaMetrics e provisionamento do Grafana |
| `install.sh`, `youtube-live-monitor.service` | instalação nativa do coletor em Linux com systemd |

## Dashboard

- As variáveis são `DS_PROMETHEUS`, `channel` (`label_values(youtube_live_info, channel)`) e `live` (`query_result(youtube_live_info{channel=~"$channel"})`). A regex de `live` usa grupos nomeados: o texto é o rótulo `live` (título — data) e o valor é o `video_id`.
- O título da linha repetida é `${live:text}`. Os painéis consultam `metrica{video_id="$live"}`.
- O Grafana registra no log `[SHOULD NOT HAPPEN] failed to update managedFields ... field not declared in schema` ao provisionar o JSON V2. O dashboard carrega normalmente.
- Métricas novas que ainda não estão no dashboard: `views_since_start`, `comments_per_minute`, `seconds_until_start`, `overdue_seconds` e as de quota (`api_calls_today` contra `quota_daily_limit`, `quota_paused`).

## Ambiente de desenvolvimento (Claude Code nesta máquina)

- O sandbox bloqueia gravar em `.git`. Comandos git que gravam e qualquer comando `docker` (o socket do OrbStack) precisam rodar fora do sandbox, com aprovação.
- O sandbox também bloqueia ler `./secrets` e `./.env`. Isso é proposital: a chave nunca passa pelo Claude.
- O `pip` dentro do sandbox falha na verificação TLS (OSStatus -26276). Use `pip install --use-deprecated=legacy-certs`.
- O `make` do macOS exige aceitar a licença do Xcode. Rode as etapas do `Makefile` à mão.
- Grafana: leitura anônima habilitada (Viewer); `admin/admin` no primeiro acesso para editar.

## Comandos

```bash
docker compose up -d --build                 # sobe ou atualiza tudo
docker compose logs -f collector             # log do coletor
curl -s 127.0.0.1:9877/metrics | grep -v '^#'
curl -s '127.0.0.1:8428/api/v1/query?query=youtube_live_status'
docker compose run --rm collector --config /etc/youtube-live-monitor/config.yaml --test
docker compose down                          # para (os volumes guardam os dados)
```

## Pendências

- Validação com a chave real feita em 15/10/2026 com a live `1gxyDkm6Xqw` (ESPN Brasil): estado, audiência, pico, taxas, saúde do coletor e dashboard ok. Falta acompanhar o encerramento da live (estado 3) e a pausa por quota.
- Commit da versão 2.0 e decidir se `analise/` entra no repositório.
- Itens da análise que continuam valendo:
  - API de cadastro de lives e canais com formulário no Grafana;
  - descoberta automática de lives por canal (`channels.list?forHandle` + playlist de uploads);
  - alertas no Grafana: coletor parado, quota acima de 80%, live atrasada;
  - resumo pós-live;
  - CI no GitHub Actions.
