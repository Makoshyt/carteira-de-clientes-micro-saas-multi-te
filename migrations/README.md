# Migrações

As migrações versionadas usadas pela aplicação ficam aqui, em `migrations/NNNN_nome.sql`
(quatro dígitos, nome em minúsculas). Elas são aplicadas em ordem numérica por
`migrar(conexao)` em `app/db.py` (o `run.py` usa o atalho `app/migracoes.aplicar(caminho)`),
cada uma numa transação própria, e registradas em
`schema_migrations` (versão, sha256 do arquivo e data UTC). Aplicar de novo não faz nada.

Regras:

- Uma migração já aplicada nunca é alterada; mudanças de esquema entram num novo arquivo
  (`0002_*.sql`, ...). Se o arquivo mudar, o aplicador recusa com `ErroMigracao`.
- SQL portável entre SQLite e PostgreSQL: só `TEXT`, `VARCHAR(n)`, `NOT NULL`, `DEFAULT`
  literal, `UNIQUE`, `CHECK`, `REFERENCES` e `CREATE INDEX`. Nada de `AUTOINCREMENT`,
  `SERIAL`, `IDENTITY`, funções de data de um banco específico, `PRAGMA` ou `BEGIN`/`COMMIT`
  (a transação é do aplicador). Um teste verifica isso.
- IDs são UUID em texto gerados em Python; datas são texto ISO-8601 UTC
  (`2026-01-31T12:00:00Z`), preenchidas pela aplicação.

| Versão | Conteúdo |
|---|---|
| `0001_inicial` | tabelas `empresas`, `usuarios`, `sessoes`, `clientes` e índice `ix_clientes_empresa_nome` |

Os arquivos em `db/migrations/` foram gerados automaticamente pela Database Factory, mas
não são usados pela aplicação (veja "Decisões técnicas" no README principal).
