-- 0001_inicial: esquema inicial da Carteira de Clientes.
--
-- SQL portável entre SQLite e PostgreSQL: só TEXT, VARCHAR(n), NOT NULL, DEFAULT
-- literal, UNIQUE, CHECK, REFERENCES e CREATE INDEX. Sem AUTOINCREMENT, SERIAL,
-- IDENTITY nem funções de data de um banco específico.
-- IDs: UUID em texto gerado em Python (uuid.uuid4).
-- Datas: texto ISO-8601 UTC de tamanho fixo (ex.: 2026-01-31T12:00:00Z), gravado
-- pela aplicação. Esse formato ordena e compara corretamente como texto.
-- O controle de transação fica a cargo do aplicador (app/migracoes.py), por isso
-- este arquivo não contém BEGIN nem COMMIT.

CREATE TABLE empresas (
    id TEXT PRIMARY KEY,
    nome VARCHAR(200) NOT NULL CHECK (nome <> ''),
    criado_em VARCHAR(32) NOT NULL
);

-- E-mail único no sistema inteiro (o login é só por e-mail).
-- A senha só pode ser gravada como hash no formato scrypt$...
-- UNIQUE (id, empresa_id) permite que sessoes garanta, por chave estrangeira
-- composta, que a empresa da sessão é a mesma do usuário.
CREATE TABLE usuarios (
    id TEXT PRIMARY KEY,
    empresa_id TEXT NOT NULL REFERENCES empresas (id),
    email VARCHAR(254) NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL CHECK (senha_hash LIKE 'scrypt$%'),
    criado_em VARCHAR(32) NOT NULL,
    UNIQUE (id, empresa_id)
);

-- Sessões de login referenciadas pelo token assinado. Logout apaga a linha.
CREATE TABLE sessoes (
    id TEXT PRIMARY KEY,
    usuario_id TEXT NOT NULL REFERENCES usuarios (id),
    empresa_id TEXT NOT NULL REFERENCES empresas (id),
    expira_em VARCHAR(32) NOT NULL,
    criado_em VARCHAR(32) NOT NULL,
    FOREIGN KEY (usuario_id, empresa_id) REFERENCES usuarios (id, empresa_id)
);

-- Clientes de cada empresa. Toda consulta da aplicação filtra por empresa_id.
CREATE TABLE clientes (
    id TEXT PRIMARY KEY,
    empresa_id TEXT NOT NULL REFERENCES empresas (id),
    nome VARCHAR(200) NOT NULL CHECK (nome <> ''),
    email VARCHAR(254),
    telefone VARCHAR(40),
    observacoes VARCHAR(2000),
    status VARCHAR(10) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em VARCHAR(32) NOT NULL,
    atualizado_em VARCHAR(32) NOT NULL
);

CREATE INDEX ix_clientes_empresa_nome ON clientes (empresa_id, nome);
