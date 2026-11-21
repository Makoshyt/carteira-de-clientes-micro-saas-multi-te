import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from app.estaticos import PASTA_PADRAO, resolver_arquivo
from app.servidor import criar_app
from app.web import ErroHttp


def requisitar(app, caminho, metodo="GET"):
    """Chama a app WSGI; só decodifica JSON quando o Content-Type for JSON."""
    environ = {}
    setup_testing_defaults(environ)
    environ.update({"PATH_INFO": caminho, "REQUEST_METHOD": metodo, "QUERY_STRING": "",
                    "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(),
                    "CONTENT_LENGTH": ""})
    resposta = {}

    def start_response(status, headers):
        resposta["status"], resposta["headers"] = status, dict(headers)

    dados = b"".join(app(environ, start_response))
    resposta["bruto"] = dados
    resposta["codigo"] = int(resposta["status"].split()[0])
    tipo = resposta["headers"].get("Content-Type", "")
    resposta["json"] = (json.loads(dados.decode("utf-8"))
                        if dados and tipo.startswith("application/json") else None)
    return resposta


class TestEstaticos(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        self.pasta = raiz / "static"
        (self.pasta / "css").mkdir(parents=True)
        (self.pasta / "js").mkdir()
        (self.pasta / "index.html").write_text("<!doctype html><p>inicio</p>", encoding="utf-8")
        (self.pasta / "css" / "estilo.css").write_text("body{margin:0}", encoding="utf-8")
        (self.pasta / "js" / "app.js").write_text("console.log(1);", encoding="utf-8")
        (self.pasta / ".oculto.txt").write_text("oculto", encoding="utf-8")
        (self.pasta / "dados.bin").write_bytes(b"\x00\x01")
        (raiz / "segredo.txt").write_text("fora da pasta", encoding="utf-8")
        self.raiz = raiz
        self.app = criar_app(None, pasta_estaticos=self.pasta)

    def test_pagina_inicial(self):
        r = requisitar(self.app, "/")
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(r["headers"]["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(r["bruto"], b"<!doctype html><p>inicio</p>")
        self.assertEqual(r["headers"]["Content-Length"], str(len(r["bruto"])))

    def test_content_types(self):
        casos = {
            "/static/index.html": "text/html; charset=utf-8",
            "/static/css/estilo.css": "text/css; charset=utf-8",
            "/static/js/app.js": "text/javascript; charset=utf-8",
        }
        for caminho, tipo in casos.items():
            with self.subTest(caminho=caminho):
                r = requisitar(self.app, caminho)
                self.assertEqual(r["codigo"], 200)
                self.assertEqual(r["headers"]["Content-Type"], tipo)

    def test_cabecalhos_de_seguranca(self):
        for caminho in ("/", "/static/js/app.js", "/api/saude", "/static/nada.js"):
            with self.subTest(caminho=caminho):
                h = requisitar(self.app, caminho)["headers"]
                self.assertEqual(h["X-Content-Type-Options"], "nosniff")
                csp = h["Content-Security-Policy"]
                self.assertIn("default-src 'self'", csp)
                self.assertNotIn("unsafe-inline", csp)
                self.assertNotIn("*", csp)

    def test_api_sem_cache(self):
        r = requisitar(self.app, "/api/saude")
        self.assertEqual(r["json"], {"status": "ok"})
        self.assertEqual(r["headers"]["Cache-Control"], "no-store")

    def test_path_traversal_404(self):
        caminhos = [
            "/static/../segredo.txt",
            "/static/../../etc/passwd",
            "/static/css/../../segredo.txt",
            "/static/css/../index.html",
            "/static/./index.html",
            "/static//etc/passwd",
            "/static/" + str(self.raiz / "segredo.txt"),
            "/static/..\\segredo.txt",
            "/static/C:/Windows/win.ini",
            "/static/index.html\x00.js",
            "/static/.oculto.txt",
            "/static/css//estilo.css",
            "/static/",
            "/static",
            "/static/css",
            "/static/dados.bin",
            "/static/nada.js",
        ]
        for caminho in caminhos:
            with self.subTest(caminho=caminho):
                r = requisitar(self.app, caminho)
                self.assertEqual(r["codigo"], 404)
                self.assertEqual(r["json"], {"erro": "não encontrado"})
                self.assertNotIn(b"fora da pasta", r["bruto"])

    @unittest.skipUnless(hasattr(os, "symlink"), "sem suporte a links simbólicos")
    def test_link_simbolico_para_fora_404(self):
        try:
            os.symlink(self.raiz / "segredo.txt", self.pasta / "link.txt")
        except OSError:
            self.skipTest("não foi possível criar link simbólico")
        r = requisitar(self.app, "/static/link.txt")
        self.assertEqual(r["codigo"], 404)
        self.assertNotIn(b"fora da pasta", r["bruto"])

    def test_resolver_arquivo_recusa_fora_da_pasta(self):
        for relativo in ("", "../segredo.txt", "/etc/passwd", "css/../../segredo.txt"):
            with self.subTest(relativo=relativo):
                with self.assertRaises(ErroHttp) as ctx:
                    resolver_arquivo(self.pasta, relativo)
                self.assertEqual(ctx.exception.status, 404)

    def test_metodo_nao_permitido(self):
        r = requisitar(self.app, "/static/js/app.js", "POST")
        self.assertEqual(r["codigo"], 405)
        self.assertEqual(r["headers"]["Allow"], "GET")
        self.assertEqual(requisitar(self.app, "/", "DELETE")["codigo"], 405)

    def test_rotas_da_api_continuam_funcionando(self):
        self.assertEqual(requisitar(self.app, "/api/nada")["codigo"], 404)
        self.assertEqual(requisitar(self.app, "/api/clientes")["codigo"], 401)

    def test_index_real_do_projeto(self):
        self.assertTrue((PASTA_PADRAO / "index.html").is_file())
        r = requisitar(criar_app(None), "/")
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(r["headers"]["Content-Type"], "text/html; charset=utf-8")
        self.assertIn(b"<html", r["bruto"].lower())


if __name__ == "__main__":
    unittest.main()
