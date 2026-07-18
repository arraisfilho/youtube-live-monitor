# Contribuindo

Contribuições são bem-vindas por issues e pull requests.

## Ambiente

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
make check
```

## Pull requests

1. Crie uma branch a partir de `main`.
2. Mantenha cada alteração focada e inclua testes para novos comportamentos.
3. Não inclua chaves, tokens, IDs privados, logs, bancos ou configurações de produção.
4. Execute `make check` antes de enviar.
5. Documente mudanças visíveis no `CHANGELOG.md`.

O código Python deve permanecer compatível com Python 3.12. Scripts shell devem passar por `bash -n` e ShellCheck. JSON e YAML precisam continuar válidos.

## Issues

Para bugs, informe versão, sistema, passos de reprodução e mensagens sanitizadas. Substitua chaves, tokens, domínios internos, IPs e IDs sensíveis por exemplos fictícios.
