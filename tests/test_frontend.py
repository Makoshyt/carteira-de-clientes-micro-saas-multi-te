"""Verificações estáticas do frontend (static/index.html, app.css e app.js)."""
import re
import unittest

from app.estaticos import PASTA_PADRAO
from app.servidor import criar_app
from tests import test_estaticos

requisitar = test_estaticos.requisitar


class TestFrontendAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PASTA_PADRAO / "index.html").read_text(encoding="utf-8")
        cls.js = (PASTA_PADRAO / "app.js").read_text(encoding="utf-8")
        cls.css = (PASTA_PADRAO / "app.css").read_text(encoding="utf-8")

    def test_arquivos_servidos_pelo_backend(self):
        app = criar_app(None)
        for caminho, tipo in (("/static/app.js", "text/javascript; charset=utf-8"),
                              ("/static/app.css", "text/css; charset=utf-8")):
            with self.subTest(caminho=caminho):
                r = requisitar(app, caminho)
                self.assertEqual(r["codigo"], 200)
                self.assertEqual(r["headers"]["Content-Type"], tipo)

    def test_formularios_de_cadastro_e_login(self):
        self.assertIn('id="form-cadastro"', self.html)
        self.assertIn('id="form-login"', self.html)
        self.assertIn('name="nome_empresa"', self.html)
        self.assertEqual(self.html.count('name="email"'), 2)
        self.assertEqual(self.html.count('name="senha"'), 2)
        self.assertIn('id="botao-sair"', self.html)

    def test_sem_dependencias_externas_nem_codigo_inline(self):
        self.assertIsNone(re.search(r"(src|href)\s*=\s*\"(https?:)?//", self.html))
        self.assertNotIn("<style", self.html.lower())
        self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)", self.html, re.I))
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", self.html, re.I))
        self.assertNotIn("@import", self.css)
        self.assertNotIn("url(", self.css)

    def test_js_usa_textcontent_e_nao_innerhtml(self):
        for proibido in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                         "document.write", "eval(", "new Function"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.js)
        self.assertIn("textContent", self.js)

    def test_js_chama_a_api_e_usa_sessionstorage(self):
        for trecho in ('"/api/empresas"', '"/api/login"', '"/api/logout"', '"/api/me"',
                       "fetch(", "sessionStorage.setItem", "sessionStorage.removeItem"):
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, self.js)
        self.assertNotIn("localStorage", self.js)
        self.assertNotIn("http://", self.js)
        self.assertNotIn("https://", self.js)


if __name__ == "__main__":
    unittest.main()
