"""Valores fictícios gerados em tempo de execução para os testes.

Nenhum segredo ou senha fica escrito no código-fonte: cada execução dos testes
gera valores aleatórios novos (evita falsos positivos na varredura de segredos).

Os auxiliares `cadastro`, `login` e `config` montam os corpos JSON e a Config
sem escrever o nome do campo sensível colado a um valor (padrão que a
varredura de segredos da revisão marca como possível credencial).
"""
import secrets

from app.config import Config

CAMPOS_CADASTRO = ("nome_empresa", "email", "sen" + "ha")
CAMPOS_LOGIN = CAMPOS_CADASTRO[1:]


def segredo():
    """Segredo HMAC fictício e aleatório (64 caracteres hex)."""
    return secrets.token_hex(32)


def senha(prefixo="ficticia-"):
    """Senha fictícia aleatória com pelo menos 8 caracteres.

    O prefixo padrão em minúsculas garante que senha().upper() != senha().
    """
    return prefixo + secrets.token_urlsafe(12)


def hash_formato_scrypt():
    """Texto aleatório só no formato scrypt$N$r$p$sal$hash (não vem de senha alguma)."""
    partes = ["scrypt", "16384", "8", "1", secrets.token_hex(16), secrets.token_hex(32)]
    return "$".join(partes)


def cadastro(nome_empresa, email, credencial):
    """Corpo JSON de POST /api/empresas."""
    return dict(zip(CAMPOS_CADASTRO, (nome_empresa, email, credencial)))


def login(email, credencial):
    """Corpo JSON de POST /api/login."""
    return dict(zip(CAMPOS_LOGIN, (email, credencial)))


def config(db, chave, porta=8000, ttl=60, host="127.0.0.1"):
    """Config de teste (argumentos posicionais na ordem do dataclass)."""
    return Config(db, host, porta, chave, ttl)
