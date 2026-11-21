"""Atalhos para aplicar as migrações num arquivo SQLite pelo caminho.

O executor de verdade fica em app/db.py (migrar(conexao)); este módulo só abre
a conexão, chama o executor e fecha a conexão. Mantido para o run.py e para
quem prefere trabalhar com o caminho do banco.
"""
from app.db import PASTA_MIGRACOES as PASTA_PADRAO
from app.db import ErroMigracao, agora_iso, conectar, listar_migracoes, migrar

__all__ = ["PASTA_PADRAO", "ErroMigracao", "agora_iso", "listar", "aplicar"]


def listar(pasta=PASTA_PADRAO):
    """Devolve [(versao, caminho)] em ordem numérica, validando os nomes."""
    return listar_migracoes(pasta)


def aplicar(caminho, pasta=PASTA_PADRAO):
    """Aplica as migrações pendentes no banco SQLite `caminho`.

    Devolve a lista de versões aplicadas nesta chamada ([] se já estava atualizado).
    """
    listar_migracoes(pasta)  # valida os nomes antes de criar/abrir o arquivo do banco
    conexao = conectar(caminho)
    try:
        return migrar(conexao, pasta)
    finally:
        conexao.close()
