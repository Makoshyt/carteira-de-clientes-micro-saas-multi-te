"""Camada de acesso a dados de clientes (repositório), sempre limitada a uma empresa.

Funções (todas recebem a conexão como primeiro argumento):
- ``listar(conexao, empresa_id, busca=None)``: clientes da empresa, ordenados por nome,
  no máximo ``LIMITE_LISTAGEM`` (200). ``busca`` filtra por nome sem diferenciar maiúsculas
  de minúsculas (``LOWER(nome) LIKE LOWER(?)``, com ``%``, ``_`` e ``\\`` escapados).
- ``obter(conexao, empresa_id, id)``: dict do cliente ou None.
- ``criar(conexao, empresa_id, dados)``: valida, grava e devolve o cliente criado.
- ``atualizar(conexao, empresa_id, id, dados)``: atualização parcial (só os campos
  enviados); devolve o cliente atualizado ou None se não existir na empresa.
- ``excluir(conexao, empresa_id, id)``: True se apagou, False se não existia na empresa.

Isolamento multi-tenant: toda query tem ``WHERE empresa_id = ?`` com o ``empresa_id``
recebido (que, na API, vem só da sessão). Um cliente de outra empresa é tratado como
inexistente. Campos desconhecidos em ``dados`` (inclusive ``id`` e ``empresa_id``) são
rejeitados com 400 por ``validar_cliente``: a empresa nunca vem do corpo da requisição.

Todo o SQL é parametrizado, sem montagem dinâmica, e portável para PostgreSQL
(``LOWER``, ``LIKE ... ESCAPE``, ``ORDER BY``, ``LIMIT``).

Validação: erro de entrada levanta ``ErroHttp(400, mensagem)`` citando o campo.
"""
import re
import uuid

from app.db import agora_iso
from app.empresas import EMAIL_MAX, validar_email
from app.web import ErroHttp

LIMITE_LISTAGEM = 200
NOME_MAX = 120
EMAIL_CLIENTE_MAX = EMAIL_MAX  # 254
TELEFONE_MAX = 30
_TELEFONE = re.compile(r"[0-9 +()\-]+")
OBSERVACOES_MAX = 2000
BUSCA_MAX = 200
STATUS_VALIDOS = ("ativo", "inativo")
STATUS_PADRAO = "ativo"
CAMPOS = ("nome", "email", "telefone", "observacoes", "status")

_SQL_LISTAR = (
    "SELECT id, nome, email, telefone, observacoes, status, criado_em, atualizado_em "
    "FROM clientes WHERE empresa_id = ? "
    "ORDER BY LOWER(nome), nome, id LIMIT ?"
)
_SQL_BUSCAR = (
    "SELECT id, nome, email, telefone, observacoes, status, criado_em, atualizado_em "
    "FROM clientes WHERE empresa_id = ? AND LOWER(nome) LIKE LOWER(?) ESCAPE '\\' "
    "ORDER BY LOWER(nome), nome, id LIMIT ?"
)
_SQL_OBTER = (
    "SELECT id, nome, email, telefone, observacoes, status, criado_em, atualizado_em "
    "FROM clientes WHERE empresa_id = ? AND id = ?"
)
_SQL_INSERIR = (
    "INSERT INTO clientes (id, empresa_id, nome, email, telefone, observacoes, status, "
    "criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_SQL_ATUALIZAR = (
    "UPDATE clientes SET nome = ?, email = ?, telefone = ?, observacoes = ?, status = ?, "
    "atualizado_em = ? WHERE empresa_id = ? AND id = ?"
)
_SQL_EXCLUIR = "DELETE FROM clientes WHERE empresa_id = ? AND id = ?"


# --------------------------------------------------------------------------- validação

def _tem_controle(texto, permitir_quebra=False):
    permitidos = {"\n", "\r", "\t"} if permitir_quebra else set()
    return any((ord(c) < 32 or ord(c) == 127) and c not in permitidos for c in texto)


def validar_nome(valor):
    if valor is None:
        raise ErroHttp(400, "nome é obrigatório")
    if not isinstance(valor, str):
        raise ErroHttp(400, "nome deve ser texto")
    nome = valor.strip()
    if not nome:
        raise ErroHttp(400, "nome é obrigatório")
    if len(nome) > NOME_MAX:
        raise ErroHttp(400, f"nome deve ter no máximo {NOME_MAX} caracteres")
    if _tem_controle(nome):
        raise ErroHttp(400, "nome contém caracteres inválidos")
    return nome


def validar_email_cliente(valor):
    """E-mail opcional: None ou texto vazio -> None; senão formato básico validado."""
    if valor is None:
        return None
    if isinstance(valor, str) and not valor.strip():
        return None
    return validar_email(valor)


def _texto_opcional(campo, valor, maximo, permitir_quebra=False):
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErroHttp(400, f"{campo} deve ser texto")
    texto = valor.strip()
    if not texto:
        return None
    if len(texto) > maximo:
        raise ErroHttp(400, f"{campo} deve ter no máximo {maximo} caracteres")
    if _tem_controle(texto, permitir_quebra):
        raise ErroHttp(400, f"{campo} contém caracteres inválidos")
    return texto


def validar_telefone(valor):
    telefone = _texto_opcional("telefone", valor, TELEFONE_MAX)
    if telefone is not None and not _TELEFONE.fullmatch(telefone):
        raise ErroHttp(400, "telefone deve ter só dígitos, espaços e os sinais + ( ) -")
    return telefone


def validar_observacoes(valor):
    return _texto_opcional("observacoes", valor, OBSERVACOES_MAX, permitir_quebra=True)


def validar_status(valor):
    if not isinstance(valor, str) or valor not in STATUS_VALIDOS:
        raise ErroHttp(400, "status deve ser 'ativo' ou 'inativo'")
    return valor


_VALIDADORES = {
    "nome": validar_nome,
    "email": validar_email_cliente,
    "telefone": validar_telefone,
    "observacoes": validar_observacoes,
    "status": validar_status,
}


def validar_cliente(dados, parcial=False):
    """Valida ``dados`` e devolve os campos normalizados.

    Com ``parcial=False`` (criação) ``nome`` é obrigatório e ``status`` assume
    ``'ativo'``. Com ``parcial=True`` (atualização) só os campos presentes são
    validados, e pelo menos um campo é exigido. Campos desconhecidos (ex.:
    ``id``, ``empresa_id``) levantam ``ErroHttp(400)`` citando o campo.
    """
    if not isinstance(dados, dict):
        raise ErroHttp(400, "o corpo deve ser um objeto JSON")
    desconhecidos = sorted(str(c) for c in dados if c not in CAMPOS)
    if desconhecidos:
        raise ErroHttp(400, f"campo não permitido: {', '.join(desconhecidos)}")
    limpos = {}
    for campo in CAMPOS:
        if campo in dados:
            limpos[campo] = _VALIDADORES[campo](dados[campo])
    if not parcial:
        if "nome" not in limpos:
            limpos["nome"] = validar_nome(None)
        limpos.setdefault("status", STATUS_PADRAO)
        for campo in ("email", "telefone", "observacoes"):
            limpos.setdefault(campo, None)
    elif not limpos:
        raise ErroHttp(400, "nenhum campo para atualizar (use nome, email, telefone, "
                            "observacoes ou status)")
    return limpos


validar_dados = validar_cliente  # nome antigo, mantido por compatibilidade


def validar_busca(busca):
    """Devolve o texto de busca aparado ou None (sem filtro)."""
    if busca is None:
        return None
    if not isinstance(busca, str):
        raise ErroHttp(400, "busca deve ser texto")
    texto = busca.strip()
    if not texto:
        return None
    if len(texto) > BUSCA_MAX:
        raise ErroHttp(400, f"busca deve ter no máximo {BUSCA_MAX} caracteres")
    if _tem_controle(texto):
        raise ErroHttp(400, "busca contém caracteres inválidos")
    return texto


def escapar_like(texto):
    """Escapa ``\\``, ``%`` e ``_`` para uso literal em ``LIKE ... ESCAPE '\\'``."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --------------------------------------------------------------------------- repositório

def _para_dict(linha):
    return {
        "id": linha["id"],
        "nome": linha["nome"],
        "email": linha["email"],
        "telefone": linha["telefone"],
        "observacoes": linha["observacoes"],
        "status": linha["status"],
        "criado_em": linha["criado_em"],
        "atualizado_em": linha["atualizado_em"],
    }


def _exigir_empresa(empresa_id):
    # Defesa em profundidade: sem empresa não há consulta (nunca "todas as empresas").
    if not isinstance(empresa_id, str) or not empresa_id:
        raise ValueError("empresa_id obrigatório")


def listar(conexao, empresa_id, busca=None):
    """Clientes da empresa, ordenados por nome, no máximo LIMITE_LISTAGEM."""
    _exigir_empresa(empresa_id)
    termo = validar_busca(busca)
    if termo is None:
        cursor = conexao.execute(_SQL_LISTAR, (empresa_id, LIMITE_LISTAGEM))
    else:
        padrao = f"%{escapar_like(termo)}%"
        cursor = conexao.execute(_SQL_BUSCAR, (empresa_id, padrao, LIMITE_LISTAGEM))
    return [_para_dict(linha) for linha in cursor.fetchall()]


def obter(conexao, empresa_id, cliente_id):
    """Cliente da empresa com esse id, ou None (inclusive se for de outra empresa)."""
    _exigir_empresa(empresa_id)
    if not isinstance(cliente_id, str) or not cliente_id:
        return None
    linha = conexao.execute(_SQL_OBTER, (empresa_id, cliente_id)).fetchone()
    return _para_dict(linha) if linha is not None else None


def criar(conexao, empresa_id, dados):
    """Valida e grava um novo cliente da empresa; devolve o cliente criado."""
    _exigir_empresa(empresa_id)
    limpos = validar_cliente(dados)
    cliente_id = str(uuid.uuid4())
    agora = agora_iso()
    with conexao:
        conexao.execute(_SQL_INSERIR, (
            cliente_id, empresa_id, limpos["nome"], limpos["email"], limpos["telefone"],
            limpos["observacoes"], limpos["status"], agora, agora))
    return obter(conexao, empresa_id, cliente_id)


def atualizar(conexao, empresa_id, cliente_id, dados):
    """Atualiza só os campos enviados; devolve o cliente ou None se não for da empresa."""
    _exigir_empresa(empresa_id)
    limpos = validar_cliente(dados, parcial=True)
    atual = obter(conexao, empresa_id, cliente_id)
    if atual is None:
        return None
    novo = {campo: limpos.get(campo, atual[campo]) for campo in CAMPOS}
    with conexao:
        cursor = conexao.execute(_SQL_ATUALIZAR, (
            novo["nome"], novo["email"], novo["telefone"], novo["observacoes"],
            novo["status"], agora_iso(), empresa_id, cliente_id))
    if cursor.rowcount != 1:
        return None
    return obter(conexao, empresa_id, cliente_id)


def excluir(conexao, empresa_id, cliente_id):
    """Apaga o cliente da empresa; True se apagou, False se não existia nela."""
    _exigir_empresa(empresa_id)
    if not isinstance(cliente_id, str) or not cliente_id:
        return False
    with conexao:
        cursor = conexao.execute(_SQL_EXCLUIR, (empresa_id, cliente_id))
    return cursor.rowcount == 1
