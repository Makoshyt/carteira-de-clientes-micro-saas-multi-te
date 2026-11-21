"""Hash e verificação de senhas com hashlib.scrypt.

Formato gravado: ``scrypt$n$r$p$sal_hex$hash_hex``. Os parâmetros ficam no próprio
valor, então hashes antigos continuam verificáveis se os padrões mudarem no futuro.
"""

import hashlib
import hmac
import re
import secrets

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
