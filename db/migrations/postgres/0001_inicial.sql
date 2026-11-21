-- Migração 0001 gerada pela Database Factory do DevBrain AI (postgres). Não edite: crie 0002+.
CREATE TABLE empresas (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (nome)
);
CREATE TABLE status_clientes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (nome)
);
CREATE TABLE usuarios (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    empresas_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    email VARCHAR(254) NOT NULL CHECK (email LIKE '%_@_%'),
    senha_hash TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (empresas_id, email)
);
CREATE INDEX ix_usuarios_empresas_id ON usuarios (empresas_id);
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuarios FORCE ROW LEVEL SECURITY;
CREATE POLICY isolamento_empresas ON usuarios USING (empresas_id = NULLIF(current_setting('app.empresas_id', true), '')::bigint) WITH CHECK (empresas_id = NULLIF(current_setting('app.empresas_id', true), '')::bigint);
CREATE TABLE clientes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    empresas_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    email VARCHAR(254) CHECK (email LIKE '%_@_%'),
    telefone VARCHAR(200),
    observacoes TEXT,
    status BIGINT NOT NULL REFERENCES status_clientes(id) ON DELETE RESTRICT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_clientes_empresas_id ON clientes (empresas_id);
CREATE INDEX ix_clientes_status ON clientes (status);
ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes FORCE ROW LEVEL SECURITY;
CREATE POLICY isolamento_empresas ON clientes USING (empresas_id = NULLIF(current_setting('app.empresas_id', true), '')::bigint) WITH CHECK (empresas_id = NULLIF(current_setting('app.empresas_id', true), '')::bigint);
