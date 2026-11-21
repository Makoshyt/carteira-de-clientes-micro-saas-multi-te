"""Rotas HTTP da coleção de clientes: GET e POST /api/clientes (ambas autenticadas).

- GET /api/clientes[?busca=texto]: 200 com a lista JSON dos clientes da empresa da
  sessão, ordenada por nome (no máximo ``clientes.LIMITE_LISTAGEM``). ``busca`` filtra
  por nome sem diferenciar maiúsculas de minúsculas; vazia ou ausente lista tudo.
- POST /api/clientes: valida o corpo (``clientes.validar_cliente``) e grava o cliente
  com o ``empresa_id`` da sessão; devolve 201 com o cliente criado (inclui ``id``,
  ``criado_em`` e ``atualizado_em``) e o cabeçalho ``Location``.

O ``empresa_id`` vem sempre de ``req.empresa_id`` (preenchido pela sessão). Qualquer
``empresa_id`` (ou ``id``) enviado no corpo nunca é usado: o validador recusa o campo
com 400, então não há como gravar um cliente em outra empresa.
"""
from app import clientes
from app.web import exigir_autenticacao


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
