"""Aplica as migrações SQLite de db/migrations/sqlite (gerado pela Database Factory; somente biblioteca padrão).

Uso: python3 db/migrar.py [caminho.sqlite3]    (padrão: variável SQLITE_PATH ou .db/app.sqlite3)
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def migrar(caminho, seeds=False):
    con = sqlite3.connect(str(caminho))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (versao TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
                "aplicada_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))")
    feitas = dict(con.execute("SELECT versao, sha256 FROM schema_migrations"))
    aplicadas = []
    pastas = [RAIZ / "migrations" / "sqlite"] + ([RAIZ / "seeds" / "sqlite"] if seeds else [])
    for pasta in pastas:
        for arq in sorted(pasta.glob("*.sql")):
            chave = ("seed:" if "seeds" in arq.parts else "") + arq.stem
            sql = arq.read_text(encoding="utf-8")
            h = hashlib.sha256(sql.encode()).hexdigest()
            if chave in feitas:
                if feitas[chave] != h:
                    raise RuntimeError(f"migração {chave} foi alterada depois de aplicada")
                continue
            con.executescript(sql)
            con.execute("INSERT INTO schema_migrations (versao, sha256) VALUES (?, ?)", (chave, h))
            con.commit()
            aplicadas.append(chave)
    con.close()
    return aplicadas


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SQLITE_PATH", ".db/app.sqlite3")
    Path(alvo).parent.mkdir(parents=True, exist_ok=True)
    print("aplicadas:", migrar(alvo, seeds="--seeds" in sys.argv) or "nenhuma (já atualizado)")
