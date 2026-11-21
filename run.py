"""Ponto de entrada: aplica as migrações e sobe o servidor em 127.0.0.1."""
from pathlib import Path
from wsgiref.simple_server import make_server

from app.config import carregar
from app.servidor import criar_app
from db.migrar import migrar


def preparar(config):
    """Cria a pasta do banco (se preciso) e aplica as migrações pendentes."""
    Path(config.db).resolve().parent.mkdir(parents=True, exist_ok=True)
    return migrar(config.db)


def main():
    config = carregar()
    aplicadas = preparar(config)
    if aplicadas:
        print("migrações aplicadas:", ", ".join(aplicadas))
    with make_server(config.host, config.porta, criar_app(config)) as servidor:
        print(f"Carteira de Clientes em http://{config.host}:{config.porta}/ (Ctrl+C para sair)")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nencerrado")


if __name__ == "__main__":
    main()
