"""Conexão com o SQLite e executor das migrações versionadas.

- conectar(caminho): abre a conexão sqlite3 com PRAGMA foreign_keys=ON e
  row_factory=sqlite3.Row (linhas acessíveis por nome de coluna).
- migrar(conexao, pasta): cria schema_migrations, lê migrations/NNNN_*.sql em
  ordem numérica e aplica, cada uma numa transação própria, só as versões
  ainda não registradas. Rodar de novo não faz nada (idempotente).

Cada versão aplicada é registrada com o sha256 do arquivo; se um arquivo já
aplicado mudar, o executor recusa com ErroMigracao (mudanças de esquema entram
num novo arquivo NNNN_*.sql).
"""
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PASTA_MIGRACOES = Path(__file__).resolve().parent.parent / "migrations"
_NOME_VALIDO = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_CRIAR_CONTROLE = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "versao TEXT PRIMARY KEY, "
    "sha256 VARCHAR(64) NOT NULL, "
    "aplicada_em VARCHAR(32) NOT NULL)"
)


class ErroMigracao(RuntimeError):
    """Problema nos arquivos de migração ou no histórico do banco."""


def agora_iso():
    """Data e hora atuais em UTC no formato ISO-8601 usado no banco."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conectar(caminho):
    """Abre a conexão SQLite com chaves estrangeiras ativas e linhas sqlite3.Row."""
    conexao = sqlite3.connect(str(caminho))
    try:
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        conexao.close()
        raise
    return conexao


def listar_migracoes(pasta=PASTA_MIGRACOES):
    """Devolve [(versao, caminho)] em ordem numérica, validando os nomes.

    Nomes aceitos: NNNN_nome.sql (quatro dígitos, nome em minúsculas).
    Números repetidos ou nomes fora do padrão geram ErroMigracao.
    """
    encontrados = {}
    for arq in Path(pasta).glob("*.sql"):
        achado = _NOME_VALIDO.match(arq.name)
        if not achado:
            raise ErroMigracao(f"nome de migração inválido: {arq.name} (use NNNN_nome.sql)")
        numero = int(achado.group(1))
        if numero in encontrados:
            raise ErroMigracao(f"número de migração repetido: {achado.group(1)}")
        encontrados[numero] = arq
    return [(encontrados[n].stem, encontrados[n]) for n in sorted(encontrados)]


def migrar(conexao, pasta=PASTA_MIGRACOES):
    """Aplica na `conexao` as migrações pendentes de `pasta`.

    Devolve a lista de versões aplicadas nesta chamada ([] se já estava em dia).
    Cada migração roda numa transação: se falhar, nada dela fica no banco e o
    erro é propagado. A conexão não pode ter transação aberta ao ser chamada.
    """
    migracoes = listar_migracoes(pasta)
    if conexao.in_transaction:
        raise ErroMigracao("a conexão tem uma transação aberta; faça commit ou rollback antes de migrar")
    nivel_anterior = conexao.isolation_level
    # isolation_level=None: o executor controla BEGIN/COMMIT/ROLLBACK explicitamente.
    conexao.isolation_level = None
    try:
        conexao.execute(_CRIAR_CONTROLE)
        feitas = {linha[0]: linha[1]
                  for linha in conexao.execute("SELECT versao, sha256 FROM schema_migrations")}
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
                conexao.executescript("BEGIN;\n" + sql)
                conexao.execute(
                    "INSERT INTO schema_migrations (versao, sha256, aplicada_em) VALUES (?, ?, ?)",
                    (versao, resumo, agora_iso()))
                conexao.execute("COMMIT")
            except BaseException:
                if conexao.in_transaction:
                    conexao.execute("ROLLBACK")
                raise
            aplicadas.append(versao)
        return aplicadas
    finally:
        conexao.isolation_level = nivel_anterior
