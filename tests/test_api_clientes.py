"""Testes das rotas GET e POST /api/clientes (autenticação, busca, validação e isolamento).

Chamam a aplicação WSGI diretamente (sem socket), com banco SQLite temporário.
Todos os dados são fictícios.
"""
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from app.config import Config
from app.db import conectar, migrar
from app.servidor import criar_app
from tests import ficticio
from tests.test_web import chamar

# Valores fictícios gerados na execução, só para testes.
SEGREDO = ficticio.segredo()
SENHA = ficticio.senha()


class TestApiClientesColecao(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "t.db")
        self.con = conectar(self.db)
        self.addCleanup(self.con.close)
        migrar(self.con)
        config = Config(db=self.db, host="127.0.0.1", porta=8000, segredo=SEGREDO, token_ttl=60)
        self.app = criar_app(config)
        self.empresa_a, self.token_a = self.nova_empresa("a@exemplo.test", "Empresa A Fictícia")
        self.empresa_b, self.token_b = self.nova_empresa("b@exemplo.test", "Empresa B Fictícia")

    def nova_empresa(self, email, nome):
        r = chamar(self.app, "/api/empresas", "POST",
                   {"nome_empresa": nome, "email": email, "senha": SENHA})
        self.assertEqual(r["codigo"], 201, r["json"])
        r2 = chamar(self.app, "/api/login", "POST", {"email": email, "senha": SENHA})
        self.assertEqual(r2["codigo"], 200, r2["json"])
        return r["json"]["empresa_id"], r2["json"]["token"]

    def get(self, token=None, busca=None):
        cab = {"Authorization": f"Bearer {token}"} if token else {}
        query = urlencode({"busca": busca}) if busca is not None else ""
        return chamar(self.app, "/api/clientes", "GET", cabecalhos=cab, query=query)

    def post(self, dados, token=None):
        cab = {"Authorization": f"Bearer {token}"} if token else {}
        return chamar(self.app, "/api/clientes", "POST", dados, cabecalhos=cab)

    def contar(self):
        return self.con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

    # ------------------------------------------------------------------ autenticação

    def test_sem_token_401(self):
        for r in (self.get(), self.post({"nome": "Ana Fictícia"})):
            self.assertEqual(r["codigo"], 401)
            self.assertIn("erro", r["json"])
        self.assertEqual(self.contar(), 0)

    def test_token_invalido_401(self):
        for token in ("lixo", self.token_a + "x"):
            self.assertEqual(self.get(token)["codigo"], 401)
            self.assertEqual(self.post({"nome": "Ana Fictícia"}, token)["codigo"], 401)
        self.assertEqual(self.contar(), 0)

    def test_token_apos_logout_401(self):
        r = chamar(self.app, "/api/logout", "POST",
                   cabecalhos={"Authorization": f"Bearer {self.token_a}"})
        self.assertEqual(r["codigo"], 204)
        self.assertEqual(self.get(self.token_a)["codigo"], 401)
        self.assertEqual(self.post({"nome": "Ana Fictícia"}, self.token_a)["codigo"], 401)

    def test_metodo_nao_permitido_405(self):
        r = chamar(self.app, "/api/clientes", "DELETE",
                   cabecalhos={"Authorization": f"Bearer {self.token_a}"})
        self.assertEqual(r["codigo"], 405)
        self.assertIn("GET", r["headers"]["Allow"])
        self.assertIn("POST", r["headers"]["Allow"])

    # ------------------------------------------------------------------ POST

    def test_criar_201_com_padroes(self):
        r = self.post({"nome": "  Ana Fictícia  "}, self.token_a)
        self.assertEqual(r["codigo"], 201, r["json"])
        c = r["json"]
        self.assertEqual(set(c), {"id", "nome", "email", "telefone", "observacoes", "status",
                                  "criado_em", "atualizado_em"})
        self.assertEqual(c["nome"], "Ana Fictícia")
        self.assertEqual(c["status"], "ativo")
        self.assertIsNone(c["email"])
        self.assertTrue(c["id"] and c["criado_em"] and c["atualizado_em"])
        self.assertEqual(r["headers"]["Location"], f"/api/clientes/{c['id']}")
        linha = self.con.execute("SELECT empresa_id FROM clientes WHERE id = ?",
                                 (c["id"],)).fetchone()
        self.assertEqual(linha[0], self.empresa_a)

    def test_criar_completo(self):
        dados = {"nome": "Bruno Fictício", "email": "bruno@exemplo.test",
                 "telefone": "+55 (11) 0000-0000", "observacoes": "linha 1\nlinha 2",
                 "status": "inativo"}
        r = self.post(dados, self.token_a)
        self.assertEqual(r["codigo"], 201, r["json"])
        for campo, valor in dados.items():
            self.assertEqual(r["json"][campo], valor)

    def test_empresa_id_do_corpo_nunca_e_usado(self):
        r = self.post({"nome": "Intruso Fictício", "empresa_id": self.empresa_b}, self.token_a)
        self.assertEqual(r["codigo"], 400)
        self.assertIn("empresa_id", r["json"]["erro"])
        r = self.post({"nome": "Intruso Fictício", "id": "forjado"}, self.token_a)
        self.assertEqual(r["codigo"], 400)
        self.assertEqual(self.contar(), 0)
        self.assertEqual(self.get(self.token_b)["json"], [])

    def test_entradas_invalidas_400_citando_campo(self):
        casos = [
            ({}, "nome"),
            ({"nome": ""}, "nome"),
            ({"nome": 123}, "nome"),
            ({"nome": "x" * 121}, "nome"),
            ({"nome": "Ana", "email": "sem-arroba"}, "email"),
            ({"nome": "Ana", "telefone": "abc"}, "telefone"),
            ({"nome": "Ana", "observacoes": "x" * 2001}, "observacoes"),
            ({"nome": "Ana", "status": "pendente"}, "status"),
            ({"nome": "Ana", "outro": 1}, "outro"),
        ]
        for dados, campo in casos:
            with self.subTest(dados=str(dados)[:60]):
                r = self.post(dados, self.token_a)
                self.assertEqual(r["codigo"], 400)
                self.assertIn(campo, r["json"]["erro"].lower())
        self.assertEqual(self.contar(), 0)

    def test_corpo_invalido_400(self):
        cab = {"Authorization": f"Bearer {self.token_a}"}
        for corpo in (b"{", b"[1, 2]", b"", b'"texto"'):
            with self.subTest(corpo=corpo):
                r = chamar(self.app, "/api/clientes", "POST", corpo, cabecalhos=cab)
                self.assertEqual(r["codigo"], 400)
                self.assertIn("erro", r["json"])
        self.assertEqual(self.contar(), 0)

    # ------------------------------------------------------------------ GET

    def test_lista_vazia(self):
        r = self.get(self.token_a)
        self.assertEqual((r["codigo"], r["json"]), (200, []))

    def test_lista_so_da_propria_empresa_ordenada(self):
        for nome in ("Carla Fictícia", "ana Fictícia", "Bruno Fictício"):
            self.assertEqual(self.post({"nome": nome}, self.token_a)["codigo"], 201)
        self.assertEqual(self.post({"nome": "Ana da Empresa B"}, self.token_b)["codigo"], 201)
        r = self.get(self.token_a)
        self.assertEqual(r["codigo"], 200)
        self.assertEqual([c["nome"] for c in r["json"]],
                         ["ana Fictícia", "Bruno Fictício", "Carla Fictícia"])
        r = self.get(self.token_b)
        self.assertEqual([c["nome"] for c in r["json"]], ["Ana da Empresa B"])

    def test_busca_sem_diferenciar_maiusculas_e_isolada(self):
        for nome in ("Ana Fictícia", "MARIANA Fictícia", "Bruno Fictício"):
            self.post({"nome": nome}, self.token_a)
        self.post({"nome": "Ana da Empresa B"}, self.token_b)
        r = self.get(self.token_a, busca="ana")
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(sorted(c["nome"] for c in r["json"]),
                         ["Ana Fictícia", "MARIANA Fictícia"])
        r = self.get(self.token_a, busca="ANA")
        self.assertEqual(len(r["json"]), 2)
        self.assertEqual(self.get(self.token_a, busca="Empresa B")["json"], [])
        self.assertEqual(len(self.get(self.token_a, busca="")["json"]), 3)
        self.assertEqual(len(self.get(self.token_a, busca="   ")["json"]), 3)

    def test_busca_curingas_literais(self):
        self.post({"nome": "Ana Fictícia"}, self.token_a)
        self.assertEqual(self.get(self.token_a, busca="%")["json"], [])
        self.assertEqual(self.get(self.token_a, busca="_")["json"], [])

    def test_busca_invalida_400(self):
        r = self.get(self.token_a, busca="x" * 201)
        self.assertEqual(r["codigo"], 400)
        self.assertIn("busca", r["json"]["erro"])

    def test_criado_aparece_na_lista(self):
        criado = self.post({"nome": "Ana Fictícia"}, self.token_a)["json"]
        self.assertEqual(self.get(self.token_a)["json"], [criado])


if __name__ == "__main__":
    unittest.main()
