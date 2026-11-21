"""Montagem da aplicação WSGI: registra as rotas da API no roteador de app/web.py.

Rotas atuais: GET /api/saude, POST /api/empresas (app/empresas.py) e
POST /api/login, POST /api/logout, GET /api/me (app/autenticacao.py).
As rotas de clientes entram nas próximas tarefas.
"""
from app.autenticacao import login, logout, me
from app.empresas import cadastrar_empresa
from app.web import Aplicacao, Roteador


def saude(req):
    """GET /api/saude: verificação simples de que o servidor está no ar."""
    return {"status": "ok"}


def criar_roteador():
    roteador = Roteador()
    roteador.adicionar("GET", "/api/saude", saude)
    roteador.adicionar("POST", "/api/empresas", cadastrar_empresa)
    roteador.adicionar("POST", "/api/login", login)
    roteador.adicionar("POST", "/api/logout", logout)
    roteador.adicionar("GET", "/api/me", me)
    return roteador


def criar_app(config):
    """Cria a aplicação WSGI ligada à configuração informada."""
    return Aplicacao(config, criar_roteador())
