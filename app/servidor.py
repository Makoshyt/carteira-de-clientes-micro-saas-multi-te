"""Montagem da aplicação WSGI: registra as rotas da API no roteador de app/web.py.

Rotas atuais: GET /api/saude e POST /api/empresas (app/empresas.py).
As rotas de login/logout e clientes entram nas próximas tarefas.
"""
from app.empresas import cadastrar_empresa
from app.web import Aplicacao, Roteador


def saude(req):
    """GET /api/saude: verificação simples de que o servidor está no ar."""
    return {"status": "ok"}


def criar_roteador():
    roteador = Roteador()
    roteador.adicionar("GET", "/api/saude", saude)
    roteador.adicionar("POST", "/api/empresas", cadastrar_empresa)
    return roteador


def criar_app(config):
    """Cria a aplicação WSGI ligada à configuração informada."""
    return Aplicacao(config, criar_roteador())
