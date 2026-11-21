"""Aplicação WSGI mínima (as rotas da API serão adicionadas nas próximas tarefas)."""
import json


def resposta_json(start_response, status, corpo):
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(dados))),
        ("X-Content-Type-Options", "nosniff"),
    ])
    return [dados]


def criar_app(config):
    """Cria a aplicação WSGI ligada à configuração informada."""

    def app(environ, start_response):
        caminho = environ.get("PATH_INFO", "/")
        metodo = environ.get("REQUEST_METHOD", "GET")
        if caminho == "/api/saude":
            if metodo != "GET":
                return resposta_json(start_response, "405 Method Not Allowed",
                                     {"erro": "método não permitido"})
            return resposta_json(start_response, "200 OK", {"status": "ok"})
        return resposta_json(start_response, "404 Not Found", {"erro": "não encontrado"})

    app.config = config
    return app
