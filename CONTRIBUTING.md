# Contribuindo

Issues e pull requests são bem-vindos em https://github.com/arraisfilho/youtube-live-monitor.

## Ambiente

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
make check
```

`make check` roda ruff, pytest, `bash -n`, shellcheck (se instalado) e valida o JSON do dashboard e os YAMLs do projeto.

Para o ambiente completo: `docker compose up -d --build`.

## Pull requests

Branch a partir de `main`, uma mudança por PR, teste para comportamento novo e `make check` passando. Mudança visível ao usuário entra no `CHANGELOG.md`.

O código precisa continuar rodando em Python 3.12.

E o mais importante: nada de chave, token, ID privado, log de produção, banco ou config real no diff. Se passar despercebido, é problema de todo mundo.

## Issues

Informe versão, sistema, o que você fez e o que aconteceu. Cole as mensagens de erro, mas troque chaves, tokens, domínios internos, IPs e IDs por exemplos fictícios antes.
