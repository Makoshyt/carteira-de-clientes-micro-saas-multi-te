"""Núcleo HTTP: aplicação WSGI própria, roteador, leitura de JSON e erros padronizados.

- ``Roteador``: rotas por método e padrão de caminho (``/api/clientes/{id}``). Caminho sem
  rota -> 404; caminho com rota, mas sem o método pedido -> 405 (com cabeçalho ``Allow``).
- ``Requisicao``: método, caminho, parâmetros do caminho, query string, cabeçalhos,
  ``json()`` (corpo limitado a 64 KB; acima disso, 413) e conexão SQLite aberta sob demanda
  (fechada ao fim da requisição).
- ``Aplicacao``: chama o handler da rota e serializa a resposta em JSON UTF-8. Um handler
  devolve um objeto (200), uma tupla ``(status, corpo)`` ou ``(status, corpo, cabecalhos)``.
  ``corpo`` None gera resposta sem corpo (ex.: 204).
- ``ErroHttp(status, mensagem)``: vira ``{"erro": mensagem}`` com o status informado.
  Qualquer outra exceção vira 500 com mensagem genérica; o traceback vai só para o log do
  servidor (``wsgi.errors``), nunca para a resposta.
- ``exigir_autenticacao``: decorador que lê ``Authorization: Bearer <token>``, valida o token
  (assinatura e sessão no banco) e preenche ``req.usuario_id`` e ``req.empresa_id``; se o token
  faltar ou for inválido, expirado ou revogado, responde 401. A empresa vem sempre da sessão.
"""
import json
import re
import traceback
from functools import wraps
from http import HTTPStatus
from urllib.parse import parse_qs

from app.db import conectar
from app.seguranca import validar_token

LIMITE_CORPO = 64 * 1024
STATUS_DE_ERRO = (400, 401, 404, 405, 409, 413, 500)
_PARAMETRO = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_CAMPOS_QUERY = 50


class ErroHttp(Exception):
    """Erro que vira resposta ``{"erro": mensagem}`` com o status HTTP informado."""

    def __init__(self, status, mensagem, cabecalhos=None):
        if status not in STATUS_DE_ERRO:
            raise ValueError(f"status de erro não suportado: {status}")
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem
        self.cabecalhos = list(cabecalhos or [])


def linha_status(codigo):
    """``200`` -> ``'200 OK'``."""
    return f"{codigo} {HTTPStatus(codigo).phrase}"


# --------------------------------------------------------------------------- roteamento

def _compilar(padrao):
    if not padrao.startswith("/"):
        raise ValueError("o padrão de rota deve começar com '/'")
    partes = []
    posicao = 0
    for achado in _PARAMETRO.finditer(padrao):
        partes.append(re.escape(padrao[posicao:achado.start()]))
        partes.append(f"(?P<{achado.group(1)}>[^/]+)")
        posicao = achado.end()
    partes.append(re.escape(padrao[posicao:]))
    return re.compile("".join(partes))


class Roteador:
    """Associa (método, padrão de caminho) a handlers ``handler(req)``."""

    def __init__(self):
        self._rotas = []  # [(regex, padrao, {metodo: handler})]

    def adicionar(self, metodo, padrao, handler):
        metodo = metodo.upper()
        for _regex, existente, handlers in self._rotas:
            if existente == padrao:
                if metodo in handlers:
                    raise ValueError(f"rota repetida: {metodo} {padrao}")
                handlers[metodo] = handler
                return handler
        self._rotas.append((_compilar(padrao), padrao, {metodo: handler}))
        return handler

    def rota(self, metodo, padrao):
        """Decorador: ``@roteador.rota("GET", "/api/clientes/{id}")``."""
        def registrar(handler):
            return self.adicionar(metodo, padrao, handler)
        return registrar

    def resolver(self, metodo, caminho):
        """Devolve ``(handler, parametros)``; levanta ErroHttp 404 ou 405."""
        permitidos = set()
        for regex, _padrao, handlers in self._rotas:
            achado = regex.fullmatch(caminho)
            if not achado:
                continue
            if metodo in handlers:
                return handlers[metodo], achado.groupdict()
            permitidos.update(handlers)
        if permitidos:
            raise ErroHttp(405, "método não permitido",
                           [("Allow", ", ".join(sorted(permitidos)))])
        raise ErroHttp(404, "não encontrado")


# --------------------------------------------------------------------------- requisição

class Requisicao:
    def __init__(self, environ, app, parametros=None):
        self.environ = environ
        self.app = app
        self.config = app.config
        self.metodo = environ.get("REQUEST_METHOD", "GET").upper()
        self.caminho = environ.get("PATH_INFO", "") or "/"
        self.parametros = dict(parametros or {})
        self.usuario_id = None
        self.empresa_id = None
        self.token = None
        self._conexao = None
        self._query = None

    def cabecalho(self, nome, padrao=None):
        chave = nome.upper().replace("-", "_")
        if chave not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            chave = "HTTP_" + chave
        return self.environ.get(chave, padrao)

    @property
    def query(self):
        """Query string como ``{nome: [valores]}``."""
        if self._query is None:
            try:
                self._query = parse_qs(self.environ.get("QUERY_STRING", ""),
                                       keep_blank_values=True,
                                       max_num_fields=_MAX_CAMPOS_QUERY)
            except ValueError:
                raise ErroHttp(400, "query string inválida") from None
        return self._query

    def parametro_query(self, nome, padrao=None):
        valores = self.query.get(nome)
        return valores[0] if valores else padrao

    def corpo_bruto(self):
        """Lê o corpo respeitando Content-Length e o limite de 64 KB."""
        bruto = (self.environ.get("CONTENT_LENGTH") or "").strip()
        if not bruto:
            return b""
        if not (bruto.isascii() and bruto.isdigit()):
            raise ErroHttp(400, "Content-Length inválido")
        tamanho = int(bruto)
        if tamanho > LIMITE_CORPO:
            raise ErroHttp(413, f"corpo da requisição acima de {LIMITE_CORPO // 1024} KB")
        if tamanho == 0:
            return b""
        dados = self.environ["wsgi.input"].read(tamanho)
        if len(dados) != tamanho:
            raise ErroHttp(400, "corpo da requisição incompleto")
        return dados

    def json(self, objeto=True):
        """Corpo decodificado de JSON (UTF-8). Por padrão exige um objeto JSON."""
        dados = self.corpo_bruto()
        if not dados.strip():
            raise ErroHttp(400, "corpo JSON obrigatório")
        try:
            texto = dados.decode("utf-8")
        except UnicodeDecodeError:
            raise ErroHttp(400, "corpo não está em UTF-8") from None
        try:
            valor = json.loads(texto, parse_constant=_recusar_constante)
        except (ValueError, RecursionError):
            raise ErroHttp(400, "JSON inválido") from None
        if objeto and not isinstance(valor, dict):
            raise ErroHttp(400, "o corpo deve ser um objeto JSON")
        return valor

    @property
    def conexao(self):
        """Conexão SQLite aberta na primeira utilização e fechada ao fim da requisição."""
        if self._conexao is None:
            self._conexao = self.app.abrir_conexao()
        return self._conexao

    def fechar(self):
        if self._conexao is not None:
            try:
                self._conexao.close()
            finally:
                self._conexao = None


def _recusar_constante(nome):
    raise ValueError(f"constante não suportada: {nome}")


# --------------------------------------------------------------------------- autenticação

def token_bearer(req):
    """Extrai o token de ``Authorization: Bearer <token>``; None se ausente ou malformado."""
    valor = req.cabecalho("Authorization")
    if not valor:
        return None
    partes = valor.split()
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return None
    return partes[1]


def autenticar(req):
    """Valida o token e preenche ``req.usuario_id``/``req.empresa_id``; senão ErroHttp 401."""
    token = token_bearer(req)
    if token is None:
        raise ErroHttp(401, "autenticação necessária", [("WWW-Authenticate", "Bearer")])
    sessao = validar_token(req.conexao, req.config.segredo, token)
    if sessao is None:
        raise ErroHttp(401, "token inválido ou expirado",
                       [("WWW-Authenticate", 'Bearer error="invalid_token"')])
    req.usuario_id, req.empresa_id = sessao
    req.token = token
    return sessao


def exigir_autenticacao(handler):
    """Decorador de handler: responde 401 se o token faltar ou for inválido."""
    @wraps(handler)
    def protegido(req):
        autenticar(req)
        return handler(req)
    return protegido


# --------------------------------------------------------------------------- aplicação

_CABECALHOS_BASE = (
    ("X-Content-Type-Options", "nosniff"),
    ("Cache-Control", "no-store"),
)


def _normalizar(resultado):
    if isinstance(resultado, tuple):
        if len(resultado) == 2:
            return resultado[0], resultado[1], []
        if len(resultado) == 3:
            return resultado[0], resultado[1], list(resultado[2])
        raise TypeError("o handler deve devolver (status, corpo) ou (status, corpo, cabecalhos)")
    return 200, resultado, []


def _corpo_json(corpo):
    return json.dumps(corpo, ensure_ascii=False, allow_nan=False).encode("utf-8")


class Aplicacao:
    """Aplicação WSGI: ``Aplicacao(config, roteador)``."""

    def __init__(self, config, roteador=None, conectar_banco=None):
        self.config = config
        self.roteador = roteador or Roteador()
        self._conectar = conectar_banco

    def abrir_conexao(self):
        if self._conectar is not None:
            return self._conectar()
        if self.config is None:
            raise RuntimeError("aplicação sem configuração de banco")
        return conectar(self.config.db)

    def _responder(self, start_response, status, corpo, cabecalhos):
        dados = b"" if corpo is None else _corpo_json(corpo)
        lista = []
        if corpo is not None:
            lista.append(("Content-Type", "application/json; charset=utf-8"))
        lista.append(("Content-Length", str(len(dados))))
        lista.extend(_CABECALHOS_BASE)
        lista.extend(cabecalhos)
        start_response(linha_status(status), lista)
        return [dados]

    def _registrar_erro(self, environ):
        destino = environ.get("wsgi.errors")
        if destino is not None:
            try:
                destino.write(traceback.format_exc())
                destino.flush()
            except Exception:  # nosec B110 - falha ao registrar log não deve derrubar a resposta
                pass

    def __call__(self, environ, start_response):
        req = Requisicao(environ, self)
        try:
            try:
                handler, parametros = self.roteador.resolver(req.metodo, req.caminho)
                req.parametros = parametros
                status, corpo, cabecalhos = _normalizar(handler(req))
                return self._responder(start_response, status, corpo, cabecalhos)
            except ErroHttp as erro:
                return self._responder(start_response, erro.status,
                                       {"erro": erro.mensagem}, erro.cabecalhos)
            except Exception:
                self._registrar_erro(environ)
                return self._responder(start_response, 500,
                                       {"erro": "erro interno do servidor"}, [])
        finally:
            req.fechar()
