"""Rotas HTTP de clientes (todas autenticadas).

Coleção:
- GET /api/clientes[?busca=texto]: 200 com a lista JSON dos clientes da empresa da
  sessão, ordenada por nome (no máximo ``clientes.LIMITE_LISTAGEM``). ``busca`` filtra
  por nome sem diferenciar maiúsculas de minúsculas; vazia ou ausente lista tudo.
- POST /api/clientes: valida o corpo (``clientes.validar_cliente``) e grava o cliente
  com o ``empresa_id`` da sessão; devolve 201 com o cliente criado (inclui ``id``,
  ``criado_em`` e ``atualizado_em``) e o cabeçalho ``Location``.

Item:
- GET /api/clientes/{id}: 200 com o cliente.
- PUT /api/clientes/{id}: atualização parcial validada (só os campos enviados);
  atualiza ``atualizado_em`` e devolve 200 com o cliente atualizado.
- DELETE /api/clientes/{id}: 204 sem corpo.

Um id inexistente ou de outra empresa devolve sempre a mesma resposta 404
(``{"erro": "cliente não encontrado"}``), para não revelar que o registro existe.
No PUT o corpo é validado antes da busca do registro, então um corpo inválido gera
400 independentemente de o id existir (também não revela nada).

O ``empresa_id`` vem sempre de ``req.empresa_id`` (preenchido pela sessão). Qualquer
``empresa_id`` (ou ``id``) enviado no corpo nunca é usado: o validador recusa o campo
com 400, então não há como gravar ou mover um cliente para outra empresa.
"""
from app import clientes
from app.web import ErroHttp, exigir_autenticacao

ID_MAX = 64
MENSAGEM_NAO_ENCONTRADO = "cliente não encontrado"


def _nao_encontrado():
    return ErroHttp(404, MENSAGEM_NAO_ENCONTRADO)


def _id_do_caminho(req):
    """Id do caminho; ids absurdamente longos são tratados como inexistentes (404)."""
    cliente_id = req.parametros.get("id") or ""
    if not cliente_id or len(cliente_id) > ID_MAX:
        raise _nao_encontrado()
    return cliente_id


@exigir_autenticacao
def listar_clientes(req):
    """GET /api/clientes: clientes da empresa da sessão, com busca opcional por nome."""
    busca = req.parametro_query("busca")
    return clientes.listar(req.conexao, req.empresa_id, busca)


@exigir_autenticacao
def criar_cliente(req):
    """POST /api/clientes: cria o cliente na empresa da sessão; 201 com o cliente."""
    dados = req.json()
    cliente = clientes.criar(req.conexao, req.empresa_id, dados)
    return 201, cliente, [("Location", f"/api/clientes/{cliente['id']}")]


@exigir_autenticacao
def obter_cliente(req):
    """GET /api/clientes/{id}: o cliente da empresa da sessão, ou 404."""
    cliente_id = _id_do_caminho(req)
    cliente = clientes.obter(req.conexao, req.empresa_id, cliente_id)
    if cliente is None:
        raise _nao_encontrado()
    return cliente


@exigir_autenticacao
def atualizar_cliente(req):
    """PUT /api/clientes/{id}: atualização parcial validada; 200 com o cliente, ou 404."""
    cliente_id = _id_do_caminho(req)
    dados = req.json()
    cliente = clientes.atualizar(req.conexao, req.empresa_id, cliente_id, dados)
    if cliente is None:
        raise _nao_encontrado()
    return cliente


@exigir_autenticacao
def excluir_cliente(req):
    """DELETE /api/clientes/{id}: 204 se apagou, ou 404."""
    cliente_id = _id_do_caminho(req)
    if not clientes.excluir(req.conexao, req.empresa_id, cliente_id):
        raise _nao_encontrado()
    return 204, None
