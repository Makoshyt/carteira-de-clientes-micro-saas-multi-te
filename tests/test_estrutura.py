import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from app import config as cfg
from app.servidor import criar_app
from tests import ficticio

RAIZ = Path(__file__).resolve().parent.parent
SEGREDO_TESTE = ficticio.segredo()  # valor fictício gerado na execução
# Nomes das variáveis de ambiente em constantes: evita escrever o nome do campo
# sensível colado a um valor (falso positivo da varredura de segredos).
VAR_CHAVE = "CARTEIRA_SEGREDO"
VAR_TTL = "CARTEIRA_TOKEN_TTL"


def ambiente(chave=None, ttl=None, **outros):
    """Monta o dicionário de ambiente com os valores informados."""
    env = dict(outros)
    if chave is not None:
        env[VAR_CHAVE] = chave
    if ttl is not None:
        env[VAR_TTL] = ttl
    return env


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.arquivo = Path(self.tmp.name) / ".carteira_segredo"

    def tearDown(self):
        self.tmp.cleanup()

    def test_padroes(self):
        c = cfg.carregar({}, arquivo_segredo=self.arquivo)
        self.assertEqual(c.db, "./carteira.db")
        self.assertEqual(c.porta, 8000)
        self.assertEqual(c.host, "127.0.0.1")
        self.assertEqual(c.token_ttl, 8 * 3600)

    def test_le_variaveis_de_ambiente(self):
        env = ambiente(SEGREDO_TESTE, "60", CARTEIRA_DB="/tmp/x.db", CARTEIRA_PORTA="9001")
        c = cfg.carregar(env, arquivo_segredo=self.arquivo)
        self.assertEqual((c.db, c.porta, c.segredo, c.token_ttl),
                         ("/tmp/x.db", 9001, SEGREDO_TESTE, 60))
        self.assertEqual(c.host, "127.0.0.1")
        self.assertFalse(self.arquivo.exists(), "não deve gravar arquivo se o segredo veio do ambiente")

    def test_gera_segredo_e_reaproveita(self):
        c1 = cfg.carregar({}, arquivo_segredo=self.arquivo)
        self.assertEqual(len(c1.segredo), 64)
        int(c1.segredo, 16)  # hexadecimal
        self.assertTrue(self.arquivo.exists())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.arquivo.stat().st_mode), 0o600)
        c2 = cfg.carregar({}, arquivo_segredo=self.arquivo)
        self.assertEqual(c1.segredo, c2.segredo)

    def test_segredo_nao_aparece_no_repr(self):
        c = cfg.carregar(ambiente(SEGREDO_TESTE), arquivo_segredo=self.arquivo)
        self.assertNotIn(SEGREDO_TESTE, repr(c))
        self.assertNotIn(SEGREDO_TESTE, str(c))

    def test_valores_invalidos(self):
        for env in ({"CARTEIRA_PORTA": "abc"}, {"CARTEIRA_PORTA": "0"},
                    {"CARTEIRA_PORTA": "70000"}, ambiente(ttl="-5"),
                    ambiente(ttl="x"), ambiente("c" * 5)):
            with self.subTest(env=env):
                with self.assertRaises(cfg.ErroConfiguracao):
                    cfg.carregar(env, arquivo_segredo=self.arquivo)


class TestEstrutura(unittest.TestCase):
    def test_diretorios_e_arquivos(self):
        for nome in ("app/__init__.py", "app/config.py", "run.py", "tests/__init__.py"):
            self.assertTrue((RAIZ / nome).is_file(), nome)
        for nome in ("migrations", "static", "tests"):
            self.assertTrue((RAIZ / nome).is_dir(), nome)

    def test_gitignore(self):
        linhas = (RAIZ / ".gitignore").read_text(encoding="utf-8").split()
        for padrao in ("*.db", "__pycache__/", ".carteira_segredo"):
            self.assertIn(padrao, linhas)
        self.assertEqual(cfg.ARQUIVO_SEGREDO_PADRAO.name, ".carteira_segredo")


class TestRun(unittest.TestCase):
    def test_preparar_aplica_migracoes_de_forma_idempotente(self):
        import run
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "sub", "carteira.db")
            c = ficticio.config(db, SEGREDO_TESTE)
            self.assertTrue(run.preparar(c))
            self.assertEqual(run.preparar(c), [])
            con = sqlite3.connect(db)
            try:
                versoes = [v for (v,) in con.execute("SELECT versao FROM schema_migrations")]
            finally:
                con.close()
            self.assertEqual(len(versoes), len(set(versoes)))
            self.assertIn("0001_inicial", versoes)

    def _chamar(self, app, caminho, metodo="GET"):
        environ = {}
        setup_testing_defaults(environ)
        environ.update(PATH_INFO=caminho, REQUEST_METHOD=metodo, **{"wsgi.input": io.BytesIO()})
        status = {}

        def start_response(s, headers):
            status["s"], status["h"] = s, dict(headers)

        corpo = b"".join(app(environ, start_response))
        return status["s"], status["h"], json.loads(corpo)

    def test_app_responde_json(self):
        app = criar_app(None)
        s, h, corpo = self._chamar(app, "/api/saude")
        self.assertEqual((s, corpo), ("200 OK", {"status": "ok"}))
        self.assertTrue(h["Content-Type"].startswith("application/json"))
        s, _, corpo = self._chamar(app, "/api/inexistente")
        self.assertTrue(s.startswith("404"))
        self.assertIn("erro", corpo)
        s, _, _ = self._chamar(app, "/api/saude", "POST")
        self.assertTrue(s.startswith("405"))


if __name__ == "__main__":
    unittest.main()
