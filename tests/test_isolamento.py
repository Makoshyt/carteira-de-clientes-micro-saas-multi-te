"""Testes de isolamento multi-tenant entre duas empresas (A e B) pela API.

As duas empresas têm clientes com os MESMOS nomes. Os testes verificam que:
- a listagem e a busca de B não mostram nada de A (e vice-versa);
- GET, PUT e DELETE de B sobre um id de A devolvem 404 idêntico ao de um id
  inexistente e deixam o registro de A intacto no banco;
- ``empresa_id`` enviado no corpo do POST/PUT, na query ou em cabeçalhos nunca muda
  o tenant (o corpo é recusado com 400; query e cabeçalhos são ignorados);
- um token de A, mesmo com assinatura válida, só acessa dados de A; um token com
  assinatura válida para uma sessão inexistente, ou assinado com outro segredo, recebe 401.

Chamam a aplicação WSGI diretamente (sem socket), com banco SQLite temporário.
Todos os dados são fictícios.
"""
import secrets
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from app.config import Config
from app.db import conectar, migrar
from app.seguranca import gerar_token, sessao_do_token
from app.servidor import criar_app
from tests import ficticio
from tests.test_web import chamar

# Valores fictícios gerados na execução, só para testes.
SEGREDO = ficticio.segredo()
OUTRO_SEGREDO = ficticio.segredo()
SENHA = ficticio.senha()
ID_FICTICIO = "00000000-0000-4000-8000-000000000000"
NOMES = ("Ana Fictícia", "Bruno Fictício", "Mariana Fictícia")
NAO_ENCONTRADO = {"erro": "cliente não encontrado"}


class TestIsolamentoEntreEmpresas(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "t.db")
        self.con = conectar(self.db)
        self.addCleanup(self.con.close)
        migrar(self.con)
        config = Config(db=self.db, host="127.0.0.1", porta=8000, segredo=SEGREDO, token_ttl=60)
        self.app = criar_app(config)

        self.token_a = self.nova_empresa("a@exemplo.test", "Empresa A Fictícia")
        self.token_b = self.nova_empresa("b@exemplo.test", "Empresa B Fictícia")
        self.empresa_a = self.me(self.token_a)["empresa_id"]
        self.empresa_b = self.me(self.token_b)["empresa_id"]
        self.assertNotEqual(self.empresa_a, self.empresa_b)

        # Mesmos nomes nas duas empresas, com e-mails diferentes para distinguir.
        self.ids_a = {n: self.criar({"nome": n, "email": "a@cliente.test"}, self.token_a)["id"]
                      for n in NOMES}
        self.ids_b = {n: self.criar({"nome": n, "email": "b@cliente.test"}, self.token_b)["id"]
                      for n in NOMES}
        self.id_a = self.ids_a["Ana Fictícia"]

    # ------------------------------------------------------------------ utilitários

    def nova_empresa(self, email, nome):
        r = chamar(self.app, "/api/empresas", "POST",
                   {"nome_empresa": nome, "email": email, "senha": SENHA})
        self.assertEqual(r["codigo"], 201, r["json"])
        r = chamar(self.app, "/api/login", "POST", {"email": email, "senha": SENHA})
        self.assertEqual(r["codigo"], 200, r["json"])
        return r["json"]["token"]

    @staticmethod
    def cab(token, **extras):
        cab = {"Authorization": f"Bearer {token}"}
        cab.update(extras)
        return cab

    def me(self, token):
        r = chamar(self.app, "/api/me", "GET", cabecalhos=self.cab(token))
        self.assertEqual(r["codigo"], 200, r["json"])
        return r["json"]

    def criar(self, dados, token):
        r = chamar(self.app, "/api/clientes", "POST", dados, cabecalhos=self.cab(token))
        self.assertEqual(r["codigo"], 201, r["json"])
        return r["json"]

    def listar(self, token, **query):
        r = chamar(self.app, "/api/clientes", "GET", cabecalhos=self.cab(token),
                   query=urlencode(query))
        self.assertEqual(r["codigo"], 200, r["json"])
        return r["json"]

    def linha(self, cliente_id):
        return self.con.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()

    def tabela(self):
        return self.con.execute("SELECT * FROM clientes ORDER BY id").fetchall()

    def ids_da_empresa(self, empresa_id):
        return {r[0] for r in self.con.execute(
            "SELECT id FROM clientes WHERE empresa_id = ?", (empresa_id,))}

    # ------------------------------------------------------------------ listagem e busca

    def test_listagem_de_b_nao_mostra_nada_de_a(self):
        lista_b = self.listar(self.token_b)
        self.assertEqual({c["id"] for c in lista_b}, set(self.ids_b.values()))
        self.assertTrue(all(c["email"] == "b@cliente.test" for c in lista_b))
        self.assertTrue(set(self.ids_a.values()).isdisjoint(c["id"] for c in lista_b))

        lista_a = self.listar(self.token_a)
        self.assertEqual({c["id"] for c in lista_a}, set(self.ids_a.values()))
        self.assertTrue(all(c["email"] == "a@cliente.test" for c in lista_a))
        # A resposta não expõe o empresa_id.
        self.assertTrue(all("empresa_id" not in c for c in lista_a + lista_b))

    def test_busca_de_b_nao_mostra_nada_de_a(self):
        for termo in ("ana", "ANA", "Fictíci", "bruno"):
            with self.subTest(termo=termo):
                achados = self.listar(self.token_b, busca=termo)
                self.assertTrue(achados)
                self.assertTrue({c["id"] for c in achados} <= set(self.ids_b.values()))
        # "ana" casa "Ana" e "Mariana" só da própria empresa.
        self.assertEqual(sorted(c["id"] for c in self.listar(self.token_b, busca="ana")),
                         sorted((self.ids_b["Ana Fictícia"], self.ids_b["Mariana Fictícia"])))

    def test_busca_por_nome_exclusivo_de_a_nao_aparece_para_b(self):
        exclusivo = self.criar({"nome": "Zuleica Exclusiva de A"}, self.token_a)["id"]
        self.assertEqual(self.listar(self.token_b, busca="zuleica"), [])
        self.assertEqual([c["id"] for c in self.listar(self.token_a, busca="zuleica")],
                         [exclusivo])

    def test_empresa_vazia_nao_ve_nada(self):
        token_c = self.nova_empresa("c@exemplo.test", "Empresa C Fictícia")
        self.assertEqual(self.listar(token_c), [])
        self.assertEqual(self.listar(token_c, busca="ana"), [])

    # ------------------------------------------------------------------ GET/PUT/DELETE cruzados

    def test_get_put_delete_de_b_sobre_id_de_a_404_sem_alterar(self):
        antes = self.tabela()
        url = f"/api/clientes/{self.id_a}"
        casos = [
            ("GET", None),
            ("PUT", {"nome": "Sequestrado por B"}),
            ("PUT", {"status": "inativo"}),
            ("DELETE", None),
        ]
        for metodo, corpo in casos:
            with self.subTest(metodo=metodo, corpo=corpo):
                r = chamar(self.app, url, metodo, corpo, cabecalhos=self.cab(self.token_b))
                self.assertEqual(r["codigo"], 404)
                self.assertEqual(r["json"], NAO_ENCONTRADO)
                # Mesma resposta de um id que não existe: não revela a existência.
                r2 = chamar(self.app, f"/api/clientes/{ID_FICTICIO}", metodo, corpo,
                            cabecalhos=self.cab(self.token_b))
                self.assertEqual((r2["codigo"], r2["json"]), (r["codigo"], r["json"]))
        self.assertEqual(self.tabela(), antes)

        # A continua vendo o próprio registro, sem nenhuma mudança.
        r = chamar(self.app, url, "GET", cabecalhos=self.cab(self.token_a))
        self.assertEqual(r["codigo"], 200)
        self.assertEqual((r["json"]["nome"], r["json"]["status"], r["json"]["email"]),
                         ("Ana Fictícia", "ativo", "a@cliente.test"))

    def test_b_nao_apaga_nenhum_cliente_de_a(self):
        for cliente_id in self.ids_a.values():
            r = chamar(self.app, f"/api/clientes/{cliente_id}", "DELETE",
                       cabecalhos=self.cab(self.token_b))
            self.assertEqual(r["codigo"], 404)
        self.assertEqual(self.ids_da_empresa(self.empresa_a), set(self.ids_a.values()))
        self.assertEqual(self.ids_da_empresa(self.empresa_b), set(self.ids_b.values()))

    def test_exclusao_em_b_nao_afeta_homonimo_de_a(self):
        id_b = self.ids_b["Ana Fictícia"]
        r = chamar(self.app, f"/api/clientes/{id_b}", "DELETE", cabecalhos=self.cab(self.token_b))
        self.assertEqual(r["codigo"], 204)
        self.assertIsNone(self.linha(id_b))
        self.assertIsNotNone(self.linha(self.id_a))
        self.assertEqual(self.ids_da_empresa(self.empresa_a), set(self.ids_a.values()))

    def test_atualizacao_em_b_nao_afeta_homonimo_de_a(self):
        antes_a = self.linha(self.id_a)
        id_b = self.ids_b["Ana Fictícia"]
        r = chamar(self.app, f"/api/clientes/{id_b}", "PUT", {"status": "inativo"},
                   cabecalhos=self.cab(self.token_b))
        self.assertEqual(r["codigo"], 200, r["json"])
        self.assertEqual(r["json"]["status"], "inativo")
        self.assertEqual(self.linha(self.id_a), antes_a)

    # ------------------------------------------------------------------ empresa_id do cliente

    def test_post_com_empresa_id_no_corpo_nao_muda_o_tenant(self):
        antes = self.tabela()
        for valor in (self.empresa_a, self.empresa_b, "", None, ID_FICTICIO):
            with self.subTest(empresa_id=valor):
                r = chamar(self.app, "/api/clientes", "POST",
                           {"nome": "Infiltrado", "empresa_id": valor},
                           cabecalhos=self.cab(self.token_b))
                if r["codigo"] == 201:
                    # Se fosse aceito, teria de ficar na empresa da sessão (B).
                    linha = self.con.execute("SELECT empresa_id FROM clientes WHERE id = ?",
                                             (r["json"]["id"],)).fetchone()
                    self.assertEqual(linha[0], self.empresa_b)
                else:
                    self.assertEqual(r["codigo"], 400, r["json"])
                    self.assertIn("empresa_id", r["json"]["erro"])
        self.assertEqual(self.ids_da_empresa(self.empresa_a), set(self.ids_a.values()))
        self.assertEqual(self.tabela(), antes)  # comportamento atual: recusado com 400

    def test_put_com_empresa_id_no_corpo_nao_move_o_cliente(self):
        antes = self.tabela()
        id_b = self.ids_b["Ana Fictícia"]
        # B tenta mover o próprio cliente para A.
        r = chamar(self.app, f"/api/clientes/{id_b}", "PUT",
                   {"nome": "Movido", "empresa_id": self.empresa_a},
                   cabecalhos=self.cab(self.token_b))
        self.assertEqual(r["codigo"], 400, r["json"])
        self.assertIn("empresa_id", r["json"]["erro"])
        # B tenta "puxar" um cliente de A dizendo que ele é de B.
        r = chamar(self.app, f"/api/clientes/{self.id_a}", "PUT",
                   {"nome": "Puxado", "empresa_id": self.empresa_b},
                   cabecalhos=self.cab(self.token_b))
        self.assertIn(r["codigo"], (400, 404), r["json"])
        self.assertEqual(self.tabela(), antes)
        self.assertEqual(self.ids_da_empresa(self.empresa_a), set(self.ids_a.values()))
        self.assertEqual(self.ids_da_empresa(self.empresa_b), set(self.ids_b.values()))

    def test_empresa_id_na_query_ou_cabecalho_e_ignorado(self):
        lista = self.listar(self.token_b, empresa_id=self.empresa_a)
        self.assertEqual({c["id"] for c in lista}, set(self.ids_b.values()))
        lista = self.listar(self.token_b, busca="ana", empresa_id=self.empresa_a)
        self.assertTrue({c["id"] for c in lista} <= set(self.ids_b.values()))

        extras = {"X-Empresa-Id": self.empresa_a, "X-Tenant-Id": self.empresa_a}
        r = chamar(self.app, "/api/clientes", "GET", cabecalhos=self.cab(self.token_b, **extras))
        self.assertEqual({c["id"] for c in r["json"]}, set(self.ids_b.values()))
        r = chamar(self.app, f"/api/clientes/{self.id_a}", "GET",
                   cabecalhos=self.cab(self.token_b, **extras),
                   query=urlencode({"empresa_id": self.empresa_a}))
        self.assertEqual((r["codigo"], r["json"]), (404, NAO_ENCONTRADO))

        r = chamar(self.app, "/api/clientes", "POST", {"nome": "Via Cabeçalho"},
                   cabecalhos=self.cab(self.token_b, **extras),
                   query=urlencode({"empresa_id": self.empresa_a}))
        self.assertEqual(r["codigo"], 201, r["json"])
        dono = self.con.execute("SELECT empresa_id FROM clientes WHERE id = ?",
                                (r["json"]["id"],)).fetchone()[0]
        self.assertEqual(dono, self.empresa_b)

    # ------------------------------------------------------------------ tokens

    def test_token_de_a_com_assinatura_valida_so_acessa_a(self):
        sessao_a = sessao_do_token(SEGREDO, self.token_a)
        self.assertIsNotNone(sessao_a)
        # Token remontado com a assinatura correta é o mesmo token de A.
        token = gerar_token(SEGREDO, sessao_a)
        self.assertEqual(token, self.token_a)
        self.assertEqual(self.me(token)["empresa_id"], self.empresa_a)

        self.assertEqual({c["id"] for c in self.listar(token)}, set(self.ids_a.values()))
        for cliente_id in self.ids_b.values():
            for metodo, corpo in (("GET", None), ("PUT", {"nome": "X"}), ("DELETE", None)):
                with self.subTest(cliente_id=cliente_id, metodo=metodo):
                    r = chamar(self.app, f"/api/clientes/{cliente_id}", metodo, corpo,
                               cabecalhos=self.cab(token))
                    self.assertEqual((r["codigo"], r["json"]), (404, NAO_ENCONTRADO))
        self.assertEqual(self.ids_da_empresa(self.empresa_b), set(self.ids_b.values()))

    def test_token_com_assinatura_valida_de_sessao_inexistente_401(self):
        forjado = gerar_token(SEGREDO, secrets.token_urlsafe(32))
        antes = self.tabela()
        for metodo, caminho, corpo in (("GET", "/api/clientes", None),
                                       ("POST", "/api/clientes", {"nome": "Intruso"}),
                                       ("GET", f"/api/clientes/{self.id_a}", None),
                                       ("PUT", f"/api/clientes/{self.id_a}", {"nome": "X"}),
                                       ("DELETE", f"/api/clientes/{self.id_a}", None)):
            with self.subTest(metodo=metodo, caminho=caminho):
                r = chamar(self.app, caminho, metodo, corpo, cabecalhos=self.cab(forjado))
                self.assertEqual(r["codigo"], 401)
                self.assertEqual(set(r["json"]), {"erro"})
        self.assertEqual(self.tabela(), antes)

    def test_sessao_de_a_assinada_com_outro_segredo_401(self):
        sessao_a = sessao_do_token(SEGREDO, self.token_a)
        forjado = gerar_token(OUTRO_SEGREDO, sessao_a)
        self.assertNotEqual(forjado, self.token_a)
        r = chamar(self.app, "/api/clientes", "GET", cabecalhos=self.cab(forjado))
        self.assertEqual(r["codigo"], 401)
        # Assinatura de B colada no id de sessão de A também não vale.
        assinatura_b = self.token_b.split(".")[1]
        misturado = f"{sessao_a}.{assinatura_b}"
        r = chamar(self.app, "/api/clientes", "GET", cabecalhos=self.cab(misturado))
        self.assertEqual(r["codigo"], 401)

    def test_logout_de_a_nao_afeta_b(self):
        r = chamar(self.app, "/api/logout", "POST", cabecalhos=self.cab(self.token_a))
        self.assertEqual(r["codigo"], 204)
        r = chamar(self.app, "/api/clientes", "GET", cabecalhos=self.cab(self.token_a))
        self.assertEqual(r["codigo"], 401)
        self.assertEqual({c["id"] for c in self.listar(self.token_b)}, set(self.ids_b.values()))
        self.assertEqual(self.ids_da_empresa(self.empresa_a), set(self.ids_a.values()))


if __name__ == "__main__":
    unittest.main()
