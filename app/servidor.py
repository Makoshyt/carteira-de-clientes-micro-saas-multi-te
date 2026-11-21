"""Montagem da aplicação WSGI: registra as rotas da API no roteador de app/web.py.

As rotas de cadastro, login/logout e clientes entram nas próximas tarefas.
"""
from app.web import Aplicacao, Roteador


def saude(req):
    """GET /api/saude: verificação simples de que o servidor está no ar."""
    return {"status": "ok"}


def criar_roteador():
    roteador = Roteador()
    roteador.adicionar("GET", "/api/saude", saude)
    return roteador


def criar_app(config):
    """Cria a aplicação WSGI ligada à configuração informada."""
    return Aplicacao(config, criar_roteador())
