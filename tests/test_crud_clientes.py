"""Testes de ponta a ponta do CRUD e da busca de clientes pela API.

Cobrem: criar cliente válido (201); nome ausente ou vazio, e-mail inválido, status
inválido, campo desconhecido e JSON malformado (400); corpo grande demais (413);
listar; buscar por parte do nome sem diferenciar maiúsculas de minúsculas, inclusive
com ``%`` e ``_`` no termo (tratados como literais); obter; atualizar parcialmente;
excluir e depois receber 404; e qualquer rota de clientes sem token (401).

Chamam a aplicação WSGI diretamente (sem socket), com banco SQLite temporário.
Todos os dados são fictícios.
"""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from app.config import Config
from app.db import conectar, migrar
from app.servidor import criar_app
from app.web import LIMITE_CORPO
from tests import ficticio
from tests.test_web import chamar

# Valores fictícios gerados na execução, só para testes.
SEGREDO = ficticio.segredo()
SENHA = ficticio.senha()
ID_FICTICIO = "00000000-0000-4000-8000-000000000000"


class TestCrudClientes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "t.db")
        self.con = conectar(self.db)
        self.addCleanup(self.con.close)
        migrar(self.con)
        config = Config(db=self.db, host="127.0.0.1", porta=8000, segredo=SEGREDO, token_ttl=60)
        self.app = criar_app(config)
        self.token = self.nova_empresa("crud@exemplo.test", "Empresa CRUD Fictícia")
        self.token_outra = self.nova_empresa("outra@exemplo.test", "Outra Empresa Fictícia")

    # ------------------------------------------------------------------ utilitários

    def nova_empresa(self, email, nome):
        r = chamar(self.app, "/api/empresas", "POST",
                   {"nome_empresa": nome, "email": email, "senha": SENHA})
        self.assertEqual(r["codigo"], 201, r["json"])
        r = chamar(self.app, "/api/login", "POST", {"email": email, "senha": SENHA})
        self.assertEqual(r["codigo"], 200, r["json"])
        return r["json"]["token"]

    @staticmethod
    def cab(token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    def criar(self, dados, token=None):
        return chamar(self.app, "/api/clientes", "POST", dados,
                      cabecalhos=self.cab(token or self.token))

    def listar(self, busca=None, token=None):
        query = urlencode({"busca": busca}) if busca is not None else ""
        return chamar(self.app, "/api/clientes", "GET",
                      cabecalhos=self.cab(token or self.token), query=query)

    def nomes(self, busca=None):
        r = self.listar(busca)
        self.assertEqual(r["codigo"], 200, r["json"])
        return sorted(c["nome"] for c in r["json"])

    def contar(self):
        return self.con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

    # ------------------------------------------------------------------ criar

    def test_criar_cliente_valido_201(self):
        dados = {"nome": "Ana Fictícia", "email": "ana@exemplo.test",
                 "telefone": "(11) 0000-0000", "observacoes": "cliente fictícia"}
        r = self.criar(dados)
        self.assertEqual(r["codigo"], 201, r["json"])
        for campo, valor in dados.items():
            self.assertEqual(r["json"][campo], valor)
        self.assertEqual(r["json"]["status"], "ativo")
        self.assertTrue(r["json"]["id"])
        self.assertEqual(self.contar(), 1)

    def test_criar_invalido_400_citando_campo(self):
        casos = [
            ("nome ausente", {"email": "ana@exemplo.test"}, "nome"),
            ("nome vazio", {"nome": ""}, "nome"),
            ("nome só espaços", {"nome": "   "}, "nome"),
            ("e-mail inválido", {"nome": "Ana", "email": "ana-sem-arroba"}, "email"),
            ("e-mail sem domínio", {"nome": "Ana", "email": "ana@"}, "email"),
            ("status inválido", {"nome": "Ana", "status": "suspenso"}, "status"),
            ("status de outro tipo", {"nome": "Ana", "status": True}, "status"),
            ("campo desconhecido", {"nome": "Ana", "apelido": "Aninha"}, "apelido"),
        ]
        for descricao, dados, campo in casos:
            with self.subTest(descricao):
                r = self.criar(dados)
                self.assertEqual(r["codigo"], 400, r["json"])
                self.assertEqual(set(r["json"]), {"erro"})
                self.assertIn(campo, r["json"]["erro"].lower())
        self.assertEqual(self.contar(), 0)

    def test_json_malformado_400(self):
        for corpo in (b'{"nome": "Ana"', b"{nome: 'Ana'}", b'{"nome": "Ana",}', b"\xff\xfe"):
            with self.subTest(corpo=corpo):
                r = self.criar(corpo)
                self.assertEqual(r["codigo"], 400)
                self.assertEqual(set(r["json"]), {"erro"})
        self.assertEqual(self.contar(), 0)

    def test_corpo_grande_demais_413(self):
        enorme = json.dumps({"nome": "Ana", "observacoes": "x" * LIMITE_CORPO}).encode("utf-8")
        self.assertGreater(len(enorme), LIMITE_CORPO)
        r = self.criar(enorme)
        self.assertEqual(r["codigo"], 413)
        self.assertEqual(set(r["json"]), {"erro"})
        self.assertEqual(self.contar(), 0)

        cid = self.criar({"nome": "Ana Fictícia"})["json"]["id"]
        r = chamar(self.app, f"/api/clientes/{cid}", "PUT", enorme,
                   cabecalhos=self.cab(self.token))
        self.assertEqual(r["codigo"], 413)
        self.assertEqual(chamar(self.app, f"/api/clientes/{cid}", "GET",
                                cabecalhos=self.cab(self.token))["json"]["observacoes"], None)

    # ------------------------------------------------------------------ listar e buscar

    def test_listar(self):
        self.assertEqual(self.listar()["json"], [])
        for nome in ("Carla Fictícia", "Ana Fictícia", "Bruno Fictício"):
            self.assertEqual(self.criar({"nome": nome})["codigo"], 201)
        self.criar({"nome": "Diego da Outra"}, self.token_outra)
        r = self.listar()
        self.assertEqual(r["codigo"], 200)
        self.assertEqual([c["nome"] for c in r["json"]],
                         ["Ana Fictícia", "Bruno Fictício", "Carla Fictícia"])

    def test_buscar_parte_do_nome_sem_diferenciar_maiusculas(self):
        for nome in ("Ana Fictícia", "MARIANA Fictícia", "Juliana Fictícia", "Bruno Fictício"):
            self.criar({"nome": nome})
        self.criar({"nome": "Ana da Outra Empresa"}, self.token_outra)
        esperado = ["Ana Fictícia", "Juliana Fictícia", "MARIANA Fictícia"]
        for termo in ("ana", "ANA", "aNa"):
            with self.subTest(termo=termo):
                self.assertEqual(self.nomes(termo), esperado)
        self.assertEqual(self.nomes("brun"), ["Bruno Fictício"])
        self.assertEqual(self.nomes("inexistente"), [])

    def test_buscar_com_porcento_e_sublinhado_literais(self):
        for nome in ("Loja 100% Fictícia", "Loja 1000 Fictícia",
                     "Ana_Silva Fictícia", "AnaXSilva Fictícia", "Contato\\Barra"):
            self.assertEqual(self.criar({"nome": nome})["codigo"], 201)
        self.assertEqual(self.nomes("%"), ["Loja 100% Fictícia"])
        self.assertEqual(self.nomes("100%"), ["Loja 100% Fictícia"])
        self.assertEqual(self.nomes("_"), ["Ana_Silva Fictícia"])
        self.assertEqual(self.nomes("ANA_s"), ["Ana_Silva Fictícia"])
        self.assertEqual(self.nomes("a%s"), [])
        self.assertEqual(self.nomes("\\"), ["Contato\\Barra"])

    # ------------------------------------------------------------------ ciclo completo

    def test_obter_atualizar_parcialmente_excluir_e_404(self):
        criado = self.criar({"nome": "Ana Fictícia", "email": "ana@exemplo.test",
                             "telefone": "(11) 0000-0000"})["json"]
        url = f"/api/clientes/{criado['id']}"
        cab = self.cab(self.token)

        r = chamar(self.app, url, "GET", cabecalhos=cab)
        self.assertEqual((r["codigo"], r["json"]), (200, criado))

        r = chamar(self.app, url, "PUT", {"status": "inativo"}, cabecalhos=cab)
        self.assertEqual(r["codigo"], 200, r["json"])
        self.assertEqual(r["json"]["status"], "inativo")
        for campo in ("nome", "email", "telefone", "observacoes", "id", "criado_em"):
            self.assertEqual(r["json"][campo], criado[campo])
        self.assertEqual(chamar(self.app, url, "GET", cabecalhos=cab)["json"], r["json"])

        r = chamar(self.app, url, "PUT", {"email": "sem-arroba"}, cabecalhos=cab)
        self.assertEqual(r["codigo"], 400)
        self.assertIn("email", r["json"]["erro"].lower())

        r = chamar(self.app, url, "DELETE", cabecalhos=cab)
        self.assertEqual((r["codigo"], r["bruto"]), (204, b""))
        for metodo, corpo in (("GET", None), ("PUT", {"nome": "X"}), ("DELETE", None)):
            with self.subTest(metodo=metodo):
                r = chamar(self.app, url, metodo, corpo, cabecalhos=cab)
                self.assertEqual(r["codigo"], 404)
                self.assertEqual(r["json"], {"erro": "cliente não encontrado"})
        self.assertEqual(self.listar()["json"], [])
        self.assertEqual(self.contar(), 0)

    # ------------------------------------------------------------------ sem token

    def test_qualquer_rota_sem_token_401(self):
        cid = self.criar({"nome": "Ana Fictícia"})["json"]["id"]
        antes = self.con.execute("SELECT * FROM clientes").fetchall()
        rotas = [
            ("GET", "/api/clientes", None, ""),
            ("GET", "/api/clientes", None, "busca=ana"),
            ("POST", "/api/clientes", {"nome": "Intruso"}, ""),
            ("GET", f"/api/clientes/{cid}", None, ""),
            ("PUT", f"/api/clientes/{cid}", {"nome": "Intruso"}, ""),
            ("DELETE", f"/api/clientes/{cid}", None, ""),
            ("GET", f"/api/clientes/{ID_FICTICIO}", None, ""),
        ]
        cabecalhos = [{}, {"Authorization": ""}, {"Authorization": "Bearer"},
                      {"Authorization": "Basic abc"}, {"Authorization": "Bearer lixo"}]
        for metodo, caminho, corpo, query in rotas:
            for cab in cabecalhos:
                with self.subTest(metodo=metodo, caminho=caminho, cab=cab):
                    r = chamar(self.app, caminho, metodo, corpo, cabecalhos=cab, query=query)
                    self.assertEqual(r["codigo"], 401)
                    self.assertEqual(set(r["json"]), {"erro"})
        self.assertEqual(self.con.execute("SELECT * FROM clientes").fetchall(), antes)


if __name__ == "__main__":
    unittest.main()
