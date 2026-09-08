# Política de segurança

## Versões suportadas

Só a versão mais recente recebe correção. Atualize antes de reportar.

## Reportando

Não abra issue pública com detalhe explorável, token, chave, URL interna ou log sensível.

Use o GitHub Security Advisories: https://github.com/arraisfilho/youtube-live-monitor/security/advisories/new. O relatório fica privado até a correção sair.

Descreva o impacto, a menor forma de reproduzir e, se tiver, a correção sugerida — sem credencial real. Respondo confirmando o recebimento em até 7 dias. O prazo da correção depende da gravidade.

## Segredos

Nunca publique:

- `/etc/youtube-live-monitor/config.yaml`
- `/etc/youtube-live-monitor/environment`
- token da API do Zabbix
- chave da YouTube Data API
- `state.db`, logs ou backups de produção

Se um segredo for para o Git, revogue primeiro. Apagar do último commit não tira do histórico já publicado.
