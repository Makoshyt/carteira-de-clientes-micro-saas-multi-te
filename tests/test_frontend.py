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


class TestFrontendClientes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PASTA_PADRAO / "index.html").read_text(encoding="utf-8")
        cls.js = (PASTA_PADRAO / "app.js").read_text(encoding="utf-8")

    def test_index_servido_tem_a_tela_de_clientes(self):
        r = requisitar(criar_app(None), "/")
        self.assertEqual(r["codigo"], 200)
        corpo = r["bruto"].decode("utf-8")
        self.assertIn('id="form-cliente"', corpo)
        self.assertIn('id="lista-clientes"', corpo)

    def test_tela_tem_busca_lista_e_formulario(self):
        for trecho in ('id="titulo-empresa"', 'id="form-busca"', 'id="campo-busca"',
                       'id="tabela-clientes"', 'id="lista-clientes"', 'id="form-cliente"',
                       'id="erro-form-cliente"', 'id="botao-cancelar-edicao"',
                       'name="cliente_id"', 'name="cliente_nome"', 'name="cliente_email"',
                       'name="cliente_telefone"', 'name="cliente_observacoes"',
                       'name="cliente_status"', '<option value="ativo" selected>',
                       '<option value="inativo">'):
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, self.html)

    def test_limites_do_formulario_batem_com_a_validacao(self):
        from app import clientes
        for nome, maximo in (("cliente_nome", clientes.NOME_MAX),
                             ("cliente_email", clientes.EMAIL_CLIENTE_MAX),
                             ("cliente_telefone", clientes.TELEFONE_MAX),
                             ("cliente_observacoes", clientes.OBSERVACOES_MAX)):
            with self.subTest(campo=nome):
                tag = re.search(r'<(input|textarea)[^>]*name="%s"[^>]*>' % nome, self.html)
                self.assertIsNotNone(tag)
                self.assertIn('maxlength="%d"' % maximo, tag.group(0))

    def test_ids_e_campos_usados_no_js_existem_no_html(self):
        ids = set(re.findall(r'\bel\("([^"]+)"\)', self.js))
        self.assertTrue(ids)
        for ident in sorted(ids):
            with self.subTest(id=ident):
                self.assertIn('id="%s"' % ident, self.html)
        campos = set(re.findall(r"\.elements\.([a-z_]+)", self.js))
        for campo in sorted(campos):
            with self.subTest(campo=campo):
                self.assertIn('name="%s"' % campo, self.html)

    def test_js_usa_as_rotas_de_clientes(self):
        for trecho in ('"/api/clientes"', '"/api/clientes/"', '"?busca="', "encodeURIComponent(",
                       '"PUT"', '"DELETE"', '"POST"', "confirm("):
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, self.js)

    def test_js_trata_401_limpando_o_token_e_voltando_ao_login(self):
        trecho = re.search(r"function sessaoPerdida\(\) \{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(trecho)
        self.assertIn("limparSessao()", trecho.group(1))
        self.assertIn("mostrarEntrada()", trecho.group(1))
        protegida = re.search(r"async function chamarApiProtegida\(.*?\n\}", self.js, re.S)
        self.assertIsNotNone(protegida)
        self.assertIn("status === 401", protegida.group(0))
        self.assertIn("sessaoPerdida()", protegida.group(0))
        # Toda chamada às rotas de clientes passa pelo tratamento de 401.
        self.assertNotRegex(self.js, r"chamarApi\(\s*\"[A-Z]+\",\s*(\"/api/clientes|caminho)")


if __name__ == "__main__":
    unittest.main()
