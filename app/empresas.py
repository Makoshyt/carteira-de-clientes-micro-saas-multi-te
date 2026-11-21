"""Cadastro de empresa com o primeiro usuário: POST /api/empresas.

Corpo: ``{"nome_empresa": str, "email": str, "senha": str}``.

Validação (erro 400 com ``{"erro": mensagem}``):
- nome_empresa: texto obrigatório, 1 a 120 caracteres depois de remover espaços das pontas;
- email: formato básico ``local@dominio.tld``, até 254 caracteres, sem espaços nem
  caracteres de controle; é normalizado (espaços das pontas removidos e minúsculas);
- senha: texto com 8 a 128 caracteres (não é alterada nem aparada).

A empresa e o usuário são gravados numa única transação. A senha é guardada só como
hash scrypt (app/seguranca.gerar_hash). E-mail já cadastrado -> 409. Campos extras
no corpo são ignorados (ids nunca vêm do cliente).
Resposta 201: ``{"empresa_id", "usuario_id", "email"}``, sem hash nem senha.
"""
import re
import sqlite3
import uuid

from app.db import agora_iso, consulta_sql
from app.seguranca import gerar_hash
from app.web import ErroHttp

NOME_EMPRESA_MAX = 120
EMAIL_MAX = 254
SENHA_MIN = 8
SENHA_MAX = 128

# Formato básico: algo@algo.algo, sem espaços, sem '@' extra e sem caracteres de controle.
_EMAIL = re.compile(r"[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f.]+(?:\.[^@\s\x00-\x1f\x7f.]+)+")


def validar_nome_empresa(valor):
    if valor is None:
        raise ErroHttp(400, "nome_empresa é obrigatório")
    if not isinstance(valor, str):
        raise ErroHttp(400, "nome_empresa deve ser texto")
    nome = valor.strip()
    if not nome:
        raise ErroHttp(400, "nome_empresa é obrigatório")
    if len(nome) > NOME_EMPRESA_MAX:
        raise ErroHttp(400, f"nome_empresa deve ter no máximo {NOME_EMPRESA_MAX} caracteres")
    if any(ord(c) < 32 or ord(c) == 127 for c in nome):
        raise ErroHttp(400, "nome_empresa contém caracteres inválidos")
    return nome


def validar_email(valor):
    """Devolve o e-mail normalizado (sem espaços nas pontas, em minúsculas)."""
    if valor is None:
        raise ErroHttp(400, "email é obrigatório")
    if not isinstance(valor, str):
        raise ErroHttp(400, "email deve ser texto")
    email = valor.strip().lower()
    if not email:
        raise ErroHttp(400, "email é obrigatório")
    if len(email) > EMAIL_MAX:
        raise ErroHttp(400, f"email deve ter no máximo {EMAIL_MAX} caracteres")
    if not _EMAIL.fullmatch(email):
        raise ErroHttp(400, "email em formato inválido")
    return email


def validar_senha(valor):
    if valor is None:
        raise ErroHttp(400, "senha é obrigatória")
    if not isinstance(valor, str):
        raise ErroHttp(400, "senha deve ser texto")
    if len(valor) < SENHA_MIN:
        raise ErroHttp(400, f"senha deve ter pelo menos {SENHA_MIN} caracteres")
    if len(valor) > SENHA_MAX:
        raise ErroHttp(400, f"senha deve ter no máximo {SENHA_MAX} caracteres")
    return valor


def _email_existe(conexao, email):
    return conexao.execute(consulta_sql("SELECT 1 FROM usuarios WHERE email = ?"),
                           (email,)).fetchone() is not None


def cadastrar_empresa(req):
    """POST /api/empresas: cria empresa e primeiro usuário numa transação."""
    dados = req.json()
    nome = validar_nome_empresa(dados.get("nome_empresa"))
    email = validar_email(dados.get("email"))
    senha = validar_senha(dados.get("senha"))

    conexao = req.conexao
    if _email_existe(conexao, email):
        raise ErroHttp(409, "e-mail já cadastrado")

    senha_hash = gerar_hash(senha)  # fora da transação: scrypt é deliberadamente lento
    empresa_id = str(uuid.uuid4())
    usuario_id = str(uuid.uuid4())
    agora = agora_iso()
    try:
        with conexao:  # commit se tudo der certo; rollback de ambos os INSERTs se algo falhar
            conexao.execute(
                consulta_sql("INSERT INTO empresas (id, nome, criado_em) VALUES (?, ?, ?)"),
                (empresa_id, nome, agora))
            conexao.execute(
                consulta_sql("INSERT INTO usuarios (id, empresa_id, email, senha_hash, criado_em) "
                             "VALUES (?, ?, ?, ?, ?)"),
                (usuario_id, empresa_id, email, senha_hash, agora))
    except sqlite3.IntegrityError:
        # Corrida: outro cadastro gravou o mesmo e-mail entre a checagem e o INSERT.
        if _email_existe(conexao, email):
            raise ErroHttp(409, "e-mail já cadastrado") from None
        raise
    return 201, {"empresa_id": empresa_id, "usuario_id": usuario_id, "email": email}
