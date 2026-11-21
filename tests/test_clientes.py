"""Testes da camada de dados de clientes (app/clientes.py), incluindo isolamento entre empresas."""
import tempfile
import unittest
from pathlib import Path

from app import clientes
from app.db import conectar, migrar
from app.web import ErroHttp

AGORA = "2026-01-01T00:00:00Z"


class BaseClientes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.con = conectar(str(Path(tmp.name) / "t.db"))
        self.addCleanup(self.con.close)
        migrar(self.con)
        with self.con:
            for empresa_id, nome in (("emp-a", "Empresa A Fictícia"), ("emp-b", "Empresa B Fictícia")):
                self.con.execute("INSERT INTO empresas (id, nome, criado_em) VALUES (?, ?, ?)",
                                 (empresa_id, nome, AGORA))

    def contar(self):
        return self.con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

    def linhas(self):
        return [tuple(r) for r in self.con.execute("SELECT * FROM clientes ORDER BY id")]

    def assertErro400(self, funcao, *args, campo=None):
        with self.assertRaises(ErroHttp) as ctx:
            funcao(*args)
        self.assertEqual(ctx.exception.status, 400)
        if campo:
            self.assertIn(campo, ctx.exception.mensagem)


class TestCrud(BaseClientes):
    def test_criar_com_padroes(self):
        c = clientes.criar(self.con, "emp-a", {"nome": "  Ana Fictícia  "})
        self.assertEqual(c["nome"], "Ana Fictícia")
        self.assertEqual(c["status"], "ativo")
        self.assertIsNone(c["email"])
        self.assertIsNone(c["telefone"])
        self.assertIsNone(c["observacoes"])
        self.assertEqual(c["criado_em"], c["atualizado_em"])
        self.assertNotIn("empresa_id", c)
        linha = self.con.execute("SELECT empresa_id FROM clientes WHERE id = ?", (c["id"],)).fetchone()
        self.assertEqual(linha[0], "emp-a")

    def test_criar_completo(self):
        dados = {"nome": "Bruno Fictício", "email": " Bruno@Exemplo.TEST ", "telefone": "+55 11 0000-0000",
                 "observacoes": "linha 1\nlinha 2", "status": "inativo"}
        c = clientes.criar(self.con, "emp-a", dados)
        self.assertEqual(c["email"], "bruno@exemplo.test")
        self.assertEqual(c["telefone"], "+55 11 0000-0000")
        self.assertEqual(c["observacoes"], "linha 1\nlinha 2")
        self.assertEqual(c["status"], "inativo")
        self.assertEqual(clientes.obter(self.con, "emp-a", c["id"]), c)

    def test_ids_enviados_sao_ignorados(self):
        c = clientes.criar(self.con, "emp-a", {"nome": "Ana", "id": "forjado", "empresa_id": "emp-b"})
        self.assertNotEqual(c["id"], "forjado")
        self.assertEqual(clientes.listar(self.con, "emp-b"), [])
        self.assertEqual(len(clientes.listar(self.con, "emp-a")), 1)

    def test_obter_inexistente(self):
        self.assertIsNone(clientes.obter(self.con, "emp-a", "nao-existe"))
        self.assertIsNone(clientes.obter(self.con, "emp-a", 123))

    def test_atualizar_parcial(self):
        c = clientes.criar(self.con, "emp-a", {"nome": "Ana", "email": "ana@exemplo.test",
                                               "telefone": "1234"})
        novo = clientes.atualizar(self.con, "emp-a", c["id"], {"status": "inativo", "telefone": ""})
        self.assertEqual(novo["status"], "inativo")
        self.assertIsNone(novo["telefone"])
        self.assertEqual(novo["nome"], "Ana")
        self.assertEqual(novo["email"], "ana@exemplo.test")
        self.assertEqual(novo["criado_em"], c["criado_em"])

    def test_atualizar_inexistente(self):
        self.assertIsNone(clientes.atualizar(self.con, "emp-a", "nao-existe", {"nome": "X"}))

    def test_excluir(self):
        c = clientes.criar(self.con, "emp-a", {"nome": "Ana"})
        self.assertTrue(clientes.excluir(self.con, "emp-a", c["id"]))
        self.assertIsNone(clientes.obter(self.con, "emp-a", c["id"]))
        self.assertFalse(clientes.excluir(self.con, "emp-a", c["id"]))
        self.assertEqual(self.contar(), 0)

    def test_empresa_id_obrigatorio(self):
        for empresa in (None, "", 1):
            with self.subTest(empresa=empresa):
                with self.assertRaises(ValueError):
                    clientes.listar(self.con, empresa)
                with self.assertRaises(ValueError):
                    clientes.criar(self.con, empresa, {"nome": "Ana"})
        self.assertEqual(self.contar(), 0)


class TestBusca(BaseClientes):
    def setUp(self):
        super().setUp()
        for nome in ("Mariana Fictícia", "ANA Paula", "Bruno", "Juliana", "Carlos"):
            clientes.criar(self.con, "emp-a", {"nome": nome})
        clientes.criar(self.con, "emp-b", {"nome": "Ana da Empresa B"})

    def nomes(self, empresa, busca=None):
        return [c["nome"] for c in clientes.listar(self.con, empresa, busca)]

    def test_lista_ordenada_por_nome(self):
        self.assertEqual(self.nomes("emp-a"),
                         ["ANA Paula", "Bruno", "Carlos", "Juliana", "Mariana Fictícia"])

    def test_busca_sem_diferenciar_maiusculas_e_so_da_empresa(self):
        self.assertEqual(self.nomes("emp-a", "ana"), ["ANA Paula", "Juliana", "Mariana Fictícia"])
        self.assertEqual(self.nomes("emp-a", "  AnA "), ["ANA Paula", "Juliana", "Mariana Fictícia"])
        self.assertEqual(self.nomes("emp-b", "ana"), ["Ana da Empresa B"])

    def test_busca_vazia_lista_tudo(self):
        self.assertEqual(len(self.nomes("emp-a", "")), 5)
        self.assertEqual(len(self.nomes("emp-a", "   ")), 5)

    def test_curingas_sao_literais(self):
        clientes.criar(self.con, "emp-a", {"nome": "Cem % Fictício"})
        clientes.criar(self.con, "emp-a", {"nome": "nome_com_sublinhado"})
        clientes.criar(self.con, "emp-a", {"nome": "barra \\ invertida"})
        self.assertEqual(self.nomes("emp-a", "%"), ["Cem % Fictício"])
        self.assertEqual(self.nomes("emp-a", "_"), ["nome_com_sublinhado"])
        self.assertEqual(self.nomes("emp-a", "\\"), ["barra \\ invertida"])
        self.assertEqual(self.nomes("emp-a", "a%a"), [])

    def test_limite_de_200(self):
        with self.con:
            self.con.executemany(
                "INSERT INTO clientes (id, empresa_id, nome, status, criado_em, atualizado_em) "
                "VALUES (?, 'emp-b', ?, 'ativo', ?, ?)",
                [(f"lote-{i:03d}", f"Lote {i:03d}", AGORA, AGORA) for i in range(250)])
        self.assertEqual(len(clientes.listar(self.con, "emp-b")), clientes.LIMITE_LISTAGEM)
        self.assertEqual(len(clientes.listar(self.con, "emp-b", "lote")), 200)
        self.assertEqual(len(clientes.listar(self.con, "emp-a")), 5)

    def test_busca_invalida(self):
        self.assertErro400(clientes.listar, self.con, "emp-a", "a" * 201, campo="busca")
        self.assertErro400(clientes.listar, self.con, "emp-a", 123, campo="busca")
        self.assertErro400(clientes.listar, self.con, "emp-a", "a\x00b", campo="busca")


class TestValidacao(BaseClientes):
    def test_criar_invalido_400_com_campo(self):
        casos = {
            "nome": [{}, {"nome": None}, {"nome": "   "}, {"nome": 5}, {"nome": "a" * 201},
                     {"nome": "Ana\nFictícia"}],
            "email": [{"nome": "Ana", "email": "sem-arroba"}, {"nome": "Ana", "email": 1},
                      {"nome": "Ana", "email": "a" * 250 + "@x.test"}],
            "telefone": [{"nome": "Ana", "telefone": 11}, {"nome": "Ana", "telefone": "1" * 41}],
            "observacoes": [{"nome": "Ana", "observacoes": ["x"]},
                            {"nome": "Ana", "observacoes": "o" * 2001},
                            {"nome": "Ana", "observacoes": "a\x00b"}],
            "status": [{"nome": "Ana", "status": "pendente"}, {"nome": "Ana", "status": None},
                       {"nome": "Ana", "status": "ATIVO"}],
        }
        for campo, lista in casos.items():
            for dados in lista:
                with self.subTest(campo=campo, dados=dados):
                    self.assertErro400(clientes.criar, self.con, "emp-a", dados, campo=campo)
        self.assertErro400(clientes.criar, self.con, "emp-a", ["nome"])
        self.assertEqual(self.contar(), 0)

    def test_limites_aceitos(self):
        c = clientes.criar(self.con, "emp-a", {"nome": "n" * 200, "telefone": "1" * 40,
                                               "observacoes": "o" * 2000, "email": ""})
        self.assertEqual(len(c["nome"]), 200)
        self.assertIsNone(c["email"])

    def test_atualizar_invalido_nao_muda_nada(self):
        c = clientes.criar(self.con, "emp-a", {"nome": "Ana"})
        antes = self.linhas()
        self.assertErro400(clientes.atualizar, self.con, "emp-a", c["id"], {"nome": ""}, campo="nome")
        self.assertErro400(clientes.atualizar, self.con, "emp-a", c["id"], {"status": "x"}, campo="status")
        self.assertErro400(clientes.atualizar, self.con, "emp-a", c["id"], {})
        self.assertErro400(clientes.atualizar, self.con, "emp-a", c["id"], {"empresa_id": "emp-b"})
        self.assertEqual(self.linhas(), antes)


class TestIsolamento(BaseClientes):
    def setUp(self):
        super().setUp()
        self.da_a = clientes.criar(self.con, "emp-a", {"nome": "Ana da A", "status": "ativo"})
        self.da_b = clientes.criar(self.con, "emp-b", {"nome": "Ana da B"})

    def test_listar_so_da_propria_empresa(self):
        self.assertEqual([c["id"] for c in clientes.listar(self.con, "emp-a")], [self.da_a["id"]])
        self.assertEqual([c["id"] for c in clientes.listar(self.con, "emp-b")], [self.da_b["id"]])
        self.assertEqual(clientes.listar(self.con, "emp-inexistente"), [])

    def test_obter_de_outra_empresa_e_none(self):
        self.assertIsNone(clientes.obter(self.con, "emp-b", self.da_a["id"]))

    def test_atualizar_de_outra_empresa_nao_muda_nada(self):
        antes = self.linhas()
        self.assertIsNone(clientes.atualizar(self.con, "emp-b", self.da_a["id"],
                                             {"nome": "Invadido", "status": "inativo"}))
        self.assertEqual(self.linhas(), antes)

    def test_excluir_de_outra_empresa_nao_apaga(self):
        antes = self.linhas()
        self.assertFalse(clientes.excluir(self.con, "emp-b", self.da_a["id"]))
        self.assertEqual(self.linhas(), antes)
        self.assertIsNotNone(clientes.obter(self.con, "emp-a", self.da_a["id"]))

    def test_busca_nao_vaza_entre_empresas(self):
        self.assertEqual([c["nome"] for c in clientes.listar(self.con, "emp-a", "da b")], [])
        self.assertEqual([c["nome"] for c in clientes.listar(self.con, "emp-b", "ana")], ["Ana da B"])


class TestSqlPortavel(unittest.TestCase):
    def test_todas_as_queries_filtram_por_empresa(self):
        for nome in ("_SQL_LISTAR", "_SQL_BUSCAR", "_SQL_OBTER", "_SQL_ATUALIZAR", "_SQL_EXCLUIR"):
            with self.subTest(sql=nome):
                self.assertIn("WHERE empresa_id = ?", getattr(clientes, nome))

    def test_sem_construcoes_especificas_do_sqlite(self):
        sqls = [getattr(clientes, n) for n in dir(clientes) if n.startswith("_SQL_")]
        for sql in sqls:
            with self.subTest(sql=sql):
                for proibido in ("ILIKE", "COLLATE NOCASE", "GLOB", "AUTOINCREMENT", "||"):
                    self.assertNotIn(proibido, sql.upper())


if __name__ == "__main__":
    unittest.main()
