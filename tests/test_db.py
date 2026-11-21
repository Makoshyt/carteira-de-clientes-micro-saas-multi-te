import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import db


class BaseDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.caminho = str(Path(self.tmp.name) / "teste.db")

    def conectar(self, caminho=None):
        con = db.conectar(caminho or self.caminho)
        self.addCleanup(con.close)
        return con

    def pasta(self, arquivos):
        pasta = Path(tempfile.mkdtemp(dir=self.tmp.name))
        for nome, sql in arquivos.items():
            (pasta / nome).write_text(sql, encoding="utf-8")
        return pasta


class TestConectar(BaseDb):
    def test_foreign_keys_e_row_factory(self):
        con = self.conectar()
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertIs(con.row_factory, sqlite3.Row)
        linha = con.execute("SELECT 1 AS um").fetchone()
        self.assertEqual(linha["um"], 1)

    def test_memoria(self):
        con = self.conectar(":memory:")
        self.assertEqual(db.migrar(con), [v for v, _ in db.listar_migracoes()])
        self.assertEqual(db.migrar(con), [])


class TestMigrar(BaseDb):
    def test_idempotente_um_registro_por_versao(self):
        con = self.conectar()
        esperadas = [v for v, _ in db.listar_migracoes()]
        self.assertIn("0001_inicial", esperadas)
        self.assertEqual(db.migrar(con), esperadas)
        self.assertEqual(db.migrar(con), [])
        con2 = self.conectar()  # outra conexão no mesmo arquivo
        self.assertEqual(db.migrar(con2), [])
        linhas = con2.execute(
            "SELECT versao, aplicada_em FROM schema_migrations ORDER BY versao").fetchall()
        self.assertEqual([linha["versao"] for linha in linhas], esperadas)
        for linha in linhas:
            self.assertRegex(linha["aplicada_em"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        colunas = [c[1] for c in con2.execute("PRAGMA table_info(schema_migrations)")]
        self.assertIn("versao", colunas)
        self.assertIn("aplicada_em", colunas)

    def test_ordem_numerica_e_so_pendentes(self):
        pasta = self.pasta({
            "0010_c.sql": "CREATE TABLE c (id TEXT PRIMARY KEY, b_id TEXT REFERENCES b (id));\n",
            "0002_b.sql": "CREATE TABLE b (id TEXT PRIMARY KEY, a_id TEXT REFERENCES a (id));\n",
            "0001_a.sql": "CREATE TABLE a (id TEXT PRIMARY KEY);\n",
        })
        self.assertEqual([v for v, _ in db.listar_migracoes(pasta)], ["0001_a", "0002_b", "0010_c"])
        con = self.conectar()
        self.assertEqual(db.migrar(con, pasta), ["0001_a", "0002_b", "0010_c"])
        (pasta / "0011_d.sql").write_text("CREATE TABLE d (id TEXT PRIMARY KEY);\n", encoding="utf-8")
        self.assertEqual(db.migrar(con, pasta), ["0011_d"])
        self.assertEqual(db.migrar(con, pasta), [])
        total = con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        self.assertEqual(total, 4)

    def test_falha_desfaz_so_a_migracao_quebrada(self):
        pasta = self.pasta({
            "0001_ok.sql": "CREATE TABLE a (id TEXT PRIMARY KEY);\n",
            "0002_quebrada.sql": "CREATE TABLE b (id TEXT PRIMARY KEY);\nCREATE TABLE ERRO DE SINTAXE;\n",
        })
        con = self.conectar()
        with self.assertRaises(sqlite3.Error):
            db.migrar(con, pasta)
        self.assertFalse(con.in_transaction)
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("a", tabelas)
        self.assertNotIn("b", tabelas)
        versoes = [r[0] for r in con.execute("SELECT versao FROM schema_migrations")]
        self.assertEqual(versoes, ["0001_ok"])

    def test_migracao_alterada_e_recusada(self):
        pasta = self.pasta({"0001_a.sql": "CREATE TABLE a (id TEXT PRIMARY KEY);\n"})
        con = self.conectar()
        db.migrar(con, pasta)
        (pasta / "0001_a.sql").write_text("CREATE TABLE a (id TEXT PRIMARY KEY, x TEXT);\n",
                                          encoding="utf-8")
        with self.assertRaises(db.ErroMigracao):
            db.migrar(con, pasta)

    def test_recusa_transacao_aberta(self):
        con = self.conectar()
        db.migrar(con)
        con.execute("CREATE TABLE t (x TEXT)")
        con.execute("INSERT INTO t (x) VALUES ('a')")  # abre transação implícita
        self.assertTrue(con.in_transaction)
        with self.assertRaises(db.ErroMigracao):
            db.migrar(con)
        con.rollback()

    def test_restaura_isolation_level(self):
        con = self.conectar()
        antes = con.isolation_level
        db.migrar(con)
        self.assertEqual(con.isolation_level, antes)
        # a conexão continua utilizável no modo transacional padrão
        con.execute("INSERT INTO empresas (id, nome, criado_em) VALUES ('e1', 'Fictícia', 'x')")
        con.rollback()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM empresas").fetchone()[0], 0)

    def test_nomes_invalidos(self):
        for nomes in (["1_x.sql"], ["0001_a.sql", "0001_b.sql"], ["0001_Maiuscula.sql"]):
            with self.subTest(nomes=nomes):
                pasta = self.pasta({nome: "SELECT 1;\n" for nome in nomes})
                with self.assertRaises(db.ErroMigracao):
                    db.migrar(self.conectar(), pasta)


if __name__ == "__main__":
    unittest.main()
