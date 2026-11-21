"""Revisão final: o roteiro do teste manual no navegador, automatizado.

Sobe o servidor HTTP real (wsgiref) numa porta livre de 127.0.0.1 com banco SQLite
temporário e repete as mesmas requisições que static/app.js faz quando duas empresas
fictícias usam a interface: abrir a página, cadastrar, entrar, criar, buscar, editar,
excluir e sair. Confere em cada passo que uma empresa não vê nem mexe nos dados da outra.

Também confere que arquivos sensíveis (``.env``, bancos ``.db``/``.sqlite3`` e o arquivo de
segredo local) são ignorados pelo Git. Só usa a interface local (sem rede externa).
"""
import fnmatch
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote
from wsgiref.simple_server import WSGIRequestHandler, make_server

import run
from app.config import Config
from app.servidor import criar_app

RAIZ = Path(__file__).resolve().parent.parent

# Valores fictícios, só para testes.
SEGREDO = "segredo-ficticio-de-teste-revisao-final-0123456"
SENHA_A = "senha-ficticia-aaa-123"
SENHA_B = "senha-ficticia-bbb-456"
EMAIL_A = "dona.a@exemplo.test"
EMAIL_B = "dono.b@exemplo.test"


class _HandlerSilencioso(WSGIRequestHandler):
    def log_message(self, formato, *args):  # não polui a saída dos testes
        pass


class Navegador:
    """Imita o ``chamarApi`` de static/app.js (mesmos cabeçalhos e formato de corpo)."""

    def __init__(self, porta):
        self.porta = porta
        self.token = None

    def pedir(self, metodo, caminho, corpo=None):
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        try:
            cabecalhos = {"Accept": "application/json"}
            if self.token:
                cabecalhos["Authorization"] = "Bearer " + self.token
            dados = None
            if corpo is not None:
                cabecalhos["Content-Type"] = "application/json"
                dados = json.dumps(corpo).encode("utf-8")
            conexao.request(metodo, caminho, body=dados, headers=cabecalhos)
            resposta = conexao.getresponse()
            conteudo = resposta.read()
            tipo = resposta.getheader("Content-Type") or ""
            if resposta.status != 204 and tipo.startswith("application/json"):
                return resposta.status, json.loads(conteudo)
            return resposta.status, conteudo
        finally:
            conexao.close()

    def bruto(self, caminho):
        """GET sem normalização do caminho (como um cliente malicioso faria)."""
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        try:
            conexao.putrequest("GET", caminho, skip_accept_encoding=True)
            conexao.endheaders()
            resposta = conexao.getresponse()
            return resposta.status, resposta.read()
        finally:
            conexao.close()

    # Ações da interface -------------------------------------------------------------

    def cadastrar(self, nome_empresa, email, senha):
        return self.pedir("POST", "/api/empresas",
                          {"nome_empresa": nome_empresa, "email": email, "senha": senha})

    def entrar(self, email, senha):
        status, dados = self.pedir("POST", "/api/login", {"email": email, "senha": senha})
        if status == 200:
            self.token = dados["token"]
        return status, dados

    def sair(self):
        status, dados = self.pedir("POST", "/api/logout")
        token_antigo, self.token = self.token, None
        return status, dados, token_antigo

    def formulario(self, nome, email="", telefone="", observacoes="", status="ativo"):
        # O formulário sempre manda todos os campos; os vazios vão como "".
        return {"nome": nome, "email": email, "telefone": telefone,
                "observacoes": observacoes, "status": status}

    def listar(self, busca=""):
        caminho = "/api/clientes"
        if busca:
            caminho += "?busca=" + quote(busca, safe="")
        return self.pedir("GET", caminho)


class TestRoteiroManualDuasEmpresas(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(db=str(Path(tmp.name) / "carteira.db"), host="127.0.0.1", porta=0,
                        segredo=SEGREDO, token_ttl=600)
        run.preparar(config)
        self.servidor = make_server("127.0.0.1", 0, criar_app(config),
                                    handler_class=_HandlerSilencioso)
        porta = self.servidor.server_address[1]
        thread = threading.Thread(target=self.servidor.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)
        self.a = Navegador(porta)
        self.b = Navegador(porta)

    def nomes(self, navegador, busca=""):
        status, dados = navegador.listar(busca)
        self.assertEqual(status, 200)
        return [c["nome"] for c in dados]

    def test_pagina_e_estaticos_abrem(self):
        status, html = self.a.pedir("GET", "/")
        self.assertEqual(status, 200)
        texto = html.decode("utf-8")
        self.assertIn('src="/static/app.js"', texto)
        self.assertIn('href="/static/app.css"', texto)
        for caminho in ("/static/app.js", "/static/app.css"):
            with self.subTest(caminho=caminho):
                status, conteudo = self.a.pedir("GET", caminho)
                self.assertEqual(status, 200)
                self.assertTrue(conteudo)

    def test_path_traversal_em_static_devolve_404(self):
        for caminho in ("/static/../run.py", "/static/../app/config.py",
                        "/static/%2e%2e/run.py", "/static/..%2fapp%2fconfig.py",
                        "/static/.env", "/static/../.env", "/static/../.carteira_segredo"):
            with self.subTest(caminho=caminho):
                status, _ = self.a.bruto(caminho)
                self.assertEqual(status, 404)

    def test_fluxo_completo_com_duas_empresas(self):
        a, b = self.a, self.b

        # Cadastro das duas empresas e login.
        self.assertEqual(a.cadastrar("Padaria Fictícia A", EMAIL_A, SENHA_A)[0], 201)
        self.assertEqual(b.cadastrar("Oficina Fictícia B", EMAIL_B, SENHA_B)[0], 201)
        self.assertEqual(a.entrar(EMAIL_A, "senha-errada-000")[0], 401)
        self.assertIsNone(a.token)
        self.assertEqual(a.entrar(EMAIL_A, SENHA_A)[0], 200)
        self.assertEqual(b.entrar(EMAIL_B, SENHA_B)[0], 200)

        status, me_a = a.pedir("GET", "/api/me")
        self.assertEqual((status, me_a["nome_empresa"], me_a["email"]),
                         (200, "Padaria Fictícia A", EMAIL_A))
        status, me_b = b.pedir("GET", "/api/me")
        self.assertEqual((status, me_b["nome_empresa"]), (200, "Oficina Fictícia B"))
        self.assertNotEqual(me_a["empresa_id"], me_b["empresa_id"])

        # Listas começam vazias.
        self.assertEqual(self.nomes(a), [])
        self.assertEqual(self.nomes(b), [])

        # Criar clientes pelo formulário (campos vazios viram null).
        status, maria_a = a.pedir("POST", "/api/clientes", a.formulario("Maria Fictícia"))
        self.assertEqual(status, 201)
        self.assertEqual((maria_a["email"], maria_a["telefone"], maria_a["observacoes"],
                          maria_a["status"]), (None, None, None, "ativo"))
        status, joao_a = a.pedir("POST", "/api/clientes", a.formulario(
            "João Exemplo", "joao@exemplo.test", "(11) 0000-0000", "linha 1\nlinha 2",
            "inativo"))
        self.assertEqual((status, joao_a["status"]), (201, "inativo"))
        status, maria_b = b.pedir("POST", "/api/clientes", b.formulario("MARIA da Oficina"))
        self.assertEqual(status, 201)

        # Erro de validação do formulário aparece como {"erro": ...}.
        status, erro = a.pedir("POST", "/api/clientes", a.formulario("Sem E-mail Válido",
                                                                     email="nao-e-email"))
        self.assertEqual(status, 400)
        self.assertIn("email", erro["erro"])
        status, erro = a.pedir("POST", "/api/clientes", a.formulario("   "))
        self.assertEqual(status, 400)
        self.assertIn("erro", erro)

        # Cada empresa só vê os próprios clientes, inclusive na busca.
        self.assertEqual(self.nomes(a), ["João Exemplo", "Maria Fictícia"])
        self.assertEqual(self.nomes(b), ["MARIA da Oficina"])
        self.assertEqual(self.nomes(a, "maria"), ["Maria Fictícia"])
        self.assertEqual(self.nomes(b, "maria"), ["MARIA da Oficina"])
        self.assertEqual(self.nomes(a, "OFICINA"), [])
        self.assertEqual(self.nomes(a, "zzz"), [])

        # B não abre, não edita e não exclui cliente de A (404, como se não existisse).
        caminho_maria_a = "/api/clientes/" + maria_a["id"]
        self.assertEqual(b.pedir("GET", caminho_maria_a)[0], 404)
        self.assertEqual(b.pedir("PUT", caminho_maria_a, b.formulario("Invadido"))[0], 404)
        self.assertEqual(b.pedir("DELETE", caminho_maria_a)[0], 404)
        status, intacto = a.pedir("GET", caminho_maria_a)
        self.assertEqual((status, intacto["nome"]), (200, "Maria Fictícia"))

        # Editar: o formulário carrega o cliente (GET) e manda tudo de volta (PUT).
        status, carregado = a.pedir("GET", caminho_maria_a)
        self.assertEqual(status, 200)
        status, editado = a.pedir("PUT", caminho_maria_a, a.formulario(
            "Maria Fictícia Souza", "maria@exemplo.test", "", carregado["observacoes"] or "",
            "inativo"))
        self.assertEqual(status, 200)
        self.assertEqual((editado["nome"], editado["email"], editado["telefone"],
                          editado["status"]),
                         ("Maria Fictícia Souza", "maria@exemplo.test", None, "inativo"))
        # Apagar o e-mail no formulário (campo vazio) limpa o valor.
        status, editado = a.pedir("PUT", caminho_maria_a,
                                  a.formulario("Maria Fictícia Souza", status="ativo"))
        self.assertEqual((status, editado["email"], editado["status"]), (200, None, "ativo"))
        self.assertEqual(self.nomes(b), ["MARIA da Oficina"])

        # Excluir.
        status, corpo = a.pedir("DELETE", "/api/clientes/" + joao_a["id"])
        self.assertEqual((status, corpo), (204, b""))
        self.assertEqual(a.pedir("GET", "/api/clientes/" + joao_a["id"])[0], 404)
        self.assertEqual(self.nomes(a), ["Maria Fictícia Souza"])
        self.assertEqual(self.nomes(b), ["MARIA da Oficina"])

        # Sair: o token antigo passa a receber 401; a outra empresa segue logada.
        status, corpo, token_antigo = a.sair()
        self.assertEqual((status, corpo), (204, b""))
        a.token = token_antigo
        status, erro = a.listar()
        self.assertEqual(status, 401)
        self.assertIn("erro", erro)
        a.token = None
        self.assertEqual(a.listar()[0], 401)
        self.assertEqual(self.nomes(b), ["MARIA da Oficina"])

        # Entrar de novo mostra os dados de A preservados.
        self.assertEqual(a.entrar(EMAIL_A, SENHA_A)[0], 200)
        self.assertEqual(self.nomes(a), ["Maria Fictícia Souza"])
        self.assertEqual(b.sair()[0], 204)


def _padroes_gitignore():
    linhas = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    padroes = [linha.strip() for linha in linhas]
    return [p for p in padroes if p and not p.startswith("#")]


def _ignorado(relativo, padroes):
    """Implementação mínima das regras usadas no .gitignore (nome, *.ext e pasta/)."""
    partes = relativo.parts
    for padrao in padroes:
        if padrao.endswith("/"):
            if padrao.rstrip("/") in partes[:-1]:
                return True
        elif any(fnmatch.fnmatch(parte, padrao) for parte in partes):
            return True
    return False


class TestNadaSensivelVersionado(unittest.TestCase):
    SENSIVEIS = (".env", ".carteira_segredo", "banco.db", "carteira.db", "app.sqlite3",
                 ".db/app.sqlite3", "dump.dump")

    def test_gitignore_cobre_arquivos_sensiveis(self):
        padroes = _padroes_gitignore()
        for nome in self.SENSIVEIS:
            with self.subTest(arquivo=nome):
                self.assertTrue(_ignorado(Path(nome), padroes))
        for nome in (".env.example", "README.md", "run.py", "static/app.js"):
            with self.subTest(arquivo=nome):
                self.assertFalse(_ignorado(Path(nome), padroes))

    def test_bancos_e_segredos_existentes_estao_ignorados(self):
        padroes = _padroes_gitignore()
        for caminho in RAIZ.rglob("*"):
            relativo = caminho.relative_to(RAIZ)
            if ".git" in relativo.parts or not caminho.is_file():
                continue
            sensivel = (caminho.suffix in (".db", ".sqlite", ".sqlite3", ".dump")
                        or caminho.name in (".env", ".carteira_segredo"))
            if sensivel:
                with self.subTest(arquivo=str(relativo)):
                    self.assertTrue(_ignorado(relativo, padroes),
                                    f"{relativo} seria versionado")

    def test_env_example_sem_valores_secretos(self):
        for linha in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
            nome, _, valor = linha.partition("=")
            if any(p in nome.upper() for p in ("PASSWORD", "SENHA", "SEGREDO", "SECRET",
                                               "TOKEN", "DATABASE_URL")):
                with self.subTest(variavel=nome):
                    self.assertEqual(valor.strip(), "")


if __name__ == "__main__":
    unittest.main()
