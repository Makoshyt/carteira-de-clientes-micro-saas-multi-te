import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import seguranca
from app.db import conectar, migrar
from app.seguranca import gerar_hash, verificar_senha

SENHA = "senha-ficticia-123"  # valor fictício só para testes
FORMATO = re.compile(r"^scrypt\$16384\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{128}$")


class TestHashSenha(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hash = gerar_hash(SENHA)

    def test_formato(self):
        self.assertRegex(self.hash, FORMATO)
        self.assertNotIn(SENHA, self.hash)

    def test_parametros(self):
        self.assertEqual((seguranca.SCRYPT_N, seguranca.SCRYPT_R, seguranca.SCRYPT_P,
                          seguranca.DKLEN, seguranca.TAMANHO_SAL), (2 ** 14, 8, 1, 64, 16))

    def test_senha_correta(self):
        self.assertTrue(verificar_senha(SENHA, self.hash))

    def test_senha_errada(self):
        for errada in ("senha-ficticia-124", SENHA.upper(), SENHA + " ", "", SENHA[:-1]):
            with self.subTest(errada=errada):
                self.assertFalse(verificar_senha(errada, self.hash))

    def test_mesma_senha_gera_hashes_diferentes(self):
        outro = gerar_hash(SENHA)
        self.assertNotEqual(self.hash, outro)
        self.assertNotEqual(self.hash.split("$")[4], outro.split("$")[4], "sal deve ser único")
        self.assertTrue(verificar_senha(SENHA, outro))

    def test_hash_confere_com_scrypt_direto(self):
        import hashlib
        _, n, r, p, sal, dk = self.hash.split("$")
        esperado = hashlib.scrypt(SENHA.encode(), salt=bytes.fromhex(sal), n=int(n),
                                  r=int(r), p=int(p), dklen=64)
        self.assertEqual(esperado.hex(), dk)

    def test_unicode(self):
        senha = "çãé-ficticia-ü"
        h = gerar_hash(senha)
        self.assertTrue(verificar_senha(senha, h))
        self.assertFalse(verificar_senha("cae-ficticia-u", h))

    def test_tipo_invalido_no_gerar(self):
        for valor in (None, b"bytes", 123):
            with self.subTest(valor=valor):
                with self.assertRaises(TypeError):
                    gerar_hash(valor)

    def test_hash_alterado_ou_malformado_retorna_false(self):
        partes = self.hash.split("$")
        ultimo = partes[5]
        trocado = ("0" if ultimo[-1] != "0" else "1")
        casos = [
            "", "texto-puro", SENHA, "scrypt$", "bcrypt$" + self.hash[7:],
            "$".join(partes[:5] + [ultimo[:-1] + trocado]),     # hash adulterado
            "$".join(partes[:4] + ["zz" * 16, ultimo]),          # sal não hex
            "$".join(partes[:5]),                                # faltando parte
            "$".join(partes + ["extra"]),                        # parte a mais
            "$".join([partes[0], "1000", *partes[2:]]),          # n não potência de 2
            "$".join([partes[0], str(2 ** 30), *partes[2:]]),    # n grande demais
            "$".join([partes[0], "-16384", *partes[2:]]),        # n negativo
            "$".join([partes[0], partes[1], "0", *partes[3:]]),  # r inválido
            "$".join([partes[0], partes[1], partes[2], "999", *partes[4:]]),  # p grande demais
            "$".join(partes[:4] + ["", ultimo]),                 # sal vazio
            "$".join(partes[:5] + [""]),                         # hash vazio
            "$".join(partes[:5] + [ultimo[:2] + " " + ultimo[2:]]),  # espaço no hex
            "$".join(partes[:5] + [ultimo.upper()]),             # hex fora do formato gravado
        ]
        for armazenado in casos:
            with self.subTest(armazenado=armazenado[:40]):
                self.assertFalse(verificar_senha(SENHA, armazenado))

    def test_tipos_invalidos_no_verificar(self):
        for senha, armazenado in ((None, self.hash), (b"x", self.hash),
                                  (SENHA, None), (SENHA, b"scrypt$")):
            with self.subTest(senha=senha, armazenado=armazenado):
                self.assertFalse(verificar_senha(senha, armazenado))

    def test_senha_com_surrogate_nao_quebra(self):
        self.assertFalse(verificar_senha("\ud800", self.hash))

    def test_hash_aceito_pelo_check_do_banco(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = conectar(str(Path(tmp) / "t.db"))
            try:
                migrar(con)
                data = "2026-01-01T00:00:00Z"
                con.execute("INSERT INTO empresas (id, nome, criado_em) VALUES (?, ?, ?)",
                            ("e1", "Empresa Fictícia", data))
                sql = ("INSERT INTO usuarios (id, empresa_id, email, senha_hash, criado_em) "
                       "VALUES (?, ?, ?, ?, ?)")
                # O CHECK do esquema recusa texto puro e aceita o formato scrypt$...
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute(sql, ("u0", "e1", "a@exemplo.test", SENHA, data))
                con.execute(sql, ("u1", "e1", "b@exemplo.test", self.hash, data))
                (gravado,) = con.execute(
                    "SELECT senha_hash FROM usuarios WHERE id = ?", ("u1",)).fetchone()
                self.assertTrue(verificar_senha(SENHA, gravado))
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
