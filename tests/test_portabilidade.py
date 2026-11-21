"""Portabilidade SQLite -> PostgreSQL das migrações e das consultas da aplicação.

- Lê todos os arquivos migrations/*.sql e falha se encontrar construções específicas do
  SQLite (AUTOINCREMENT, INSERT OR REPLACE, datetime('now'), PRAGMA, tipos dinâmicos...).
- Garante que PRAGMA só aparece em app/db.py e que toda consulta com parâmetros da
  aplicação passa por app.db.consulta_sql (único ponto que conhece ``?``/``%s``).
- Testa a própria função consulta_sql.
"""
import ast
import re
import sqlite3
import unittest
from pathlib import Path

from app import db
from app.db import consulta_sql

RAIZ = Path(__file__).resolve().parent.parent
PASTA_MIGRACOES = RAIZ / "migrations"
PASTA_APP = RAIZ / "app"

# (descrição, regex) de construções que não existem ou mudam de sentido no PostgreSQL.
PROIBIDOS = [
    ("AUTOINCREMENT", r"\bAUTOINCREMENT\b"),
    ("INSERT OR REPLACE/IGNORE/ABORT/FAIL/ROLLBACK", r"\bINSERT\s+OR\s+\w+"),
    ("REPLACE INTO", r"\bREPLACE\s+INTO\b"),
    ("UPDATE OR ...", r"\bUPDATE\s+OR\s+\w+"),
    ("datetime()/date()/time()/julianday()/strftime()", r"\b(datetime|date|time|julianday|strftime|unixepoch)\s*\("),
    ("'now'", r"'now'"),
    ("PRAGMA", r"\bPRAGMA\b"),
    ("WITHOUT ROWID", r"\bWITHOUT\s+ROWID\b"),
    ("tabela STRICT", r"\)\s*STRICT\b"),
    ("ATTACH/DETACH", r"\b(ATTACH|DETACH)\b"),
    ("VACUUM", r"\bVACUUM\b"),
    ("GLOB", r"\bGLOB\b"),
    ("COLLATE NOCASE", r"\bNOCASE\b"),
    ("rowid", r"\b(_?rowid_?|oid)\b"),
    ("INTEGER PRIMARY KEY (alias de rowid)", r"\bINTEGER\s+PRIMARY\s+KEY\b"),
    ("SERIAL/IDENTITY (só PostgreSQL)", r"\b(BIG)?SERIAL\b|\bIDENTITY\b"),
    ("cast ::tipo (só PostgreSQL)", r"::"),
    ("BEGIN/COMMIT (a transação é do aplicador)", r"\b(BEGIN|COMMIT)\b"),
]

# Tipos aceitos nas colunas (mesmo significado nos dois bancos). Qualquer outro nome de
# tipo, ou coluna sem tipo, é "tipo dinâmico" do SQLite e reprova.
TIPO_PERMITIDO = re.compile(
    r"^(TEXT|VARCHAR\(\d+\)|INTEGER|BIGINT|SMALLINT|BOOLEAN|NUMERIC\(\d+,\s*\d+\))$", re.I)
_RESTRICOES_DE_TABELA = ("UNIQUE", "FOREIGN", "CHECK", "PRIMARY", "CONSTRAINT")


def sem_comentarios(texto):
    """Remove comentários de linha (--) e de bloco (/* */)."""
    texto = re.sub(r"/\*.*?\*/", " ", texto, flags=re.S)
    return "\n".join(linha.split("--", 1)[0] for linha in texto.splitlines())


def construcoes_proibidas(texto):
    """Devolve as descrições das construções não portáveis encontradas no SQL."""
    sql_limpo = sem_comentarios(texto)
    return [desc for desc, padrao in PROIBIDOS if re.search(padrao, sql_limpo, re.I)]


def _dividir_colunas(corpo):
    """Divide o corpo de CREATE TABLE nas vírgulas de nível 0 (fora de parênteses)."""
    partes, atual, nivel = [], [], 0
    for caractere in corpo:
        if caractere == "(":
            nivel += 1
        elif caractere == ")":
            nivel -= 1
        if caractere == "," and nivel == 0:
            partes.append("".join(atual))
            atual = []
        else:
            atual.append(caractere)
    partes.append("".join(atual))
    return [p.strip() for p in partes if p.strip()]


def tipos_dinamicos(texto):
    """Devolve ["tabela.coluna: definição"] das colunas sem tipo ou com tipo não aceito."""
    problemas = []
    sql_limpo = sem_comentarios(texto)
    for achado in re.finditer(r"CREATE\s+TABLE\s+(\w+)\s*\(", sql_limpo, re.I):
        inicio = achado.end()
        nivel, fim = 1, inicio
        while fim < len(sql_limpo) and nivel:
            nivel += {"(": 1, ")": -1}.get(sql_limpo[fim], 0)
            fim += 1
        for definicao in _dividir_colunas(sql_limpo[inicio:fim - 1]):
            palavras = definicao.split()
            if palavras[0].upper() in _RESTRICOES_DE_TABELA:
                continue
            tipo = re.match(r"\s*\w+\s+(\w+(?:\s*\([^)]*\))?)", definicao)
            if not tipo or not TIPO_PERMITIDO.match(tipo.group(1)):
                problemas.append(f"{achado.group(1)}.{palavras[0]}: {definicao}")
    return problemas


class TestDetector(unittest.TestCase):
    """O detector precisa reprovar exemplos não portáveis (senão o teste seria vazio)."""

    def test_reprova_exemplos(self):
        exemplos = [
            "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT);",
            "INSERT OR REPLACE INTO t (id) VALUES (1);",
            "INSERT OR IGNORE INTO t (id) VALUES (1);",
            "REPLACE INTO t (id) VALUES (1);",
            "CREATE TABLE t (id TEXT, criado TEXT DEFAULT (datetime('now')));",
            "CREATE TABLE t (id TEXT, criado TEXT DEFAULT (strftime('%s', 'now')));",
            "PRAGMA foreign_keys = ON;",
            "CREATE TABLE t (id TEXT PRIMARY KEY) WITHOUT ROWID;",
            "CREATE TABLE t (id TEXT PRIMARY KEY) STRICT;",
            "CREATE TABLE t (id SERIAL PRIMARY KEY);",
            "SELECT 1::text;",
        ]
        for exemplo in exemplos:
            with self.subTest(exemplo=exemplo):
                self.assertTrue(construcoes_proibidas(exemplo))

    def test_ignora_comentarios(self):
        self.assertEqual(construcoes_proibidas("-- sem AUTOINCREMENT nem PRAGMA\n/* datetime('now') */\n"
                                               "CREATE TABLE t (id TEXT PRIMARY KEY);"), [])

    def test_tipos_dinamicos(self):
        self.assertTrue(tipos_dinamicos("CREATE TABLE t (id TEXT PRIMARY KEY, livre);"))
        self.assertTrue(tipos_dinamicos("CREATE TABLE t (id TEXT PRIMARY KEY, x STRING);"))
        self.assertTrue(tipos_dinamicos("CREATE TABLE t (id TEXT PRIMARY KEY, x BLOB);"))
        self.assertTrue(tipos_dinamicos("CREATE TABLE t (id TEXT PRIMARY KEY, x ANY);"))
        self.assertEqual(tipos_dinamicos(
            "CREATE TABLE t (id TEXT PRIMARY KEY, n VARCHAR(10) NOT NULL CHECK (n IN ('a', 'b')), "
            "v NUMERIC(10, 2), UNIQUE (id, n));"), [])


class TestMigracoesPortaveis(unittest.TestCase):
    def setUp(self):
        self.arquivos = sorted(PASTA_MIGRACOES.glob("*.sql"))

    def test_ha_migracoes(self):
        self.assertTrue(self.arquivos, "nenhum arquivo migrations/*.sql encontrado")

    def test_sem_construcoes_especificas_do_sqlite(self):
        for arq in self.arquivos:
            with self.subTest(arquivo=arq.name):
                self.assertEqual(construcoes_proibidas(arq.read_text(encoding="utf-8")), [])

    def test_sem_tipos_dinamicos(self):
        for arq in self.arquivos:
            with self.subTest(arquivo=arq.name):
                self.assertEqual(tipos_dinamicos(arq.read_text(encoding="utf-8")), [])

    def test_todas_as_colunas_tem_tipo_declarado_no_banco(self):
        con = sqlite3.connect(":memory:")
        try:
            db.migrar(con, PASTA_MIGRACOES)
            tabelas = [linha[0] for linha in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")]
            for tabela in tabelas:
                for coluna in con.execute(f"PRAGMA table_info({tabela})"):  # nosec B608 - nome do catálogo
                    with self.subTest(tabela=tabela, coluna=coluna[1]):
                        self.assertTrue(TIPO_PERMITIDO.match(coluna[2]), coluna[2])
        finally:
            con.close()


def _arquivos_app():
    return sorted(PASTA_APP.glob("*.py"))


def _textos_literais(arvore):
    for no in ast.walk(arvore):
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            yield no


class TestConsultasDaAplicacao(unittest.TestCase):
    def test_pragma_so_em_db_py(self):
        for arq in _arquivos_app():
            if arq.name == "db.py":
                continue
            with self.subTest(arquivo=arq.name):
                self.assertNotRegex(arq.read_text(encoding="utf-8"), r"(?i)\bPRAGMA\b")

    def test_consultas_sem_construcoes_especificas(self):
        for arq in _arquivos_app():
            arvore = ast.parse(arq.read_text(encoding="utf-8"))
            for no in _textos_literais(arvore):
                if re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE)\b", no.value, re.I):
                    with self.subTest(arquivo=arq.name, linha=no.lineno):
                        achados = [d for d in construcoes_proibidas(no.value) if d != "PRAGMA"]
                        self.assertEqual(achados, [])

    def test_consultas_com_parametro_passam_por_consulta_sql(self):
        for arq in _arquivos_app():
            arvore = ast.parse(arq.read_text(encoding="utf-8"))
            embrulhados = set()
            for no in ast.walk(arvore):
                if (isinstance(no, ast.Call) and isinstance(no.func, ast.Name)
                        and no.func.id == "consulta_sql" and no.args):
                    embrulhados.add(id(no.args[0]))
            for no in _textos_literais(arvore):
                if re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE)\b", no.value, re.I) and "?" in no.value:
                    with self.subTest(arquivo=arq.name, linha=no.lineno):
                        self.assertIn(id(no), embrulhados,
                                      "consulta com parâmetro fora de consulta_sql()")


class TestConsultaSql(unittest.TestCase):
    def test_padrao_e_qmark_do_sqlite(self):
        self.assertEqual(db.ESTILO_PARAMETRO, "qmark")
        texto = "SELECT 1 FROM t WHERE a = ? AND b LIKE 'x%'"
        self.assertEqual(consulta_sql(texto), texto)
        self.assertEqual(consulta_sql(texto, "qmark"), texto)

    def test_format_para_psycopg(self):
        self.assertEqual(consulta_sql("SELECT a FROM t WHERE a = ? AND b = ?", "format"),
                         "SELECT a FROM t WHERE a = %s AND b = %s")

    def test_format_preserva_literais_e_escapa_porcentagem(self):
        self.assertEqual(
            consulta_sql("SELECT '?' FROM t WHERE n LIKE LOWER(?) ESCAPE '\\' AND m LIKE 'a%'", "format"),
            "SELECT '?' FROM t WHERE n LIKE LOWER(%s) ESCAPE '\\' AND m LIKE 'a%%'")
        self.assertEqual(consulta_sql('SELECT "col?" FROM t WHERE x = ?', "format"),
                         'SELECT "col?" FROM t WHERE x = %s')

    def test_estilo_invalido_ou_literal_aberto(self):
        with self.assertRaises(ValueError):
            consulta_sql("SELECT 1", "named")
        with self.assertRaises(ValueError):
            consulta_sql("SELECT 'aberto FROM t WHERE x = ?", "format")

    def test_consultas_da_aplicacao_convertem_para_format(self):
        from app import clientes
        for nome in [n for n in dir(clientes) if n.startswith("_SQL_")]:
            original = getattr(clientes, nome)
            convertida = consulta_sql(original, "format")
            with self.subTest(consulta=nome):
                self.assertEqual(convertida.count("%s"), original.count("?"))
                self.assertNotIn("?", convertida)


if __name__ == "__main__":
    unittest.main()
