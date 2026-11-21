# Carteira de Clientes (Micro SaaS multi-tenant)

Aplicação local de teste em que cada empresa (tenant) cadastra sua conta, faz login
e gerencia seus clientes, com isolamento total entre empresas. Usa somente a
biblioteca padrão do Python 3 (sem `pip install`). Dados apenas fictícios.

> Estado atual (fase E1, tarefa "estrutura-projeto"): estrutura do projeto,
> configuração, aplicação das migrações e servidor WSGI mínimo (`GET /api/saude`).
> Cadastro, login e CRUD entram nas próximas tarefas.

## Estrutura

```
app/            pacote Python (config.py, servidor.py)
db/             migrações versionadas (db/migrations/sqlite e postgres) e db/migrar.py
migrations/     nota sobre onde ficam as migrações
static/         frontend HTML/CSS/JS sem dependências
tests/          testes unittest
run.py          ponto de entrada
```

## Como executar

```
python3 run.py
```

Aplica as migrações pendentes no banco e sobe o servidor em `http://127.0.0.1:8000/`.

Variáveis de ambiente:

| Variável | Padrão | Descrição |
|---|---|---|
| `CARTEIRA_DB` | `./carteira.db` | caminho do arquivo SQLite |
| `CARTEIRA_PORTA` | `8000` | porta HTTP (sempre ligada só em `127.0.0.1`) |
| `CARTEIRA_SEGREDO` | gerado | segredo HMAC dos tokens (mín. 32 caracteres) |
| `CARTEIRA_TOKEN_TTL` | `28800` (8h) | validade do token, em segundos |

Se `CARTEIRA_SEGREDO` não estiver definido, um segredo é gerado com
`secrets.token_hex(32)` e gravado em `.carteira_segredo` (permissão 600, ignorado pelo Git),
sendo reaproveitado nas execuções seguintes.

## Como testar

```
python3 -m unittest discover -s tests -v
```

Os testes usam diretórios temporários (não tocam no banco nem no segredo locais) e não usam rede.

## Decisões técnicas

- **Só biblioteca padrão**: `wsgiref.simple_server` com uma app WSGI própria, `sqlite3`, `hashlib`, `secrets`, `hmac`.
- **Bind só em 127.0.0.1**: o host não é configurável, para que o servidor nunca fique exposto na rede.
- **Configuração por ambiente** com validação (porta 1–65535, TTL positivo, segredo mínimo de 32
  caracteres); valores inválidos geram `ErroConfiguracao` em vez de rodar com padrões silenciosos.
  O `repr` da configuração mascara o segredo.
- **Migrações**: arquivos `NNNN_nome.sql` em `db/migrations/<dialeto>/`, aplicados em ordem por
  `db/migrar.py` e registrados em `schema_migrations` com sha256 (idempotente; migração aplicada
  não pode ser alterada). O esquema tem versão equivalente para PostgreSQL (sem driver neste projeto).
- **Multi-tenant**: tabelas de dados têm `empresas_id`; toda consulta será filtrada pela empresa da sessão.
- **Limitações**: servidor de desenvolvimento single-thread, sem HTTPS e sem rate limiting (fora do escopo).
