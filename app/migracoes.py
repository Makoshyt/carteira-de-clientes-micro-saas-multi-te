"""Aplica as migrações versionadas de migrations/NNNN_nome.sql no SQLite.

Os arquivos SQL são portáveis (SQLite e PostgreSQL). Cada versão aplicada é
registrada em schema_migrations com o sha256 do arquivo; uma migração já
aplicada nunca é reaplicada e não pode ser alterada. Cada migração roda numa
transação própria: se falhar, nada dela fica no banco.
"""
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "migrations"
_NOME_VALIDO = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_CRIAR_CONTROLE = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "versao VARCHAR(100) PRIMARY KEY, "
    "sha256 VARCHAR(64) NOT NULL, "
    "aplicada_em VARCHAR(32) NOT NULL)"
)


class ErroMigracao(RuntimeError):
    """Problema nos arquivos de migração ou no histórico do banco."""


def agora_iso():
    """Data e hora atuais em UTC no formato ISO-8601 usado no banco."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def listar(pasta=PASTA_PADRAO):
    """Devolve [(versao, caminho)] em ordem numérica, validando os nomes."""
    resultado, numeros = [], set()
    for arq in sorted(Path(pasta).glob("*.sql")):
        achado = _NOME_VALIDO.match(arq.name)
        if not achado:
            raise ErroMigracao(f"nome de migração inválido: {arq.name} (use NNNN_nome.sql)")
        if achado.group(1) in numeros:
            raise ErroMigracao(f"número de migração repetido: {achado.group(1)}")
        numeros.add(achado.group(1))
        resultado.append((arq.stem, arq))
    return resultado


def aplicar(caminho, pasta=PASTA_PADRAO):
    """Aplica as migrações pendentes no banco SQLite `caminho`.

    Devolve a lista de versões aplicadas nesta chamada ([] se já estava atualizado).
    """
    migracoes = listar(pasta)
    # isolation_level=None: o próprio código controla BEGIN/COMMIT/ROLLBACK.
    con = sqlite3.connect(str(caminho), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute(_CRIAR_CONTROLE)
        feitas = dict(con.execute("SELECT versao, sha256 FROM schema_migrations"))
        aplicadas = []
        for versao, arq in migracoes:
            sql = arq.read_text(encoding="utf-8")
            resumo = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if versao in feitas:
                if feitas[versao] != resumo:
                    raise ErroMigracao(
                        f"a migração {versao} difere da que foi aplicada neste banco; "
                        "migrações aplicadas não podem ser alteradas (crie uma nova "
                        "NNNN_*.sql) ou, se o banco tiver só dados fictícios, apague-o")
                continue
            try:
                con.executescript("BEGIN;\n" + sql)
                con.execute(
                    "INSERT INTO schema_migrations (versao, sha256, aplicada_em) VALUES (?, ?, ?)",
                    (versao, resumo, agora_iso()))
                con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
            aplicadas.append(versao)
        return aplicadas
    finally:
        con.close()
