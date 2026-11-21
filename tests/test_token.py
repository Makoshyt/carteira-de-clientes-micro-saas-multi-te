import base64
import hashlib
import hmac
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import conectar, migrar
from app.seguranca import (assinar, criar_sessao, gerar_token, limpar_sessoes_expiradas,
                           revogar_sessao, sessao_do_token, validar_token)
from tests import ficticio

# Valores fictícios gerados na execução, só para testes.
SEGREDO = ficticio.segredo()
OUTRO_SEGREDO = ficticio.segredo()
HASH_FICTICIO = "scrypt$ficticio"  # aceito pelo CHECK; estes testes não verificam senha
DATA = "2026-01-01T00:00:00Z"
AGORA = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
TTL = 3600


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.con = conectar(str(Path(self._tmp.name) / "t.db"))
        self.addCleanup(self.con.close)
        migrar(self.con)
        with self.con:
            for emp, usu, email in (("e1", "u1", "a@exemplo.test"), ("e2", "u2", "b@exemplo.test")):
                self.con.execute("INSERT INTO empresas (id, nome, criado_em) VALUES (?, ?, ?)",
                                 (emp, "Empresa Fictícia " + emp, DATA))
                self.con.execute(
                    "INSERT INTO usuarios (id, empresa_id, email, senha_hash, criado_em) "
                    "VALUES (?, ?, ?, ?, ?)", (usu, emp, email, HASH_FICTICIO, DATA))

    def contar_sessoes(self):
        return self.con.execute("SELECT COUNT(*) FROM sessoes").fetchone()[0]


class TestAssinatura(unittest.TestCase):
    def test_formato_e_hmac_sha256_base64url(self):
        sessao_id = "A" * 43
        token = gerar_token(SEGREDO, sessao_id)
        sid, assinatura = token.split(".")
        self.assertEqual(sid, sessao_id)
        esperado = base64.urlsafe_b64encode(
            hmac.new(SEGREDO.encode(), sessao_id.encode(), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        self.assertEqual(assinatura, esperado)
        self.assertEqual(assinar(SEGREDO, sessao_id), esperado)
        self.assertNotIn("=", token)

    def test_sessao_do_token(self):
        token = gerar_token(SEGREDO, "B" * 43)
        self.assertEqual(sessao_do_token(SEGREDO, token), "B" * 43)
        self.assertIsNone(sessao_do_token(OUTRO_SEGREDO, token))

    def test_tokens_malformados(self):
        valido = gerar_token(SEGREDO, "C" * 43)
        sid, assinatura = valido.split(".")
        casos = [None, b"x", 123, "", ".", sid, sid + ".", "." + assinatura,
                 valido + ".x", valido + "x", " " + valido, valido + "\n",
                 sid + "." + assinatura + "=", "Ç" * 43 + "." + assinatura,
                 "D" * 300 + "." + assinatura, "curto." + assinatura]
        for token in casos:
            with self.subTest(token=repr(token)[:40]):
                self.assertIsNone(sessao_do_token(SEGREDO, token))

    def test_segredo_e_id_invalidos(self):
        for segredo in ("", None, b""):
            with self.subTest(segredo=segredo), self.assertRaises(ValueError):
                gerar_token(segredo, "E" * 43)
        for sid in ("", "com.ponto" * 3, "curto", None, "ç" * 20):
            with self.subTest(sid=sid), self.assertRaises(ValueError):
                gerar_token(SEGREDO, sid)


class TestSessoes(BaseBanco):
    def test_criar_e_validar(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        self.assertEqual(validar_token(self.con, SEGREDO, token, agora=AGORA), ("u1", "e1"))
        self.assertEqual(self.contar_sessoes(), 1)
        sid = token.split(".")[0]
        expira, criado = self.con.execute(
            "SELECT expira_em, criado_em FROM sessoes WHERE id = ?", (sid,)).fetchone()
        self.assertEqual(criado, "2026-06-01T12:00:00Z")
        self.assertEqual(expira, "2026-06-01T13:00:00Z")

    def test_validar_com_hora_atual_real(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL)
        self.assertEqual(validar_token(self.con, SEGREDO, token), ("u1", "e1"))

    def test_sessao_gravada_e_persistida(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        self.assertFalse(self.con.in_transaction)
        outra = conectar(str(Path(self._tmp.name) / "t.db"))
        try:
            self.assertEqual(validar_token(outra, SEGREDO, token, agora=AGORA), ("u1", "e1"))
        finally:
            outra.close()

    def test_tokens_unicos(self):
        t1 = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        t2 = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        self.assertNotEqual(t1, t2)
        self.assertEqual(self.contar_sessoes(), 2)

    def test_empresa_vem_da_sessao(self):
        t1 = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        t2 = criar_sessao(self.con, SEGREDO, "u2", "e2", TTL, agora=AGORA)
        self.assertEqual(validar_token(self.con, SEGREDO, t1, agora=AGORA), ("u1", "e1"))
        self.assertEqual(validar_token(self.con, SEGREDO, t2, agora=AGORA), ("u2", "e2"))

    def test_token_alterado(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        sid, assinatura = token.split(".")
        troca = "A" if assinatura[0] != "A" else "B"
        outro_sid = ("x" if sid[0] != "x" else "y") + sid[1:]
        casos = [
            sid + "." + troca + assinatura[1:],     # assinatura adulterada
            outro_sid + "." + assinatura,           # id trocado, assinatura antiga
            sid + "." + assinatura[:-1],            # assinatura truncada
            sid,                                    # só o id, sem assinatura
        ]
        for alterado in casos:
            with self.subTest(token=alterado[-12:]):
                self.assertIsNone(validar_token(self.con, SEGREDO, alterado, agora=AGORA))

    def test_segredo_diferente(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        self.assertIsNone(validar_token(self.con, OUTRO_SEGREDO, token, agora=AGORA))

    def test_assinatura_valida_sem_sessao(self):
        forjado = gerar_token(SEGREDO, "F" * 43)  # assinatura certa, mas sessão inexistente
        self.assertIsNone(validar_token(self.con, SEGREDO, forjado, agora=AGORA))

    def test_expiracao(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        quase = AGORA + timedelta(seconds=TTL - 1)
        self.assertEqual(validar_token(self.con, SEGREDO, token, agora=quase), ("u1", "e1"))
        for depois in (AGORA + timedelta(seconds=TTL), AGORA + timedelta(days=30)):
            with self.subTest(depois=depois):
                self.assertIsNone(validar_token(self.con, SEGREDO, token, agora=depois))

    def test_logout_revoga(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        outro = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        self.assertTrue(revogar_sessao(self.con, SEGREDO, token))
        self.assertIsNone(validar_token(self.con, SEGREDO, token, agora=AGORA))
        self.assertFalse(revogar_sessao(self.con, SEGREDO, token))  # já revogado
        self.assertFalse(self.con.in_transaction)
        # Só a sessão do token foi apagada.
        self.assertEqual(validar_token(self.con, SEGREDO, outro, agora=AGORA), ("u1", "e1"))
        self.assertEqual(self.contar_sessoes(), 1)

    def test_logout_com_token_invalido_nao_apaga(self):
        token = criar_sessao(self.con, SEGREDO, "u1", "e1", TTL, agora=AGORA)
        sid = token.split(".")[0]
        for invalido in (sid + "." + "A" * 43, token + "x", "", None):
            with self.subTest(token=repr(invalido)[-12:]):
                self.assertFalse(revogar_sessao(self.con, SEGREDO, invalido))
        self.assertFalse(revogar_sessao(self.con, OUTRO_SEGREDO, token))
        self.assertEqual(self.contar_sessoes(), 1)

    def test_ttl_invalido(self):
        for ttl in (0, -1, 1.5, "60", None, True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                criar_sessao(self.con, SEGREDO, "u1", "e1", ttl, agora=AGORA)
        self.assertEqual(self.contar_sessoes(), 0)

    def test_sessao_com_empresa_de_outro_usuario_recusada(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            criar_sessao(self.con, SEGREDO, "u1", "e2", TTL, agora=AGORA)
        self.assertEqual(self.contar_sessoes(), 0)

    def test_limpar_expiradas(self):
        velho = criar_sessao(self.con, SEGREDO, "u1", "e1", 60, agora=AGORA)
        novo = criar_sessao(self.con, SEGREDO, "u2", "e2", TTL, agora=AGORA)
        depois = AGORA + timedelta(seconds=120)
        self.assertEqual(limpar_sessoes_expiradas(self.con, agora=depois), 1)
        self.assertIsNone(validar_token(self.con, SEGREDO, velho, agora=AGORA))
        self.assertEqual(validar_token(self.con, SEGREDO, novo, agora=depois), ("u2", "e2"))


if __name__ == "__main__":
    unittest.main()
