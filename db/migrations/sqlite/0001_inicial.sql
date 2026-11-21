-- Migração 0001 gerada pela Database Factory do DevBrain AI (sqlite). Não edite: crie 0002+.
CREATE TABLE empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (nome)
);
CREATE TABLE status_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (nome)
);
CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresas_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    email TEXT NOT NULL CHECK (email LIKE '%_@_%'),
    senha_hash TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (empresas_id, email)
);
CREATE INDEX ix_usuarios_empresas_id ON usuarios (empresas_id);
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresas_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    email TEXT CHECK (email LIKE '%_@_%'),
    telefone TEXT,
    observacoes TEXT,
    status INTEGER NOT NULL REFERENCES status_clientes(id) ON DELETE RESTRICT,
    criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_clientes_empresas_id ON clientes (empresas_id);
CREATE INDEX ix_clientes_status ON clientes (status);
