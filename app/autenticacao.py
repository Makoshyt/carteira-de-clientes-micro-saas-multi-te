"""Login, logout e dados do usuário logado: POST /api/login, POST /api/logout, GET /api/me.

- POST /api/login com ``{"email": str, "senha": str}``: 200 com ``{"token", "expira_em"}``
  ou 401 com a mensagem genérica "e-mail ou senha inválidos" (não revela se o erro está
  no e-mail ou na senha). Corpo JSON malformado ou campos que não são texto -> 400.
  Para e-mail inexistente, uma verificação scrypt com hash fictício é feita mesmo assim,
  para o tempo de resposta não denunciar quais e-mails estão cadastrados.
- POST /api/logout (autenticado): apaga a sessão do token e devolve 204 sem corpo; o mesmo
  token passa a receber 401.
- GET /api/me (autenticado): ``{"usuario_id", "email", "empresa_id", "nome_empresa"}``,
  consultado com o usuario_id e o empresa_id da sessão (nunca de dados do cliente).
"""
import secrets
from datetime import datetime, timedelta, timezone

from app.db import consulta_sql
from app.empresas import EMAIL_MAX, SENHA_MAX
from app.seguranca import FORMATO_DATA, criar_sessao, gerar_hash, revogar_sessao, verificar_senha
from app.web import ErroHttp, exigir_autenticacao

MENSAGEM_LOGIN_INVALIDO = "e-mail ou senha inválidos"

_hash_ficticio = None


def _hash_para_comparacao_falsa():
    """Hash scrypt de uma senha aleatória, usado quando o e-mail não existe."""
    global _hash_ficticio
    if _hash_ficticio is None:
        _hash_ficticio = gerar_hash(secrets.token_hex(16))
    return _hash_ficticio


def _texto(dados, campo):
    valor = dados.get(campo)
    if valor is None:
        raise ErroHttp(400, f"{campo} é obrigatório")
    if not isinstance(valor, str):
        raise ErroHttp(400, f"{campo} deve ser texto")
    return valor


def login(req):
    """POST /api/login: valida credenciais e devolve um token assinado."""
    dados = req.json()
    email = _texto(dados, "email").strip().lower()
    senha = _texto(dados, "senha")

    linha = None
    if email and len(email) <= EMAIL_MAX and len(senha) <= SENHA_MAX:
        linha = req.conexao.execute(
            consulta_sql("SELECT id, empresa_id, senha_hash FROM usuarios WHERE email = ?"),
            (email,)).fetchone()
    if linha is None:
        verificar_senha(senha[:SENHA_MAX], _hash_para_comparacao_falsa())
        raise ErroHttp(401, MENSAGEM_LOGIN_INVALIDO)
    if not verificar_senha(senha, linha[2]):
        raise ErroHttp(401, MENSAGEM_LOGIN_INVALIDO)

    ttl = req.config.token_ttl
    agora = datetime.now(timezone.utc)
    token = criar_sessao(req.conexao, req.config.segredo, linha[0], linha[1], ttl, agora=agora)
    expira_em = (agora + timedelta(seconds=ttl)).strftime(FORMATO_DATA)
    return {"token": token, "expira_em": expira_em}


@exigir_autenticacao
def logout(req):
    """POST /api/logout: revoga a sessão do token usado na requisição."""
    revogar_sessao(req.conexao, req.config.segredo, req.token)
    return 204, None


@exigir_autenticacao
def me(req):
    """GET /api/me: dados do usuário e da empresa da sessão."""
    linha = req.conexao.execute(
        consulta_sql("SELECT u.id, u.email, e.id, e.nome FROM usuarios u "
                     "JOIN empresas e ON e.id = u.empresa_id "
                     "WHERE u.id = ? AND u.empresa_id = ?"),
        (req.usuario_id, req.empresa_id)).fetchone()
    if linha is None:
        raise ErroHttp(401, "token inválido ou expirado",
                       [("WWW-Authenticate", 'Bearer error="invalid_token"')])
    return {"usuario_id": linha[0], "email": linha[1],
            "empresa_id": linha[2], "nome_empresa": linha[3]}
