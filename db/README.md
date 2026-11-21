# Banco de dados — proj_003_carteira_de_clientes_

Gerado pela **Database Factory** do DevBrain AI. Fonte: `db/modelo.json`.

- Multi-tenant: **sim** (tenant: `empresas`; coluna `empresas_id`)
- Dialetos: SQLite (`db/migrations/sqlite`) e PostgreSQL (`db/migrations/postgres`), mesma numeração.
- Migrações versionadas: arquivos `NNNN_nome.sql`, aplicados em ordem e registrados em `schema_migrations` (com sha256; uma migração aplicada nunca é reescrita).
- Seeds fictícios: `db/seeds/<dialeto>/` (domínio `.invalid`, sem senhas reais).
- Credenciais: só em `.env` (ignorado pelo Git, modo 600). Nunca as copie para o código.

## Isolamento entre contas

- PostgreSQL: Row Level Security **forçada** em todas as tabelas com `empresas_id`; a aplicação conecta com um papel sem privilégios de dono e define `SET app.empresas_id = <id da conta>` em cada transação. Sem o valor, nenhuma linha aparece.
- SQLite: o isolamento é da camada de acesso da aplicação (todas as consultas filtram por `empresas_id`), coberto por testes.

## Tabelas

### `empresas` — Contas das empresas
| Coluna | Tipo | Regras |
|---|---|---|
| id | inteiro | chave primária |
| nome | texto | obrigatório · único |
| criado_em | data_hora | padrão: agora |

### `status_clientes` — Status dos clientes
| Coluna | Tipo | Regras |
|---|---|---|
| id | inteiro | chave primária |
| nome | texto | obrigatório · único |
| criado_em | data_hora | padrão: agora |

### `usuarios` — Usuários das empresas
| Coluna | Tipo | Regras |
|---|---|---|
| id | inteiro | chave primária |
| empresas_id | inteiro | obrigatório · FK `empresas(id)` · índice · RLS |
| email | email | obrigatório · único por conta |
| senha_hash | senha_hash | obrigatório |
| criado_em | data_hora | padrão: agora |

### `clientes` — Clientes das empresas
| Coluna | Tipo | Regras |
|---|---|---|
| id | inteiro | chave primária |
| empresas_id | inteiro | obrigatório · FK `empresas(id)` · índice · RLS |
| nome | texto | obrigatório |
| email | email | — |
| telefone | texto_curto | — |
| observacoes | texto | — |
| status | inteiro | obrigatório · FK `status_clientes(id)` · índice |
| criado_em | data_hora | padrão: agora |
