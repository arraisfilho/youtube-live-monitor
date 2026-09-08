# youtube-live-monitor

Coleta métricas de transmissões públicas do YouTube pela Data API v3, envia para o Zabbix e desenha em um dashboard Grafana.

Só usa `videos.list`. Não lê chat, não baixa vídeo e não acessa nada privado.

## Por que existe

Monitorar uma live com a API pública é fácil. Monitorar vinte sem estourar a quota diária não é. O coletor agrupa até 50 IDs por chamada, consulta lives agendadas com intervalos progressivos conforme o horário se aproxima e para de vez quando a transmissão acaba. Pico, média, agenda e backoff ficam no SQLite, então reiniciar o serviço não desperdiça quota.

## Requisitos

- Ubuntu Server 24.04 (é o que o instalador conhece)
- Python 3.12+
- Zabbix 7.0+
- Grafana 13 com o plugin Zabbix da Alexander Zobnin e um datasource configurado

O dashboard usa o formato V2 Resource, por isso a exigência do Grafana 13. Outras distros podem ser testadas com `--allow-unsupported`, por sua conta e risco.

## Instalação

```bash
git clone https://github.com/arraisfilho/youtube-live-monitor.git
cd youtube-live-monitor
sudo ./install.sh
```

O instalador mostra o plano antes de mexer no sistema, instala só o que falta e preserva `config.yaml` e `lives.yaml` existentes. Use `--yes` para pular a confirmação.

## Configuração

`/etc/youtube-live-monitor/config.yaml`:

```yaml
youtube:
  api_key: SUA_API_KEY

collector:
  interval: 15
  timeout: 10
  retries: 2
  batch_size: 50
  unknown_interval: 300

zabbix:
  server: zabbix.exemplo.com
  port: 10051
  api_url: https://zabbix.exemplo.com/zabbix/api_jsonrpc.php
  api_token: SEU_TOKEN
```

Em `api_url` use o nome que está no certificado TLS. Não desative a verificação para contornar hostname divergente.

`/etc/youtube-live-monitor/lives.yaml`:

```yaml
lives:
  - url: AbCdEfGhI12
    enabled: true
  - url: https://youtu.be/XXXXXXXXXXX
    enabled: true
```

Aceita ID puro ou URL (`watch`, `youtu.be`, `/live`, `shorts`, `embed`). `enabled` é booleano YAML, sem aspas. Entrada desabilitada não gera chamada. Reinicie o serviço após editar.

As variáveis `YOUTUBE_API_KEY`, `YOUTUBE_LIVES_FILE`, `ZABBIX_SERVER`, `ZABBIX_PORT`, `ZABBIX_API_URL` e `ZABBIX_API_TOKEN` têm precedência sobre o YAML. Ficam em `/etc/youtube-live-monitor/environment`, modo `0640`, dono `root:youtube-monitor`.

## Uso

```bash
# valida os arquivos, sem tocar em nada
sudo -u youtube-monitor /opt/youtube-live-monitor/venv/bin/python \
  /opt/youtube-live-monitor/youtube_live_monitor.py \
  --config /etc/youtube-live-monitor/config.yaml --check-config

# consulta todas as lives uma vez, sem provisionar nem enviar
... --database /var/lib/youtube-live-monitor/state.db --test

# um ciclo completo
... --once

# mostra os campos da API usados na classificação
... --inspect-api
```

`--test` e `--once` saem com código diferente de zero se alguma live falhar.

```bash
sudo systemctl restart youtube-live-monitor
sudo journalctl -u youtube-live-monitor -f
```

## Agenda de consultas

A primeira consulta descobre estado e horário. Daí em diante:

| Situação | Próxima consulta |
|---|---:|
| Mais de 24 h para o início | 6 h |
| 6 a 24 h | 1 h |
| 1 a 6 h | 15 min |
| 15 a 60 min | 5 min |
| Até 15 min | 1 min |
| Horário vencido, ainda agendada | 30 s |
| Ao vivo | 15 s |
| Encerrada | nunca mais |
| Erro | 5, 10, 20, 40, até 60 min |

Tudo que estiver pronto vai no mesmo lote. Como `videos.list` custa uma unidade por chamada e não por vídeo, 30 lives ao vivo custam uma unidade por ciclo. `--test` ignora a agenda de propósito.

## Métricas

Por live: `concurrent_viewers`, `peak_viewers`, `peak_timestamp`, `average_viewers`, `viewer_change_per_minute`, `viewer_change_percent`, `total_views`, `new_views_per_minute`, `like_count`, `likes_per_minute`, `comment_count`, `engagement_rate`, `elapsed_seconds`, `scheduled_delay_seconds`, `time_to_peak_seconds`, `viewer_count_available` e `status`.

`status` é `0` desconhecida, `1` agendada, `2` ao vivo, `3` encerrada. Métricas de audiência só entram no histórico enquanto a live está ao vivo; agendada envia apenas estado e metadados. Curtidas, comentários e audiência simultânea podem simplesmente não vir — o YouTube ou o dono do canal decidem isso. Dislike público não existe mais na API.

O host `youtube-live-monitor-collector`, no grupo `YouTube Live Monitor Internal`, recebe as métricas do próprio coletor: chamadas do dia, vídeos por chamada, consultas evitadas, duração do ciclo, idade do último sucesso, sequência de erros, falhas do `zabbix_sender`, tamanho do banco e contagem de lives por estado. Fica fora do grupo usado pela variável `Canal` para não sujar o filtro.

## Zabbix e Grafana

Na primeira coleta o token cria (ou reaproveita) o grupo, o template, o value map, um host `youtube-channel-<channel_id>` por canal e os itens trapper por vídeo. É idempotente.

O dashboard vai para `/var/lib/grafana/dashboards/youtube-live-monitor/dashboard.json`, com backup datado do anterior. Não contém UID de datasource nem nada da instância onde foi feito — escolha o datasource na variável `Zabbix` e salve se quiser fixar.

Com `Canal = All` e `Live = All` você vê uma seção por live de todos os canais. A seção de saúde do coletor não se repete. Refresh de 15 s.

## Quando algo não funciona

```bash
sudo systemctl status zabbix-server grafana-server youtube-live-monitor
sudo journalctl -u youtube-live-monitor --since "30 minutes ago" --no-pager
sudo tail -n 100 /var/log/youtube-live-monitor/monitor.log
sudo -u youtube-monitor test -r /etc/youtube-live-monitor/config.yaml
sudo -u youtube-monitor test -w /var/lib/youtube-live-monitor
```

Erro de certificado se resolve com o DNS certo em `zabbix.api_url` ou um certificado com SAN adequado, não desligando a verificação. Erro persistente entra em backoff, e uma live com problema não derruba as outras.

## Limitações

Bitrate, resolução de ingest, saúde do encoder e chat exigem API autenticada com autorização do canal. Não dá para fazer isso monitorando lives públicas de terceiros, então está fora do escopo. A própria Data API às vezes demora a atualizar os contadores.

## Atualizar e remover

```bash
git pull --ff-only
sudo ./install.sh          # preserva config, lives e banco
```

```bash
sudo ./uninstall.sh          # mantém os dados
sudo ./uninstall.sh --purge  # apaga tudo local
```

Objetos e histórico no Zabbix não são removidos.

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

YouTube, Zabbix e Grafana são marcas de seus donos. Este projeto não tem qualquer vínculo com eles.
