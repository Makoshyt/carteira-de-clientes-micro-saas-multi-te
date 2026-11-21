import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Config
from app.db import conectar, migrar
from app.seguranca import FORMATO_DATA
from app.servidor import criar_app
from tests import ficticio
from tests.test_web import chamar

# Valores fictícios gerados na execução, só para testes.
SEGREDO = ficticio.segredo()
SENHA = ficticio.senha()
EMAIL = "dono@exemplo.test"


class TestLoginLogoutMe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "t.db")
        self.con = conectar(self.db)
        self.addCleanup(self.con.close)
        migrar(self.con)
        self.config = Config(db=self.db, host="127.0.0.1", porta=8000,
                             segredo=SEGREDO, token_ttl=60)
        self.app = criar_app(self.config)
        r = chamar(self.app, "/api/empresas", "POST",
                   {"nome_empresa": "Empresa Fictícia", "email": EMAIL, "senha": SENHA})
        self.assertEqual(r["codigo"], 201)
        self.cadastro = r["json"]

    def login(self, email=EMAIL, senha=SENHA, app=None):
        return chamar(app or self.app, "/api/login", "POST", {"email": email, "senha": senha})

    def token(self):
        r = self.login()
        self.assertEqual(r["codigo"], 200)
        return r["json"]["token"]

    @staticmethod
    def auth(token):
        return {"Authorization": f"Bearer {token}"}

    def me(self, token):
        return chamar(self.app, "/api/me", "GET", cabecalhos=self.auth(token))

    # ------------------------------------------------------------------ login

    def test_login_devolve_token_e_expiracao(self):
        antes = datetime.now(timezone.utc).replace(microsecond=0)
        r = self.login(email="  DONO@Exemplo.Test ")
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(set(r["json"]), {"token", "expira_em"})
        self.assertIsInstance(r["json"]["token"], str)
        expira = datetime.strptime(r["json"]["expira_em"], FORMATO_DATA).replace(tzinfo=timezone.utc)
        self.assertGreaterEqual(expira, antes + timedelta(seconds=60))
        self.assertLessEqual(expira, antes + timedelta(seconds=62))
        self.assertNotIn(SENHA.encode(), r["bruto"])
        self.assertNotIn(b"scrypt", r["bruto"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sessoes").fetchone()[0], 1)

    def test_login_invalido_mensagem_generica(self):
        senha_errada = self.login(senha=SENHA + "-errada")
        email_inexistente = self.login(email="ninguem@exemplo.test")
        for r in (senha_errada, email_inexistente):
            self.assertEqual(r["codigo"], 401)
            self.assertNotIn("token", r["json"])
        self.assertEqual(senha_errada["json"], email_inexistente["json"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sessoes").fetchone()[0], 0)

    def test_login_entradas_invalidas(self):
        for dados in ({"senha": SENHA}, {"email": EMAIL}, {"email": 1, "senha": SENHA},
                      {"email": EMAIL, "senha": ["x"]}):
            with self.subTest(dados=dados):
                r = chamar(self.app, "/api/login", "POST", dados)
                self.assertEqual(r["codigo"], 400)
                self.assertIn("erro", r["json"])
        for bruto in (b"", b"{", b"[]"):
            with self.subTest(bruto=bruto):
                self.assertEqual(chamar(self.app, "/api/login", "POST", bruto)["codigo"], 400)
        for email, senha in (("", SENHA), (EMAIL, ""), ("a" * 300, SENHA), (EMAIL, "a" * 500)):
            with self.subTest(email=email[:10], senha=len(senha)):
                self.assertEqual(self.login(email=email, senha=senha)["codigo"], 401)

    def test_login_metodo_errado_405(self):
        self.assertEqual(chamar(self.app, "/api/login", "GET")["codigo"], 405)

    # ------------------------------------------------------------------ /api/me

    def test_me_devolve_dados_da_sessao(self):
        r = self.me(self.token())
        self.assertEqual(r["codigo"], 200)
        self.assertEqual(r["json"], {
            "usuario_id": self.cadastro["usuario_id"],
            "email": EMAIL,
            "empresa_id": self.cadastro["empresa_id"],
            "nome_empresa": "Empresa Fictícia",
        })

    def test_me_de_cada_empresa(self):
        r = chamar(self.app, "/api/empresas", "POST",
                   {"nome_empresa": "Outra Fictícia", "email": "outro@exemplo.test", "senha": SENHA})
        outra = r["json"]
        token_a = self.token()
        token_b = self.login(email="outro@exemplo.test")["json"]["token"]
        self.assertEqual(self.me(token_a)["json"]["empresa_id"], self.cadastro["empresa_id"])
        self.assertEqual(self.me(token_b)["json"]["empresa_id"], outra["empresa_id"])
        self.assertEqual(self.me(token_b)["json"]["nome_empresa"], "Outra Fictícia")

    def test_me_sem_token_ou_token_invalido_401(self):
        token = self.token()
        sessao_id, assinatura = token.split(".")
        trocado = "A" if assinatura[0] != "A" else "B"
        casos = {
            "sem cabeçalho": None,
            "esquema errado": {"Authorization": f"Basic {token}"},
            "bearer vazio": {"Authorization": "Bearer"},
            "lixo": self.auth("abc"),
            "assinatura alterada": self.auth(f"{sessao_id}.{trocado}{assinatura[1:]}"),
            "sessão alterada": self.auth(f"{sessao_id[:-1]}{'x' if sessao_id[-1] != 'x' else 'y'}.{assinatura}"),
        }
        for nome, cabecalhos in casos.items():
            with self.subTest(caso=nome):
                r = chamar(self.app, "/api/me", "GET", cabecalhos=cabecalhos)
                self.assertEqual(r["codigo"], 401)
                self.assertIn("erro", r["json"])

    def test_token_de_outro_segredo_401(self):
        outro = Config(db=self.db, host="127.0.0.1", porta=8000,
                       segredo=ficticio.segredo(), token_ttl=60)
        token = self.login(app=criar_app(outro))["json"]["token"]
        self.assertEqual(self.me(token)["codigo"], 401)

    def test_token_expirado_401(self):
        token = self.token()
        self.assertEqual(self.me(token)["codigo"], 200)
        passado = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(FORMATO_DATA)
        with self.con:
            self.con.execute("UPDATE sessoes SET expira_em = ?", (passado,))
        self.assertEqual(self.me(token)["codigo"], 401)

    # ------------------------------------------------------------------ logout

    def test_logout_revoga_token(self):
        token = self.token()
        r = chamar(self.app, "/api/logout", "POST", cabecalhos=self.auth(token))
        self.assertEqual(r["codigo"], 204)
        self.assertEqual(r["bruto"], b"")
        self.assertEqual(self.me(token)["codigo"], 401)
        r = chamar(self.app, "/api/logout", "POST", cabecalhos=self.auth(token))
        self.assertEqual(r["codigo"], 401)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sessoes").fetchone()[0], 0)

    def test_logout_so_revoga_a_propria_sessao(self):
        token1 = self.token()
        token2 = self.token()
        self.assertNotEqual(token1, token2)
        r = chamar(self.app, "/api/logout", "POST", cabecalhos=self.auth(token1))
        self.assertEqual(r["codigo"], 204)
        self.assertEqual(self.me(token1)["codigo"], 401)
        self.assertEqual(self.me(token2)["codigo"], 200)

    def test_logout_sem_token_401(self):
        self.assertEqual(chamar(self.app, "/api/logout", "POST")["codigo"], 401)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sessoes").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
