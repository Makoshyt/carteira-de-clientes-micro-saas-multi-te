"""Montagem da aplicação WSGI: registra as rotas no roteador de app/web.py.

Rotas atuais: GET /api/saude, POST /api/empresas (app/empresas.py),
POST /api/login, POST /api/logout, GET /api/me (app/autenticacao.py),
GET/POST /api/clientes e GET/PUT/DELETE /api/clientes/{id} (app/api_clientes.py) e
os arquivos estáticos GET / e GET /static/<caminho> (app/estaticos.py).
"""
from app.api_clientes import (
    atualizar_cliente,
    criar_cliente,
    excluir_cliente,
    listar_clientes,
    obter_cliente,
)
from app.autenticacao import login, logout, me
from app.empresas import cadastrar_empresa
from app.estaticos import criar_handlers
from app.web import Aplicacao, Roteador


def saude(req):
    """GET /api/saude: verificação simples de que o servidor está no ar."""
    return {"status": "ok"}


def criar_roteador(pasta_estaticos=None):
    roteador = Roteador()
    roteador.adicionar("GET", "/api/saude", saude)
    roteador.adicionar("POST", "/api/empresas", cadastrar_empresa)
    roteador.adicionar("POST", "/api/login", login)
    roteador.adicionar("POST", "/api/logout", logout)
    roteador.adicionar("GET", "/api/me", me)
    roteador.adicionar("GET", "/api/clientes", listar_clientes)
    roteador.adicionar("POST", "/api/clientes", criar_cliente)
    roteador.adicionar("GET", "/api/clientes/{id}", obter_cliente)
    roteador.adicionar("PUT", "/api/clientes/{id}", atualizar_cliente)
    roteador.adicionar("DELETE", "/api/clientes/{id}", excluir_cliente)
    pagina_inicial, arquivo_estatico = criar_handlers(pasta_estaticos)
    roteador.adicionar("GET", "/", pagina_inicial)
    roteador.adicionar("GET", "/static/{caminho:caminho}", arquivo_estatico)
    return roteador


def criar_app(config, pasta_estaticos=None):
    """Cria a aplicação WSGI ligada à configuração (e, opcionalmente, à pasta estática)."""
    return Aplicacao(config, criar_roteador(pasta_estaticos))
