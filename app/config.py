"""Configuração da aplicação lida de variáveis de ambiente.

Variáveis:
- CARTEIRA_DB: caminho do banco SQLite (padrão ./carteira.db)
- CARTEIRA_PORTA: porta HTTP (padrão 8000); o servidor liga só em 127.0.0.1
- CARTEIRA_SEGREDO: segredo HMAC dos tokens; se ausente, é gerado com
  secrets.token_hex(32) e gravado no arquivo local .carteira_segredo
  (ignorado pelo Git, permissão 600)
- CARTEIRA_TOKEN_TTL: validade do token em segundos (padrão 28800 = 8h)
"""
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
DB_PADRAO = "./carteira.db"
PORTA_PADRAO = 8000
TTL_PADRAO = 8 * 60 * 60
ARQUIVO_SEGREDO_PADRAO = RAIZ / ".carteira_segredo"
TAMANHO_MINIMO_SEGREDO = 32


class ErroConfiguracao(ValueError):
    """Valor de configuração inválido."""


@dataclass(frozen=True)
class Config:
    db: str
    host: str
    porta: int
    segredo: str
    token_ttl: int

    def __repr__(self):  # nunca expõe o segredo em logs
        return (f"Config(db={self.db!r}, host={self.host!r}, porta={self.porta}, "
                f"segredo=<oculto>, token_ttl={self.token_ttl})")

    __str__ = __repr__


def _inteiro(env, nome, padrao, minimo, maximo):
    bruto = env.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = int(bruto)
    except ValueError:
        raise ErroConfiguracao(f"{nome} deve ser um número inteiro") from None
    if not minimo <= valor <= maximo:
        raise ErroConfiguracao(f"{nome} deve estar entre {minimo} e {maximo}")
    return valor


def obter_segredo_local(arquivo):
    """Lê o segredo do arquivo local ou gera um novo (permissão 600)."""
    arquivo = Path(arquivo)
    try:
        existente = arquivo.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existente = ""
    if len(existente) >= TAMANHO_MINIMO_SEGREDO:
        return existente
    novo = secrets.token_hex(32)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(arquivo), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(novo + "\n")
    try:
        os.chmod(str(arquivo), 0o600)
    except OSError:
        pass
    return novo


def carregar(env=None, arquivo_segredo=None):
    """Monta a Config a partir de `env` (padrão: os.environ)."""
    env = os.environ if env is None else env
    db = env.get("CARTEIRA_DB", "").strip() or DB_PADRAO
    porta = _inteiro(env, "CARTEIRA_PORTA", PORTA_PADRAO, 1, 65535)
    ttl = _inteiro(env, "CARTEIRA_TOKEN_TTL", TTL_PADRAO, 1, 30 * 24 * 60 * 60)
    segredo = env.get("CARTEIRA_SEGREDO", "").strip()
    if segredo:
        if len(segredo) < TAMANHO_MINIMO_SEGREDO:
            raise ErroConfiguracao(
                f"CARTEIRA_SEGREDO deve ter pelo menos {TAMANHO_MINIMO_SEGREDO} caracteres")
    else:
        segredo = obter_segredo_local(arquivo_segredo or ARQUIVO_SEGREDO_PADRAO)
    return Config(db=db, host=HOST, porta=porta, segredo=segredo, token_ttl=ttl)
