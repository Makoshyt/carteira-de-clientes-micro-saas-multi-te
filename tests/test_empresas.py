import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.config import Config
from app.db import conectar, migrar
from app.seguranca import verificar_senha
from app.servidor import criar_app
from tests.test_web import chamar

# Valores fictícios, só para testes.
SEGREDO = "segredo-ficticio-de-teste-empresas-0123456789"
SENHA = "senha-ficticia-123"


def corpo(**extra):
    base = {"nome_empresa": "Empresa Fictícia", "email": "dono@exemplo.test", "senha": SENHA}
    base.update(extra)
    return base


class TestCadastroEmpresa(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "t.db")
        self.con = conectar(self.db)
        self.addCleanup(self.con.close)
        migrar(self.con)
        config = Config(db=self.db, host="127.0.0.1", porta=8000, segredo=SEGREDO, token_ttl=60)
        self.app = criar_app(config)

    def post(self, dados):
        return chamar(self.app, "/api/empresas", "POST", dados)

    def contar(self, tabela):
        return self.con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]  # nosec B608 - nome fixo do teste

    def test_cria_empresa_e_usuario(self):
        r = self.post(corpo(nome_empresa="  Loja Fictícia  ", email="  Dono@Exemplo.TEST "))
        self.assertEqual(r["codigo"], 201)
        self.assertEqual(set(r["json"]), {"empresa_id", "usuario_id", "email"})
        self.assertEqual(r["json"]["email"], "dono@exemplo.test")
        empresa = self.con.execute("SELECT id, nome FROM empresas").fetchone()
        self.assertEqual((empresa["id"], empresa["nome"]), (r["json"]["empresa_id"], "Loja Fictícia"))
        usuario = self.con.execute("SELECT * FROM usuarios").fetchone()
        self.assertEqual(usuario["id"], r["json"]["usuario_id"])
        self.assertEqual(usuario["empresa_id"], r["json"]["empresa_id"])
        self.assertEqual(usuario["email"], "dono@exemplo.test")

    def test_senha_guardada_so_como_scrypt(self):
        r = self.post(corpo())
        self.assertEqual(r["codigo"], 201)
        self.assertNotIn(SENHA.encode(), r["bruto"])
        self.assertNotIn(b"scrypt", r["bruto"])
        senha_hash = self.con.execute("SELECT senha_hash FROM usuarios").fetchone()[0]
        self.assertTrue(senha_hash.startswith("scrypt$"))
        self.assertNotIn(SENHA, senha_hash)
        self.assertTrue(verificar_senha(SENHA, senha_hash))
        # nenhuma coluna de nenhuma tabela guarda a senha em texto puro
        for (tabela,) in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for linha in self.con.execute(f'SELECT * FROM "{tabela}"'):  # nosec B608 - nomes do próprio banco
                self.assertNotIn(SENHA, [v for v in tuple(linha) if isinstance(v, str)])

    def test_sais_diferentes_por_usuario(self):
        self.assertEqual(self.post(corpo(email="a@exemplo.test"))["codigo"], 201)
        self.assertEqual(self.post(corpo(email="b@exemplo.test"))["codigo"], 201)
        hashes = [h for (h,) in self.con.execute("SELECT senha_hash FROM usuarios")]
        self.assertNotEqual(hashes[0].split("$")[4], hashes[1].split("$")[4])

    def test_email_repetido_409(self):
        self.assertEqual(self.post(corpo())["codigo"], 201)
        r = self.post(corpo(nome_empresa="Outra Fictícia", email="DONO@exemplo.test"))
        self.assertEqual(r["codigo"], 409)
        self.assertIn("erro", r["json"])
        self.assertEqual(self.contar("empresas"), 1)
        self.assertEqual(self.contar("usuarios"), 1)

    def test_ids_do_cliente_sao_ignorados(self):
        r = self.post(corpo(empresa_id="forjado", usuario_id="forjado"))
        self.assertEqual(r["codigo"], 201)
        self.assertNotEqual(r["json"]["empresa_id"], "forjado")
        self.assertNotEqual(r["json"]["usuario_id"], "forjado")

    def test_entradas_invalidas_400(self):
        sem_campo = {campo: {k: v for k, v in corpo().items() if k != campo}
                     for campo in ("nome_empresa", "email", "senha")}
        casos = {
            "nome ausente": sem_campo["nome_empresa"],
            "email ausente": sem_campo["email"],
            "senha ausente": sem_campo["senha"],
            "nome nulo": corpo(nome_empresa=None),
            "nome vazio": corpo(nome_empresa="   "),
            "nome número": corpo(nome_empresa=123),
            "nome longo": corpo(nome_empresa="a" * 121),
            "nome com controle": corpo(nome_empresa="Empresa\nFictícia"),
            "sem email": corpo(email=None),
            "email lista": corpo(email=["a@exemplo.test"]),
            "email sem arroba": corpo(email="dono.exemplo.test"),
            "email sem domínio": corpo(email="dono@"),
            "email sem ponto": corpo(email="dono@exemplo"),
            "email dois arrobas": corpo(email="a@b@exemplo.test"),
            "email com espaço": corpo(email="do no@exemplo.test"),
            "email longo": corpo(email="a" * 245 + "@exemplo.test"),
            "sem senha": corpo(senha=None),
            "senha curta": corpo(senha="1234567"),
            "senha longa": corpo(senha="a" * 129),
            "senha número": corpo(senha=12345678),
        }
        for nome, dados in casos.items():
            with self.subTest(caso=nome):
                r = self.post(dados)
                self.assertEqual(r["codigo"], 400)
                self.assertIn("erro", r["json"])
        self.assertEqual(self.contar("empresas"), 0)
        self.assertEqual(self.contar("usuarios"), 0)

    def test_limites_aceitos(self):
        r = self.post(corpo(nome_empresa="a" * 120, senha="a" * 8, email="x@exemplo.test"))
        self.assertEqual(r["codigo"], 201)
        email = "b" * (254 - len("@exemplo.test")) + "@exemplo.test"
        r = self.post(corpo(senha="s" * 128, email=email))
        self.assertEqual(r["codigo"], 201)
        self.assertEqual(r["json"]["email"], email)

    def test_corpo_invalido_400(self):
        for dados in (b"", b"{", b"[]", json.dumps("texto").encode()):
            with self.subTest(dados=dados):
                self.assertEqual(self.post(dados)["codigo"], 400)

    def test_metodo_errado_405(self):
        self.assertEqual(chamar(self.app, "/api/empresas", "GET")["codigo"], 405)

    def test_transacao_unica_desfaz_empresa_se_usuario_falhar(self):
        # Gatilho de teste que faz o INSERT em usuarios falhar depois do INSERT em empresas.
        with self.con:
            self.con.execute(
                "CREATE TRIGGER falha_usuario BEFORE INSERT ON usuarios "
                "BEGIN SELECT RAISE(ABORT, 'falha simulada'); END")
        r = self.post(corpo())
        self.assertEqual(r["codigo"], 500)
        self.assertEqual(r["json"], {"erro": "erro interno do servidor"})
        self.assertEqual(self.contar("empresas"), 0)
        self.assertEqual(self.contar("usuarios"), 0)

    def test_integrity_error_por_email_vira_409(self):
        # Simula a corrida: o e-mail aparece entre a checagem e o INSERT.
        from app import empresas
        original = empresas._email_existe
        chamadas = []

        def falso(conexao, email):
            chamadas.append(email)
            if len(chamadas) == 1:
                with sqlite3.connect(self.db) as outra:
                    outra.execute("INSERT INTO empresas (id, nome, criado_em) VALUES "
                                  "('e0', 'Concorrente Fictícia', '2026-01-01T00:00:00Z')")
                    outra.execute("INSERT INTO usuarios (id, empresa_id, email, senha_hash, criado_em) "
                                  "VALUES ('u0', 'e0', ?, 'scrypt$ficticio', '2026-01-01T00:00:00Z')",
                                  (email,))
                outra.close()
                return False
            return original(conexao, email)

        empresas._email_existe = falso
        self.addCleanup(setattr, empresas, "_email_existe", original)
        r = self.post(corpo())
        self.assertEqual(r["codigo"], 409)
        self.assertEqual(self.contar("empresas"), 1)


if __name__ == "__main__":
    unittest.main()
