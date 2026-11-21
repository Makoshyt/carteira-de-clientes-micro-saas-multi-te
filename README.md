# Carteira de Clientes (Micro SaaS multi-tenant)

Aplicação local de teste em que cada empresa (tenant) cadastra sua conta, faz login
e gerencia seus clientes, com isolamento total entre empresas. Usa somente a
biblioteca padrão do Python 3 (sem `pip install`). Dados apenas fictícios.

> Estado atual (fase E1, tarefas "estrutura-projeto", "migracao-inicial" e
> "executor-migracoes"): estrutura do projeto, configuração, migração inicial portável
> (`migrations/0001_inicial.sql`), executor de migrações (`app/db.py`) chamado pelo `run.py`
> e servidor WSGI mínimo (`GET /api/saude`).
> Cadastro, login e CRUD entram nas próximas tarefas.

## Estrutura

```
app/            pacote Python (config.py, db.py, migracoes.py, servidor.py)
migrations/     migrações versionadas em SQL portável (0001_inicial.sql, ...)
db/             artefatos gerados pela Database Factory (não usados pela aplicação)
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
- **Conexão** (`app/db.py`, `conectar(caminho)`): toda conexão SQLite liga `PRAGMA foreign_keys=ON`
  (o SQLite vem com chaves estrangeiras desligadas) e usa `row_factory=sqlite3.Row`.
- **Migrações**: arquivos `migrations/NNNN_nome.sql`, aplicados em ordem numérica por
  `app/db.py` (`migrar(conexao)`; `app/migracoes.aplicar(caminho)` é um atalho que abre e fecha
  a conexão). Cada um roda numa transação explícita (`BEGIN` ... `COMMIT`; se falhar, `ROLLBACK`
  e nada dele fica aplicado) e é registrado em `schema_migrations` (versão como chave primária,
  sha256 e data UTC). É idempotente: só as versões ainda não registradas são aplicadas, sem
  duplicar registros. Uma migração já aplicada não pode ser alterada (mudanças vão num novo
  `0002_*.sql`); nomes fora do padrão ou números repetidos são recusados. O executor recusa
  conexões com transação aberta e devolve a conexão no mesmo `isolation_level` em que a recebeu.
- **SQL portável (SQLite e PostgreSQL)**: um único conjunto de arquivos, só com `TEXT`, `VARCHAR(n)`,
  `CHECK`, `UNIQUE`, `REFERENCES`, `DEFAULT` literal e `CREATE INDEX`. Sem `AUTOINCREMENT`/`SERIAL`/
  `IDENTITY` e sem funções de data de um banco: **IDs são UUID em texto** gerados em Python e
  **datas são texto ISO-8601 UTC** de tamanho fixo (`2026-01-31T12:00:00Z`), que comparam e ordenam
  corretamente como texto (útil para checar expiração de sessão). Um teste rejeita construções
  específicas de um banco. Não há execução real em PostgreSQL neste projeto (fora do escopo).
- **Esquema (0001)**: `empresas`, `usuarios` (e-mail único no sistema, `CHECK` que só aceita
  `senha_hash` no formato `scrypt$...`), `sessoes` (chave estrangeira composta
  `(usuario_id, empresa_id)` garante que a sessão é da mesma empresa do usuário) e `clientes`
  (`status` com `CHECK IN ('ativo','inativo')`, padrão `ativo`; índice `(empresa_id, nome)`).
- **Artefatos da Database Factory em `db/`**: o esquema gerado lá (IDs inteiros com
  `AUTOINCREMENT`/`IDENTITY`, `strftime`/`now()`, tabela `status_clientes`, e-mail único só por
  empresa, sem tabela de sessões) contradiz a especificação aprovada, então a aplicação usa
  `migrations/`. Os arquivos de `db/` não foram alterados (regra de não reescrever migrações).
  Um banco criado antes com o esquema de `db/` é recusado com uma mensagem clara; como só contém
  dados fictícios, basta apagá-lo.
- **Multi-tenant**: as tabelas de dados têm `empresa_id`; toda consulta será filtrada pela empresa da sessão.
- **Limitações**: servidor de desenvolvimento single-thread, sem HTTPS e sem rate limiting (fora do escopo).
