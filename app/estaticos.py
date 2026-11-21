"""Arquivos estáticos do frontend: GET / (index.html) e GET /static/<caminho>.

Proteções contra path traversal: o caminho pedido é recusado com 404 se estiver vazio,
for absoluto, tiver segmento vazio, ``.`` ou ``..``, arquivo oculto (``.x``), barra
invertida, ``:`` ou byte nulo. Depois disso o caminho resolvido (com links simbólicos)
ainda precisa estar dentro da pasta ``static/`` e ser um arquivo regular com extensão
conhecida. Qualquer falha responde 404, sem revelar o motivo.
"""
from pathlib import Path

from app.web import ErroHttp, RespostaBruta

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "static"

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

_PROIBIDOS = ("\x00", "\\", ":")


def _nao_encontrado():
    return ErroHttp(404, "não encontrado")


def resolver_arquivo(pasta, relativo):
    """Devolve o Path do arquivo dentro de ``pasta`` ou levanta ErroHttp 404."""
    if not relativo or relativo.startswith("/") or any(c in relativo for c in _PROIBIDOS):
        raise _nao_encontrado()
    for parte in relativo.split("/"):
        if not parte or parte.startswith("."):
            raise _nao_encontrado()
    base = Path(pasta).resolve()
    try:
        alvo = (base / relativo).resolve()
    except (OSError, RuntimeError, ValueError):
        raise _nao_encontrado() from None
    if not alvo.is_relative_to(base) or alvo == base:
        raise _nao_encontrado()
    if alvo.suffix.lower() not in TIPOS or not alvo.is_file():
        raise _nao_encontrado()
    return alvo


def servir_arquivo(pasta, relativo):
    alvo = resolver_arquivo(pasta, relativo)
    try:
        dados = alvo.read_bytes()
    except OSError:
        raise _nao_encontrado() from None
    return RespostaBruta(dados, TIPOS[alvo.suffix.lower()])


def criar_handlers(pasta=None):
    """Devolve ``(pagina_inicial, arquivo_estatico)`` ligados à pasta informada."""
    pasta = Path(pasta) if pasta is not None else PASTA_PADRAO

    def pagina_inicial(req):
        return servir_arquivo(pasta, "index.html")

    def arquivo_estatico(req):
        return servir_arquivo(pasta, req.parametros.get("caminho", ""))

    return pagina_inicial, arquivo_estatico
