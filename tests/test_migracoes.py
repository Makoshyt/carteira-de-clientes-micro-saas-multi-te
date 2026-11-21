import re
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from app import migracoes
from tests import ficticio

RAIZ = Path(__file__).resolve().parent.parent
MIGRACAO_0001 = RAIZ / "migrations" / "0001_inicial.sql"
DATA = "2026-01-01T00:00:00Z"
HASH_FICTICIO = "scrypt$16384$8$1$c2Fs$aGFzaA=="  # formato apenas, não é senha real


def _id():
    return str(uuid.uuid4())


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "teste.db")

    def tearDown(self):
        self.tmp.cleanup()

    def conectar(self):
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(con.close)
        return con


class TestAplicacao(BaseBanco):
    def test_aplica_e_e_idempotente(self):
        self.assertEqual(migracoes.aplicar(self.db), ["0001_inicial"])
        self.assertEqual(migracoes.aplicar(self.db), [])
        self.assertEqual(migracoes.aplicar(self.db), [])
        con = self.conectar()
        linhas = con.execute("SELECT versao, sha256, aplicada_em FROM schema_migrations").fetchall()
        versoes = [v for v, _, _ in linhas]
        self.assertEqual(sorted(versoes), sorted(v for v, _ in migracoes.listar()))
        self.assertEqual(len(versoes), len(set(versoes)))
        for _, sha, aplicada_em in linhas:
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            self.assertRegex(aplicada_em, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_tabelas_e_colunas(self):
        migracoes.aplicar(self.db)
        con = self.conectar()
        esperado = {
            "empresas": ["id", "nome", "criado_em"],
            "usuarios": ["id", "empresa_id", "email", "senha_hash", "criado_em"],
            "sessoes": ["id", "usuario_id", "empresa_id", "expira_em", "criado_em"],
            "clientes": ["id", "empresa_id", "nome", "email", "telefone", "observacoes",
                         "status", "criado_em", "atualizado_em"],
        }
        for tabela, colunas in esperado.items():
            with self.subTest(tabela=tabela):
                info = con.execute(f"PRAGMA table_info({tabela})").fetchall()  # nosec B608 - nome fixo
                self.assertEqual([c[1] for c in info], colunas)
                pk = [c[1] for c in info if c[5]]
                self.assertEqual(pk, ["id"])
                tipo_id = [c[2] for c in info if c[1] == "id"][0]
                self.assertEqual(tipo_id, "TEXT")

    def test_indice_clientes_empresa_nome(self):
        migracoes.aplicar(self.db)
        con = self.conectar()
        indices = {linha[1] for linha in con.execute("PRAGMA index_list(clientes)")}
        self.assertIn("ix_clientes_empresa_nome", indices)
        colunas = [linha[2] for linha in con.execute("PRAGMA index_info(ix_clientes_empresa_nome)")]
        self.assertEqual(colunas, ["empresa_id", "nome"])

    def test_migracao_alterada_e_recusada(self):
        pasta = Path(self.tmp.name) / "mig"
        pasta.mkdir()
        arq = pasta / "0001_teste.sql"
        arq.write_text("CREATE TABLE a (id TEXT PRIMARY KEY);\n", encoding="utf-8")
        self.assertEqual(migracoes.aplicar(self.db, pasta), ["0001_teste"])
        arq.write_text("CREATE TABLE a (id TEXT PRIMARY KEY, x TEXT);\n", encoding="utf-8")
        with self.assertRaises(migracoes.ErroMigracao):
            migracoes.aplicar(self.db, pasta)

    def test_migracao_com_erro_e_desfeita_por_inteiro(self):
        pasta = Path(self.tmp.name) / "mig"
        pasta.mkdir()
        (pasta / "0001_ok.sql").write_text("CREATE TABLE a (id TEXT PRIMARY KEY);\n", encoding="utf-8")
        (pasta / "0002_quebrada.sql").write_text(
            "CREATE TABLE b (id TEXT PRIMARY KEY);\nCREATE TABLE ERRO DE SINTAXE;\n", encoding="utf-8")
        with self.assertRaises(sqlite3.Error):
            migracoes.aplicar(self.db, pasta)
        con = self.conectar()
        tabelas = {t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("a", tabelas)
        self.assertNotIn("b", tabelas)
        versoes = [v for (v,) in con.execute("SELECT versao FROM schema_migrations")]
        self.assertEqual(versoes, ["0001_ok"])

    def test_nomes_invalidos_ou_repetidos(self):
        for nomes in (["1_x.sql"], ["0001_a.sql", "0001_b.sql"], ["0001_Maiuscula.sql"]):
            with self.subTest(nomes=nomes):
                pasta = Path(tempfile.mkdtemp(dir=self.tmp.name))
                for nome in nomes:
                    (pasta / nome).write_text("SELECT 1;\n", encoding="utf-8")
                with self.assertRaises(migracoes.ErroMigracao):
                    migracoes.listar(pasta)


class TestPortabilidade(unittest.TestCase):
    """Garante que o SQL só usa construções comuns a SQLite e PostgreSQL."""

    def setUp(self):
        texto = MIGRACAO_0001.read_text(encoding="utf-8")
        # remove comentários de linha para analisar só o SQL
        self.sql = "\n".join(linha.split("--", 1)[0] for linha in texto.splitlines())

    def test_sem_construcoes_especificas(self):
        proibidos = [r"AUTOINCREMENT", r"\bSERIAL\b", r"\bBIGSERIAL\b", r"\bIDENTITY\b",
                     r"\bstrftime\b", r"\bdatetime\s*\(", r"\bnow\s*\(", r"CURRENT_TIMESTAMP",
                     r"\bPRAGMA\b", r"TIMESTAMPTZ", r"::", r"\bWITHOUT\s+ROWID\b",
                     r"\bBEGIN\b", r"\bCOMMIT\b", r"\bINTEGER\s+PRIMARY\s+KEY\b",
                     r"\bIF\s+NOT\s+EXISTS\b", r"\bgen_random_uuid\b", r"\bILIKE\b"]
        for padrao in proibidos:
            with self.subTest(padrao=padrao):
                self.assertIsNone(re.search(padrao, self.sql, re.IGNORECASE))

    def test_so_tipos_text_e_varchar(self):
        for tabela, corpo in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", self.sql, re.S):
            for linha in corpo.splitlines():
                linha = linha.strip().rstrip(",")
                if not linha or linha.split()[0].upper() in ("UNIQUE", "FOREIGN", "CHECK", "PRIMARY"):
                    continue
                with self.subTest(tabela=tabela, coluna=linha.split()[0]):
                    self.assertRegex(linha.split()[1], r"^(TEXT|VARCHAR\(\d+\))$")

    def test_quatro_tabelas_e_indice(self):
        tabelas = re.findall(r"CREATE TABLE (\w+)", self.sql)
        self.assertEqual(tabelas, ["empresas", "usuarios", "sessoes", "clientes"])
        self.assertRegex(self.sql, r"CREATE INDEX ix_clientes_empresa_nome ON clientes \(empresa_id, nome\);")


class TestRestricoes(BaseBanco):
    def setUp(self):
        super().setUp()
        migracoes.aplicar(self.db)
        self.con = self.conectar()
        self.emp1 = self._empresa("Empresa Fictícia 1")
        self.emp2 = self._empresa("Empresa Fictícia 2")

    def _empresa(self, nome):
        eid = _id()
        self.con.execute("INSERT INTO empresas (id, nome, criado_em) VALUES (?, ?, ?)", (eid, nome, DATA))
        return eid

    def _usuario(self, empresa_id, email, senha_hash=HASH_FICTICIO):
        uid = _id()
        self.con.execute(
            "INSERT INTO usuarios (id, empresa_id, email, senha_hash, criado_em) VALUES (?, ?, ?, ?, ?)",
            (uid, empresa_id, email, senha_hash, DATA))
        return uid

    def _cliente(self, empresa_id, nome, status=None):
        if status is None:
            self.con.execute(
                "INSERT INTO clientes (id, empresa_id, nome, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?)",
                (_id(), empresa_id, nome, DATA, DATA))
        else:
            self.con.execute(
                "INSERT INTO clientes (id, empresa_id, nome, status, criado_em, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?, ?)", (_id(), empresa_id, nome, status, DATA, DATA))

    def test_email_unico_no_sistema(self):
        self._usuario(self.emp1, "ana@exemplo.invalid")
        with self.assertRaises(sqlite3.IntegrityError):
            self._usuario(self.emp2, "ana@exemplo.invalid")

    def test_senha_so_em_formato_scrypt(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._usuario(self.emp1, "bia@exemplo.invalid", senha_hash=ficticio.senha())

    def test_usuario_exige_empresa_existente(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._usuario(_id(), "caio@exemplo.invalid")

    def test_sessao_exige_mesma_empresa_do_usuario(self):
        uid = self._usuario(self.emp1, "duda@exemplo.invalid")
        sql = ("INSERT INTO sessoes (id, usuario_id, empresa_id, expira_em, criado_em) "
               "VALUES (?, ?, ?, ?, ?)")
        self.con.execute(sql, (_id(), uid, self.emp1, DATA, DATA))
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(sql, (_id(), uid, self.emp2, DATA, DATA))

    def test_cliente_status_padrao_e_valores_validos(self):
        self._cliente(self.emp1, "Cliente A")
        self._cliente(self.emp1, "Cliente B", "inativo")
        status = dict(self.con.execute("SELECT nome, status FROM clientes"))
        self.assertEqual(status, {"Cliente A": "ativo", "Cliente B": "inativo"})
        with self.assertRaises(sqlite3.IntegrityError):
            self._cliente(self.emp1, "Cliente C", "bloqueado")

    def test_cliente_nome_obrigatorio_e_empresa_obrigatoria(self):
        for nome in (None, ""):
            with self.subTest(nome=nome), self.assertRaises(sqlite3.IntegrityError):
                self._cliente(self.emp1, nome)
        with self.assertRaises(sqlite3.IntegrityError):
            self._cliente(None, "Sem empresa")
        with self.assertRaises(sqlite3.IntegrityError):
            self._cliente(_id(), "Empresa inexistente")


if __name__ == "__main__":
    unittest.main()
