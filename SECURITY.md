# Política de segurança

## Versões suportadas

A versão mais recente publicada recebe correções de segurança. Versões anteriores devem ser atualizadas antes da abertura de um relatório.

## Relatar uma vulnerabilidade

Não abra uma issue pública com detalhes exploráveis, tokens, chaves, URLs internas, logs sensíveis ou bancos de dados. Use o recurso **Private vulnerability reporting** do GitHub no repositório do projeto. Se ele ainda não estiver habilitado, contate o mantenedor por um canal privado indicado no perfil do repositório.

Inclua versão, impacto, forma mínima de reprodução e correção sugerida, sem credenciais reais. O recebimento deve ser confirmado em até 7 dias; prazos de correção dependem da gravidade e da complexidade.

## Segredos

Nunca publique:

- `/etc/youtube-live-monitor/config.yaml`;
- `/etc/youtube-live-monitor/environment`;
- tokens da API do Zabbix;
- chaves da YouTube Data API;
- `state.db`, logs ou backups de produção.

Se um segredo entrar no Git, revogue-o imediatamente. Remover o texto do último commit não elimina o segredo do histórico remoto.
