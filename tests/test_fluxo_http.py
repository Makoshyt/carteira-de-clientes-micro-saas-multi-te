"""Teste de ponta a ponta da fase 1 com o servidor HTTP real (wsgiref) numa porta livre.

Sobe a mesma aplicação do run.py em 127.0.0.1 numa thread, com banco SQLite temporário,
e percorre o fluxo: migrações -> cadastro -> login -> /api/me -> logout -> 401.
Só usa a interface local (sem rede externa).
"""
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

import run
from app.config import Config
from app.seguranca import FORMATO_DATA
from app.servidor import criar_app

# Valores fictícios, só para testes.
SEGREDO = "segredo-ficticio-de-teste-http-0123456789abcd"
SENHA = "senha-ficticia-123"
EMAIL = "dono@exemplo.test"


class _HandlerSilencioso(WSGIRequestHandler):
    def log_message(self, formato, *args):  # não polui a saída dos testes
        pass


class TestFluxoHttp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "sub" / "carteira.db")
        config = Config(db=self.db, host="127.0.0.1", porta=0, segredo=SEGREDO, token_ttl=60)
        self.assertTrue(run.preparar(config))   # primeira vez aplica
        self.assertEqual(run.preparar(config), [])  # segunda vez não faz nada
        self.servidor = make_server("127.0.0.1", 0, criar_app(config),
                                    handler_class=_HandlerSilencioso)
        self.porta = self.servidor.server_address[1]
        thread = threading.Thread(target=self.servidor.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, metodo, caminho, corpo=None, token=None, bruto=None):
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        try:
            cabecalhos = {}
            dados = bruto
            if corpo is not None:
                dados = json.dumps(corpo).encode("utf-8")
            if dados is not None:
                cabecalhos["Content-Type"] = "application/json"
            if token is not None:
                cabecalhos["Authorization"] = f"Bearer {token}"
            conexao.request(metodo, caminho, body=dados, headers=cabecalhos)
            resposta = conexao.getresponse()
            conteudo = resposta.read()
            return resposta.status, (json.loads(conteudo) if conteudo else None), resposta
        finally:
            conexao.close()

    def consultar(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_migracoes_um_registro_por_versao(self):
        versoes = [v for (v,) in self.consultar("SELECT versao FROM schema_migrations")]
        self.assertEqual(len(versoes), len(set(versoes)))
        self.assertIn("0001_inicial", versoes)

    def test_fluxo_completo(self):
        status, corpo, _ = self.pedir("GET", "/api/saude")
        self.assertEqual((status, corpo), (200, {"status": "ok"}))

        status, cadastro, resposta = self.pedir(
            "POST", "/api/empresas",
            {"nome_empresa": "Empresa Fictícia", "email": EMAIL, "senha": SENHA})
        self.assertEqual(status, 201)
        self.assertTrue(resposta.getheader("Content-Type").startswith("application/json"))
        (senha_hash,) = self.consultar("SELECT senha_hash FROM usuarios")[0]
        self.assertTrue(senha_hash.startswith("scrypt$"))
        self.assertNotIn(SENHA, senha_hash)

        status, corpo, _ = self.pedir(
            "POST", "/api/empresas",
            {"nome_empresa": "Outra Fictícia", "email": EMAIL.upper(), "senha": SENHA})
        self.assertEqual(status, 409)
        self.assertIn("erro", corpo)

        status, corpo, _ = self.pedir("POST", "/api/login", {"email": EMAIL, "senha": "errada-000"})
        self.assertEqual(status, 401)
        self.assertNotIn("token", corpo)

        status, login, _ = self.pedir("POST", "/api/login", {"email": EMAIL, "senha": SENHA})
        self.assertEqual(status, 200)
        token = login["token"]

        status, me, _ = self.pedir("GET", "/api/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(me["empresa_id"], cadastro["empresa_id"])
        self.assertEqual(me["usuario_id"], cadastro["usuario_id"])
        self.assertEqual(me["email"], EMAIL)

        status, corpo, _ = self.pedir("POST", "/api/logout", token=token)
        self.assertEqual((status, corpo), (204, None))
        status, corpo, resposta = self.pedir("GET", "/api/me", token=token)
        self.assertEqual(status, 401)
        self.assertIn("erro", corpo)
        self.assertIn("Bearer", resposta.getheader("WWW-Authenticate"))

    def test_tokens_rejeitados_401(self):
        self.pedir("POST", "/api/empresas",
                   {"nome_empresa": "Empresa Fictícia", "email": EMAIL, "senha": SENHA})
        token = self.pedir("POST", "/api/login", {"email": EMAIL, "senha": SENHA})[1]["token"]
        sessao_id, assinatura = token.split(".")
        trocado = "A" if assinatura[0] != "A" else "B"
        self.assertEqual(self.pedir("GET", "/api/me")[0], 401)
        self.assertEqual(self.pedir("GET", "/api/me", token=f"{sessao_id}.{trocado}{assinatura[1:]}")[0], 401)
        self.assertEqual(self.pedir("GET", "/api/me", token=token)[0], 200)

        passado = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(FORMATO_DATA)
        con = sqlite3.connect(self.db)
        try:
            with con:
                con.execute("UPDATE sessoes SET expira_em = ?", (passado,))
        finally:
            con.close()
        status, corpo, _ = self.pedir("GET", "/api/me", token=token)
        self.assertEqual(status, 401)
        self.assertIn("erro", corpo)

    def test_erros_json_padronizados(self):
        status, corpo, _ = self.pedir("POST", "/api/empresas", bruto=b"{")
        self.assertEqual(status, 400)
        self.assertIn("erro", corpo)
        status, corpo, _ = self.pedir("POST", "/api/empresas", {"nome_empresa": "X", "email": EMAIL,
                                                                "senha": "curta"})
        self.assertEqual(status, 400)
        self.assertIn("erro", corpo)
        status, corpo, _ = self.pedir("GET", "/api/login")
        self.assertEqual(status, 405)
        self.assertIn("erro", corpo)
        status, corpo, _ = self.pedir("GET", "/api/inexistente")
        self.assertEqual((status, corpo), (404, {"erro": "não encontrado"}))
        # O 413 (corpo > 64 KB) é coberto em tests/test_web.py chamando a app WSGI direto:
        # pelo socket real o servidor responde sem ler o corpo e a conexão pode ser resetada.
        self.assertEqual(self.consultar("SELECT COUNT(*) FROM empresas"), [(0,)])


if __name__ == "__main__":
    unittest.main()
