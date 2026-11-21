"""Testes das rotas GET, PUT e DELETE /api/clientes/{id}.

Cobrem autenticação (401), leitura, atualização parcial validada (atualizado_em),
exclusão (204) e isolamento multi-tenant: id inexistente e id de outra empresa devolvem
exatamente a mesma resposta 404, sem alterar nada no banco.
Chamam a aplicação WSGI diretamente (sem socket), com banco SQLite temporário.
Todos os dados são fictícios.
"""
import tempfile
import unittest
from pathlib import Path

from app.config import Config
from app.db import conectar, migrar
from app.servidor import criar_app
from tests import ficticio
from tests.test_web import chamar

# Valores fictícios gerados na execução, só para testes.
SEGREDO = ficticio.segredo()
SENHA = ficticio.senha()
DATA_ANTIGA = "2000-01-01T00:00:00Z"
ID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"


class TestApiClientesItem(unittest.TestCase):
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
        self.cliente_a = self.criar({"nome": "Ana Fictícia", "email": "ana@exemplo.test",
                                     "telefone": "(11) 0000-0000"}, self.token_a)
        self.cliente_b = self.criar({"nome": "Bruno da Empresa B"}, self.token_b)

    # ------------------------------------------------------------------ utilitários

    def nova_empresa(self, email, nome):
        r = chamar(self.app, "/api/empresas", "POST",
                   {"nome_empresa": nome, "email": email, "senha": SENHA})
        self.assertEqual(r["codigo"], 201, r["json"])
        r2 = chamar(self.app, "/api/login", "POST", {"email": email, "senha": SENHA})
        self.assertEqual(r2["codigo"], 200, r2["json"])
        return r["json"]["empresa_id"], r2["json"]["token"]

    @staticmethod
    def cab(token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    def criar(self, dados, token):
        r = chamar(self.app, "/api/clientes", "POST", dados, cabecalhos=self.cab(token))
        self.assertEqual(r["codigo"], 201, r["json"])
        return r["json"]

    def get(self, cliente_id, token):
        return chamar(self.app, f"/api/clientes/{cliente_id}", "GET", cabecalhos=self.cab(token))

    def put(self, cliente_id, dados, token):
        return chamar(self.app, f"/api/clientes/{cliente_id}", "PUT", dados,
                      cabecalhos=self.cab(token))

    def delete(self, cliente_id, token):
        return chamar(self.app, f"/api/clientes/{cliente_id}", "DELETE",
                      cabecalhos=self.cab(token))

    def foto_banco(self):
        """Estado completo da tabela clientes, para provar que nada mudou."""
        return [tuple(linha) for linha in self.con.execute(
            "SELECT * FROM clientes ORDER BY id").fetchall()]

    # ------------------------------------------------------------------ autenticação

    def test_sem_token_401(self):
        antes = self.foto_banco()
        cid = self.cliente_a["id"]
        for r in (self.get(cid, None), self.put(cid, {"nome": "X"}, None),
                  self.delete(cid, None)):
            self.assertEqual(r["codigo"], 401)
            self.assertIn("erro", r["json"])
        self.assertEqual(self.foto_banco(), antes)

    def test_token_invalido_e_apos_logout_401(self):
        cid = self.cliente_a["id"]
        antes = self.foto_banco()
        for token in ("lixo", self.token_a + "x"):
            self.assertEqual(self.get(cid, token)["codigo"], 401)
            self.assertEqual(self.put(cid, {"nome": "X"}, token)["codigo"], 401)
            self.assertEqual(self.delete(cid, token)["codigo"], 401)
        r = chamar(self.app, "/api/logout", "POST", cabecalhos=self.cab(self.token_a))
        self.assertEqual(r["codigo"], 204)
        self.assertEqual(self.get(cid, self.token_a)["codigo"], 401)
        self.assertEqual(self.put(cid, {"nome": "X"}, self.token_a)["codigo"], 401)
        self.assertEqual(self.delete(cid, self.token_a)["codigo"], 401)
        self.assertEqual(self.foto_banco(), antes)

    def test_metodo_nao_permitido_405(self):
        r = chamar(self.app, f"/api/clientes/{self.cliente_a['id']}", "POST", {"nome": "X"},
                   cabecalhos=self.cab(self.token_a))
        self.assertEqual(r["codigo"], 405)
        for metodo in ("GET", "PUT", "DELETE"):
            self.assertIn(metodo, r["headers"]["Allow"])

    # ------------------------------------------------------------------ GET

    def test_get_200(self):
        r = self.get(self.cliente_a["id"], self.token_a)
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(r["json"], self.cliente_a)

    # ------------------------------------------------------------------ PUT

    def test_put_parcial_200_e_atualizado_em(self):
        cid = self.cliente_a["id"]
        with self.con:
            self.con.execute("UPDATE clientes SET atualizado_em = ? WHERE id = ?",
                             (DATA_ANTIGA, cid))
        r = self.put(cid, {"status": "inativo", "observacoes": "nota fictícia"}, self.token_a)
        self.assertEqual(r["codigo"], 200, r["json"])
        c = r["json"]
        self.assertEqual(c["status"], "inativo")
        self.assertEqual(c["observacoes"], "nota fictícia")
        # Campos não enviados ficam como estavam.
        self.assertEqual(c["nome"], "Ana Fictícia")
        self.assertEqual(c["email"], "ana@exemplo.test")
        self.assertEqual(c["telefone"], "(11) 0000-0000")
        self.assertEqual(c["id"], cid)
        self.assertEqual(c["criado_em"], self.cliente_a["criado_em"])
        self.assertNotEqual(c["atualizado_em"], DATA_ANTIGA)
        self.assertEqual(self.get(cid, self.token_a)["json"], c)

    def test_put_limpa_campo_opcional(self):
        cid = self.cliente_a["id"]
        r = self.put(cid, {"email": None, "telefone": ""}, self.token_a)
        self.assertEqual(r["codigo"], 200, r["json"])
        self.assertIsNone(r["json"]["email"])
        self.assertIsNone(r["json"]["telefone"])

    def test_put_invalido_400_citando_campo_sem_alterar(self):
        cid = self.cliente_a["id"]
        antes = self.foto_banco()
        casos = [
            ({}, "nenhum campo"),
            ({"nome": ""}, "nome"),
            ({"nome": None}, "nome"),
            ({"nome": 123}, "nome"),
            ({"nome": "x" * 121}, "nome"),
            ({"email": "sem-arroba"}, "email"),
            ({"telefone": "abc"}, "telefone"),
            ({"observacoes": "x" * 2001}, "observacoes"),
            ({"status": "pendente"}, "status"),
            ({"empresa_id": self.empresa_b}, "empresa_id"),
            ({"id": "forjado"}, "id"),
        ]
        for dados, trecho in casos:
            with self.subTest(dados=str(dados)[:60]):
                r = self.put(cid, dados, self.token_a)
                self.assertEqual(r["codigo"], 400)
                self.assertIn(trecho, r["json"]["erro"].lower())
        self.assertEqual(self.foto_banco(), antes)

    def test_put_corpo_invalido_400(self):
        cid = self.cliente_a["id"]
        antes = self.foto_banco()
        for corpo in (b"{", b"[1, 2]", b"", b'"texto"'):
            with self.subTest(corpo=corpo):
                r = chamar(self.app, f"/api/clientes/{cid}", "PUT", corpo,
                           cabecalhos=self.cab(self.token_a))
                self.assertEqual(r["codigo"], 400)
                self.assertIn("erro", r["json"])
        self.assertEqual(self.foto_banco(), antes)

    def test_put_nao_move_cliente_de_empresa(self):
        cid = self.cliente_a["id"]
        r = self.put(cid, {"nome": "Ana Movida", "empresa_id": self.empresa_b}, self.token_a)
        self.assertEqual(r["codigo"], 400)
        linha = self.con.execute("SELECT empresa_id, nome FROM clientes WHERE id = ?",
                                 (cid,)).fetchone()
        self.assertEqual((linha[0], linha[1]), (self.empresa_a, "Ana Fictícia"))

    # ------------------------------------------------------------------ DELETE

    def test_delete_204_e_some(self):
        cid = self.cliente_a["id"]
        r = self.delete(cid, self.token_a)
        self.assertEqual(r["codigo"], 204)
        self.assertEqual(r["bruto"], b"")
        self.assertEqual(self.get(cid, self.token_a)["codigo"], 404)
        self.assertEqual(self.delete(cid, self.token_a)["codigo"], 404)
        self.assertEqual(self.put(cid, {"nome": "X"}, self.token_a)["codigo"], 404)
        n = self.con.execute("SELECT COUNT(*) FROM clientes WHERE id = ?", (cid,)).fetchone()[0]
        self.assertEqual(n, 0)
        # O cliente da outra empresa continua lá.
        self.assertEqual(self.get(self.cliente_b["id"], self.token_b)["codigo"], 200)

    # ------------------------------------------------------------------ isolamento / 404

    def test_outra_empresa_404_sem_alterar_nada(self):
        cid_b = self.cliente_b["id"]
        antes = self.foto_banco()
        r_get = self.get(cid_b, self.token_a)
        r_put = self.put(cid_b, {"nome": "Sequestrado"}, self.token_a)
        r_del = self.delete(cid_b, self.token_a)
        for r in (r_get, r_put, r_del):
            self.assertEqual(r["codigo"], 404)
            self.assertEqual(r["json"], {"erro": "cliente não encontrado"})
        self.assertEqual(self.foto_banco(), antes)
        self.assertEqual(self.get(cid_b, self.token_b)["json"], self.cliente_b)

    def test_inexistente_e_de_outra_empresa_respondem_igual(self):
        for metodo, corpo in (("GET", None), ("PUT", {"nome": "X"}), ("DELETE", None)):
            with self.subTest(metodo=metodo):
                outra = chamar(self.app, f"/api/clientes/{self.cliente_b['id']}", metodo,
                               corpo, cabecalhos=self.cab(self.token_a))
                inexistente = chamar(self.app, f"/api/clientes/{ID_INEXISTENTE}", metodo,
                                     corpo, cabecalhos=self.cab(self.token_a))
                self.assertEqual(outra["codigo"], 404)
                self.assertEqual(outra["status"], inexistente["status"])
                self.assertEqual(outra["bruto"], inexistente["bruto"])
                self.assertEqual(outra["headers"], inexistente["headers"])

    def test_id_estranho_404(self):
        for cid in ("x" * 65, "1' OR '1'='1", "%25"):
            with self.subTest(cid=cid[:20]):
                self.assertEqual(self.get(cid, self.token_a)["codigo"], 404)
                self.assertEqual(self.delete(cid, self.token_a)["codigo"], 404)
        self.assertEqual(len(self.foto_banco()), 2)


if __name__ == "__main__":
    unittest.main()
