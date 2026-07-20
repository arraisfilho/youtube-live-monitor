# Changelog

## 1.3.2 - 2026-07-20

### Added

- Comando `--inspect-api` para exibir os campos públicos usados na classificação, sem acessar o Zabbix.
- Registro estruturado dos campos de estado quando uma transmissão muda de situação; diagnóstico contínuo opcional com `collector.log_api_state`.

### Fixed

- Uma transmissão iniciada com `liveBroadcastContent: none` agora é classificada como encerrada mesmo se `actualEndTime` ainda estiver ausente.
- O painel **Status** consulta o histórico bruto, sem médias de trends que poderiam produzir valores inválidos como `2.13`.
- Itens Zabbix de status novos ou reconciliados ficam sem trends, pois o estado é uma métrica discreta.

## 1.3.1 - 2026-07-18

### Fixed

- Corrigida a conversão do painel **Momento do pico**: o timestamp Unix do Zabbix é multiplicado por 1000 antes de ser formatado como data pelo Grafana.

## 1.3.0 - 2026-07-18

### Added

- Coleta adaptativa de lives agendadas com intervalos progressivos conforme o horário de início se aproxima.
- Consultas `videos.list` em lotes de até 50 IDs, reduzindo o custo de quota para múltiplas transmissões.
- Backoff persistente para vídeos indisponíveis e parada definitiva após a coleta final de uma live encerrada.
- Métricas públicas de curtidas, comentários, engajamento, variação percentual, atraso, pico e disponibilidade da audiência.
- Host Zabbix interno com métricas de quota, eficiência dos lotes, estados e saúde do coletor.
- Dashboard Grafana 13 baseado no ajuste enviado pelo usuário, com novos painéis e seção de saúde.
- Migração automática e compatível do banco SQLite criado pela versão 1.2.0.

### Changed

- O dashboard agora usa o formato V2 Resource do Grafana 13 e não contém UID de datasource nem metadados da instância de origem.
- Métricas de audiência só são gravadas quando a transmissão está ao vivo; agendadas enviam apenas estado e metadados.
- Amostras auxiliares usadas nos cálculos são mantidas por 48 horas.

Este projeto segue versionamento semântico.

## [1.2.0] - 2026-07-15

### Adicionado

- Dashboard com linhas repetidas por live e filtros múltiplos `Canal`/`Live` com `All`.
- Validação local com `--check-config`.
- Testes automatizados e workflow de integração contínua.
- Documentação pública, licença MIT e política de segurança.

### Alterado

- Intervalo padrão de coleta e atualização do dashboard para 15 segundos.
- Validação estrita de `enabled` como booleano YAML.
- Instalação explícita do pacote `venv` correspondente à versão do Python.
- Modos systemd de configuração, estado e logs definidos como `0750`.
- Backup datado do dashboard durante atualizações.

### Corrigido

- Reutilização idempotente de itens Zabbix existentes.
- Código de saída de `--test` e `--once` quando uma live falha.
- Ausência de chamadas externas quando não existem lives habilitadas.

## [1.1.0] - 2026-07-15

- Lista externa `lives.yaml`, múltiplas transmissões e controle `enabled`.

## [1.0.0] - 2026-07-15

- Primeira versão funcional do coletor, provisionamento Zabbix e dashboard Grafana.
