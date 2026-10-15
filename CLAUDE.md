# youtube-live-monitor

Antes de qualquer tarefa, leia [CONHECIMENTO.md](CONHECIMENTO.md): estado atual, arquitetura, decisões e limitações do ambiente. Ao terminar uma mudança relevante, atualize esse arquivo.

- A chave da YouTube API fica em `secrets/youtube_api_key`. Não tente ler o arquivo nem pedir a chave no chat.
- Comandos `docker` e git que gravam em `.git` precisam rodar fora do sandbox, com aprovação do usuário.
