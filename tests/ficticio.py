"""Valores fictícios gerados em tempo de execução para os testes.

Nenhum segredo ou senha fica escrito no código-fonte: cada execução dos testes
gera valores aleatórios novos (evita falsos positivos na varredura de segredos).
"""
import secrets


def segredo():
    """Segredo HMAC fictício e aleatório (64 caracteres hex)."""
    return secrets.token_hex(32)


def senha(prefixo="ficticia-"):
    """Senha fictícia aleatória com pelo menos 8 caracteres.

    O prefixo padrão em minúsculas garante que senha().upper() != senha().
    """
    return prefixo + secrets.token_urlsafe(12)
