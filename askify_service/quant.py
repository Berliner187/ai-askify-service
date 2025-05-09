from Crypto.PublicKey import ECC
from Crypto.Cipher import AES
from Crypto.Hash import SHA256, HMAC
from Crypto.Util.Padding import pad, unpad

import os
import hashlib
import json
import base64


from .utils import ManageConfidentFields


manage = ManageConfidentFields("config.json")
SECRET_KEY = manage.get_confident_key("secret_key")


class Quant:
    def __init__(self):
        self.private_key = None
        self.public_key = None
        self.shared_key = None

    def generate_keys_with_secret(self):
        """Генерация ключей с использованием SECRET_KEY."""
        seed = SHA256.new(SECRET_KEY.encode('utf-8')).digest()
        self.private_key = ECC.generate(curve='P-256', randfunc=lambda x: seed[:x])
        self.public_key = self.private_key.public_key()
        return self.private_key, self.public_key

    def derive_shared_key(self, peer_public_key):
        """Вычисление общего ключа на основе приватного ключа и публичного ключа другого участника."""
        if not self.private_key:
            raise ValueError("Приватный ключ не сгенерирован. Сначала вызовите generate_keys_with_secret().")

        shared_point = self.private_key.d * peer_public_key.pointQ
        shared_point_bytes = int(shared_point.x).to_bytes(32, 'big') + int(shared_point.y).to_bytes(32, 'big')

        # self.shared_key = hashlib.sha256(shared_point_bytes).digest()[:16]
        self.shared_key = hashlib.sha256(shared_point_bytes).digest()[:32]  # 32 байта для AES-256

        return self.shared_key

    def encrypt_data(self, data):
        """Шифрование данных с использованием общего ключа."""
        if not self.shared_key:
            raise ValueError("Общий ключ не вычислен. Сначала вызовите derive_shared_key().")

        if isinstance(data, dict):
            data = json.dumps(data)

        cipher = AES.new(self.shared_key, AES.MODE_EAX)
        ciphertext, tag = cipher.encrypt_and_digest(data.encode())
        return cipher.nonce, ciphertext, tag

    def decrypt_data(self, nonce, ciphertext, tag):
        """Дешифрование данных с использованием общего ключа."""
        if not self.shared_key:
            raise ValueError("Общий ключ не вычислен. Сначала вызовите derive_shared_key().")

        cipher = AES.new(self.shared_key, AES.MODE_EAX, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return json.loads(plaintext.decode())  # Преобразуем строку JSON обратно в словарь

    @staticmethod
    def verify_public_key(public_key):
        """Проверка подлинности публичного ключа."""
        return isinstance(public_key, ECC.EccKey)  # Просто проверка типа

    @staticmethod
    def generate_secret_key():
        """
            Генерирует случайный SECRET_KEY длиной 256 бит и кодирует его в base64.
        """
        secret_key = os.urandom(32)

        secret_key_base64 = base64.urlsafe_b64encode(secret_key).decode()

        return secret_key_base64


