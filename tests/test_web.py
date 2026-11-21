import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from app.config import Config
from app.db import conectar, migrar
from app.seguranca import criar_sessao, revogar_sessao
from app.servidor import criar_app
from app.web import (LIMITE_CORPO, Aplicacao, ErroHttp, Roteador, exigir_autenticacao,
                     token_bearer)

# Valores fictícios, só para testes.
SEGREDO = "segredo-ficticio-de-teste-web-0123456789abcdef"
HASH_FICTICIO = "scrypt$ficticio"
DATA = "2026-01-01T00:00:00Z"


def chamar(app, caminho, metodo="GET", corpo=None, cabecalhos=None, query=""):
    environ = {}
    setup_testing_defaults(environ)
    if isinstance(corpo, (dict, list)):
        corpo = json.dumps(corpo).encode("utf-8")
    corpo = corpo or b""
    erros = io.StringIO()
    environ.update({"PATH_INFO": caminho, "REQUEST_METHOD": metodo, "QUERY_STRING": query,
                    "wsgi.input": io.BytesIO(corpo), "wsgi.errors": erros,
                    "CONTENT_LENGTH": str(len(corpo)) if corpo else ""})
    for nome, valor in (cabecalhos or {}).items():
        chave = nome.upper().replace("-", "_")
        if chave not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            chave = "HTTP_" + chave
        environ[chave] = valor
    resposta = {}

    def start_response(status, headers):
        resposta["status"], resposta["headers"] = status, dict(headers)

    dados = b"".join(app(environ, start_response))
    resposta["bruto"] = dados
    resposta["erros"] = erros.getvalue()
    resposta["json"] = json.loads(dados.decode("utf-8")) if dados else None
    resposta["codigo"] = int(resposta["status"].split()[0])
    return resposta


def app_de_teste(config=None):
    roteador = Roteador()

    @roteador.rota("GET", "/api/itens/{id}")
    def obter(req):
        return {"id": req.parametros["id"], "busca": req.parametro_query("busca")}

    @roteador.rota("DELETE", "/api/itens/{id}")
    def apagar(req):
        return 204, None

    @roteador.rota("POST", "/api/eco")
    def eco(req):
        return 201, {"recebido": req.json()}

    @roteador.rota("GET", "/api/texto")
    def texto(req):
        return {"mensagem": "ação concluída"}

    @roteador.rota("GET", "/api/falha")
    def falha(req):
        raise RuntimeError("detalhe interno secreto")

    @roteador.rota("GET", "/api/conflito")
    def conflito(req):
        raise ErroHttp(409, "já existe")

    @roteador.rota("GET", "/api/protegido")
    @exigir_autenticacao
    def protegido(req):
        return {"usuario_id": req.usuario_id, "empresa_id": req.empresa_id}

    return Aplicacao(config, roteador)


class TestRoteamento(unittest.TestCase):
    def setUp(self):
        self.app = app_de_teste()

    def test_parametro_de_caminho_e_query(self):
        r = chamar(self.app, "/api/itens/abc-123", query="busca=Jo%C3%A3o")
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(r["json"], {"id": "abc-123", "busca": "João"})

    def test_parametro_nao_atravessa_barra(self):
        self.assertEqual(chamar(self.app, "/api/itens/a/b")["codigo"], 404)
        self.assertEqual(chamar(self.app, "/api/itens/")["codigo"], 404)

    def test_404_json(self):
        r = chamar(self.app, "/api/nada")
        self.assertEqual(r["codigo"], 404)
        self.assertEqual(r["json"], {"erro": "não encontrado"})

    def test_405_com_allow(self):
        r = chamar(self.app, "/api/itens/1", "PUT")
        self.assertEqual(r["codigo"], 405)
        self.assertIn("erro", r["json"])
        self.assertEqual(r["headers"]["Allow"], "DELETE, GET")

    def test_204_sem_corpo(self):
        r = chamar(self.app, "/api/itens/1", "DELETE")
        self.assertEqual(r["status"], "204 No Content")
        self.assertEqual(r["bruto"], b"")

    def test_rota_repetida(self):
        roteador = Roteador()
        roteador.adicionar("GET", "/api/x", lambda req: {})
        with self.assertRaises(ValueError):
            roteador.adicionar("get", "/api/x", lambda req: {})

    def test_erro_http_so_aceita_status_previstos(self):
        with self.assertRaises(ValueError):
            ErroHttp(418, "x")


class TestRespostas(unittest.TestCase):
    def setUp(self):
        self.app = app_de_teste()

    def test_json_utf8(self):
        r = chamar(self.app, "/api/texto")
        self.assertEqual(r["headers"]["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("ação".encode("utf-8"), r["bruto"])
        self.assertEqual(r["headers"]["Content-Length"], str(len(r["bruto"])))
        self.assertEqual(r["headers"]["X-Content-Type-Options"], "nosniff")

    def test_409(self):
        r = chamar(self.app, "/api/conflito")
        self.assertEqual((r["codigo"], r["json"]), (409, {"erro": "já existe"}))

    def test_500_sem_stack_trace(self):
        r = chamar(self.app, "/api/falha")
        self.assertEqual(r["codigo"], 500)
        self.assertEqual(r["json"], {"erro": "erro interno do servidor"})
        self.assertNotIn(b"Traceback", r["bruto"])
        self.assertNotIn(b"secreto", r["bruto"])
        self.assertIn("Traceback", r["erros"])  # vai só para o log do servidor

    def test_saude_do_servidor_real(self):
        r = chamar(criar_app(None), "/api/saude")
        self.assertEqual((r["codigo"], r["json"]), (200, {"status": "ok"}))


class TestCorpoJson(unittest.TestCase):
    def setUp(self):
        self.app = app_de_teste()

    def test_eco(self):
        r = chamar(self.app, "/api/eco", "POST", {"nome": "Cliente Fictício"})
        self.assertEqual((r["codigo"], r["json"]), (201, {"recebido": {"nome": "Cliente Fictício"}}))

    def test_corpos_invalidos_400(self):
        casos = [b"", b"   ", b"{", b"nao-json", b"[1, 2]", b'"texto"', b"\xff\xfe",
                 b'{"x": NaN}', b"[" * 20000 + b"]" * 20000]
        for corpo in casos:
            with self.subTest(corpo=corpo[:20]):
                r = chamar(self.app, "/api/eco", "POST", corpo)
                self.assertEqual(r["codigo"], 400)
                self.assertIn("erro", r["json"])

    def test_content_length_invalido(self):
        r = chamar(self.app, "/api/eco", "POST", b"{}", {"Content-Length": "abc"})
        self.assertEqual(r["codigo"], 400)

    def test_corpo_incompleto(self):
        r = chamar(self.app, "/api/eco", "POST", b"{}", {"Content-Length": "10"})
        self.assertEqual(r["codigo"], 400)

    def test_limite_de_64kb(self):
        no_limite = json.dumps({"x": "a" * (LIMITE_CORPO - 9)}).encode()
        self.assertEqual(len(no_limite), LIMITE_CORPO)
        self.assertEqual(chamar(self.app, "/api/eco", "POST", no_limite)["codigo"], 201)
        acima = json.dumps({"x": "a" * (LIMITE_CORPO - 8)}).encode()
        self.assertEqual(len(acima), LIMITE_CORPO + 1)
        r = chamar(self.app, "/api/eco", "POST", acima)
        self.assertEqual(r["codigo"], 413)
        self.assertIn("erro", r["json"])


class TestAutenticacao(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "t.db")
        self.con = conectar(self.db)
        self.addCleanup(self.con.close)
        migrar(self.con)
        with self.con:
            self.con.execute("INSERT INTO empresas (id, nome, criado_em) VALUES (?, ?, ?)",
                             ("e1", "Empresa Fictícia", DATA))
            self.con.execute(
                "INSERT INTO usuarios (id, empresa_id, email, senha_hash, criado_em) "
                "VALUES (?, ?, ?, ?, ?)", ("u1", "e1", "a@exemplo.test", HASH_FICTICIO, DATA))
        config = Config(db=self.db, host="127.0.0.1", porta=8000, segredo=SEGREDO, token_ttl=60)
        self.app = app_de_teste(config)

    def _get(self, autorizacao=None):
        cab = {} if autorizacao is None else {"Authorization": autorizacao}
        return chamar(self.app, "/api/protegido", cabecalhos=cab)

    def test_token_valido(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", 60)
        for prefixo in ("Bearer ", "bearer "):
            r = self._get(prefixo + token)
            self.assertEqual(r["codigo"], 200)
            self.assertEqual(r["json"], {"usuario_id": "u1", "empresa_id": "e1"})

    def test_sem_token_401(self):
        r = self._get()
        self.assertEqual(r["codigo"], 401)
        self.assertIn("erro", r["json"])
        self.assertIn("Bearer", r["headers"]["WWW-Authenticate"])

    def test_tokens_invalidos_401(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", 60)
        alterado = token[:-1] + ("A" if token[-1] != "A" else "B")
        for valor in ("", "Bearer", "Basic " + token, token, "Bearer " + alterado,
                      "Bearer " + token + " extra", "Bearer x.y"):
            with self.subTest(valor=valor[:20]):
                self.assertEqual(self._get(valor)["codigo"], 401)

    def test_token_expirado_401(self):
        passado = datetime.now(timezone.utc) - timedelta(hours=2)
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", 60, agora=passado)
        self.assertEqual(self._get("Bearer " + token)["codigo"], 401)

    def test_token_revogado_401(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", 60)
        self.assertEqual(self._get("Bearer " + token)["codigo"], 200)
        self.assertTrue(revogar_sessao(self.con, SEGREDO, token))
        self.assertEqual(self._get("Bearer " + token)["codigo"], 401)

    def test_token_bearer(self):
        class Req:
            def __init__(self, valor):
                self.valor = valor

            def cabecalho(self, nome, padrao=None):
                return self.valor

        self.assertEqual(token_bearer(Req("Bearer abc")), "abc")
        self.assertIsNone(token_bearer(Req(None)))
        self.assertIsNone(token_bearer(Req("Token abc")))


if __name__ == "__main__":
    unittest.main()
