"""Segurança: hash de senhas com hashlib.scrypt e tokens assinados de sessão.

Senhas — formato gravado: ``scrypt$n$r$p$sal_hex$hash_hex``. Os parâmetros ficam no
próprio valor, então hashes antigos continuam verificáveis se os padrões mudarem.

Tokens — formato ``<sessao_id>.<assinatura>``, em que a assinatura é
HMAC-SHA256(segredo, sessao_id) em base64url sem ``=``. O token só referencia uma
linha da tabela ``sessoes`` (que guarda usuário, empresa e expiração); logout apaga
a linha, invalidando o token mesmo que a assinatura continue correta.
"""

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

PREFIXO = "scrypt"
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 64
TAMANHO_SAL = 16

# Limites aceitos ao verificar um valor armazenado: evitam que um valor corrompido
# ou adulterado no banco provoque consumo excessivo de memória/CPU.
_N_MAX = 2 ** 20
_R_MAX = 32
_P_MAX = 16
_DKLEN_MIN = 16
_DKLEN_MAX = 128
_SAL_MIN = 8
_SAL_MAX = 64
_MAXMEM = 256 * 1024 * 1024
_HEX = re.compile(r"(?:[0-9a-f]{2})+")


def _scrypt(senha, sal, n, r, p, dklen):
    # maxmem explícito: o padrão do OpenSSL (32 MiB) pode ser pequeno demais para n/r maiores.
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=n, r=r, p=p,
                          maxmem=_MAXMEM, dklen=dklen)


def _validar_senha(senha):
    if not isinstance(senha, str):
        raise TypeError("a senha deve ser str")


def gerar_hash(senha):
    """Devolve ``scrypt$n$r$p$sal_hex$hash_hex`` com sal aleatório de 16 bytes."""
    _validar_senha(senha)
    sal = secrets.token_bytes(TAMANHO_SAL)
    derivado = _scrypt(senha, sal, SCRYPT_N, SCRYPT_R, SCRYPT_P, DKLEN)
    return "$".join((PREFIXO, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
                     sal.hex(), derivado.hex()))


def _inteiro(texto):
    # Só dígitos ASCII: recusa sinais, espaços e dígitos Unicode que int() aceitaria.
    if not texto or not texto.isascii() or not texto.isdigit():
        raise ValueError
    return int(texto)


def _decodificar(armazenado):
    partes = armazenado.split("$")
    if len(partes) != 6 or partes[0] != PREFIXO:
        raise ValueError
    n, r, p = (_inteiro(x) for x in partes[1:4])
    if not all(_HEX.fullmatch(x) for x in partes[4:6]):
        raise ValueError
    sal = bytes.fromhex(partes[4])
    esperado = bytes.fromhex(partes[5])
    if not (2 <= n <= _N_MAX and n & (n - 1) == 0):
        raise ValueError
    if not (1 <= r <= _R_MAX and 1 <= p <= _P_MAX):
        raise ValueError
    if 128 * r * n > _MAXMEM // 2:
        raise ValueError
    if not (_SAL_MIN <= len(sal) <= _SAL_MAX and _DKLEN_MIN <= len(esperado) <= _DKLEN_MAX):
        raise ValueError
    return n, r, p, sal, esperado


def verificar_senha(senha, armazenado):
    """True se ``senha`` corresponde ao hash ``armazenado``; False caso contrário.

    Valores armazenados malformados (ou tipos inválidos) resultam em False, nunca em exceção.
    A comparação final usa hmac.compare_digest (tempo constante).
    """
    if not isinstance(senha, str) or not isinstance(armazenado, str):
        return False
    try:
        n, r, p, sal, esperado = _decodificar(armazenado)
        calculado = _scrypt(senha, sal, n, r, p, len(esperado))
    except (ValueError, UnicodeEncodeError, MemoryError):
        return False
    return hmac.compare_digest(calculado, esperado)


# --------------------------------------------------------------------------- tokens

FORMATO_DATA = "%Y-%m-%dT%H:%M:%SZ"  # mesmo formato ISO-8601 UTC de app/db.agora_iso
TAMANHO_ID_SESSAO = 32               # bytes aleatórios (secrets.token_urlsafe) -> 43 caracteres
TAMANHO_MAXIMO_TOKEN = 256
_ID_SESSAO = re.compile(r"[A-Za-z0-9_-]{16,128}")
_ASSINATURA = re.compile(r"[A-Za-z0-9_-]{43}")  # 32 bytes do SHA-256 em base64url sem '='


def _bytes_segredo(segredo):
    if isinstance(segredo, str):
        segredo = segredo.encode("utf-8")
    if not isinstance(segredo, (bytes, bytearray)) or not segredo:
        raise ValueError("segredo HMAC ausente ou inválido")
    return bytes(segredo)


def _agora(agora):
    return datetime.now(timezone.utc) if agora is None else agora


def _formatar(momento):
    return momento.astimezone(timezone.utc).strftime(FORMATO_DATA)


def assinar(segredo, sessao_id):
    """HMAC-SHA256(segredo, sessao_id) em base64url sem preenchimento."""
    digest = hmac.new(_bytes_segredo(segredo), sessao_id.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def gerar_token(segredo, sessao_id):
    """Monta ``<sessao_id>.<assinatura>``."""
    if not isinstance(sessao_id, str) or not _ID_SESSAO.fullmatch(sessao_id):
        raise ValueError("id de sessão inválido")
    return f"{sessao_id}.{assinar(segredo, sessao_id)}"


def sessao_do_token(segredo, token):
    """Devolve o sessao_id se o formato e a assinatura do token conferem; senão None.

    Não consulta o banco. A assinatura é comparada com hmac.compare_digest.
    """
    if not isinstance(token, str) or not 0 < len(token) <= TAMANHO_MAXIMO_TOKEN:
        return None
    partes = token.split(".")
    if len(partes) != 2:
        return None
    sessao_id, assinatura = partes
    if not _ID_SESSAO.fullmatch(sessao_id) or not _ASSINATURA.fullmatch(assinatura):
        return None
    esperada = assinar(segredo, sessao_id)
    if not hmac.compare_digest(esperada.encode("ascii"), assinatura.encode("ascii")):
        return None
    return sessao_id


def criar_sessao(conexao, segredo, usuario_id, empresa_id, ttl, agora=None):
    """Grava uma sessão nova (expira em ``ttl`` segundos) e devolve o token assinado.

    Faz commit da transação da conexão.
    """
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
        raise ValueError("ttl deve ser um inteiro positivo")
    _bytes_segredo(segredo)  # falha antes de gravar se o segredo for inválido
    momento = _agora(agora)
    sessao_id = secrets.token_urlsafe(TAMANHO_ID_SESSAO)
    with conexao:
        conexao.execute(
            "INSERT INTO sessoes (id, usuario_id, empresa_id, expira_em, criado_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (sessao_id, usuario_id, empresa_id,
             _formatar(momento + timedelta(seconds=ttl)), _formatar(momento)))
    return gerar_token(segredo, sessao_id)


def validar_token(conexao, segredo, token, agora=None):
    """Devolve ``(usuario_id, empresa_id)`` da sessão do token, ou None.

    Recusa (None) token malformado, com assinatura errada, de sessão inexistente
    (revogada por logout) ou expirada. A assinatura é conferida antes do banco.
    """
    sessao_id = sessao_do_token(segredo, token)
    if sessao_id is None:
        return None
    linha = conexao.execute(
        "SELECT usuario_id, empresa_id FROM sessoes WHERE id = ? AND expira_em > ?",
        (sessao_id, _formatar(_agora(agora)))).fetchone()
    if linha is None:
        return None
    return (linha[0], linha[1])


def revogar_sessao(conexao, segredo, token):
    """Logout: apaga a sessão do token. Devolve True se uma sessão foi apagada.

    Token com assinatura inválida não apaga nada. Faz commit da transação da conexão.
    """
    sessao_id = sessao_do_token(segredo, token)
    if sessao_id is None:
        return False
    with conexao:
        cursor = conexao.execute("DELETE FROM sessoes WHERE id = ?", (sessao_id,))
    return cursor.rowcount > 0


def limpar_sessoes_expiradas(conexao, agora=None):
    """Apaga as sessões já expiradas e devolve quantas foram apagadas."""
    with conexao:
        cursor = conexao.execute("DELETE FROM sessoes WHERE expira_em <= ?",
                                 (_formatar(_agora(agora)),))
    return cursor.rowcount
