# Migrações

As migrações versionadas do projeto ficam em `db/migrations/<dialeto>/NNNN_nome.sql`
(SQLite e PostgreSQL com a mesma numeração) e são aplicadas por `db/migrar.py`,
que registra cada versão em `schema_migrations`. Migrações já aplicadas nunca são
alteradas; mudanças de esquema entram como um novo arquivo `0002_*.sql` nos dois dialetos.
