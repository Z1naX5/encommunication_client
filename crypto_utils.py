from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os

import random
from sympy import isprime


def generate_large_prime(bits=16):
    while True:
        candidate = random.getrandbits(bits)
        candidate |= 1  # 确保是奇数
        if isprime(candidate):
            return candidate


# === asymmetric encryption ===#


def generate_rsa_keys():
    public_exponent = generate_large_prime(16)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def serialize_public_key(pub):
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def serialize_private_key(priv):
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def rsa_encrypt(public_key_pem_or_obj, data: bytes):
    if isinstance(public_key_pem_or_obj, (str, bytes)):
        if isinstance(public_key_pem_or_obj, str):
            public_key_pem_or_obj = public_key_pem_or_obj.encode()
        pub = serialization.load_pem_public_key(public_key_pem_or_obj)
    else:
        # 已经是 RSA 公钥对象
        pub = public_key_pem_or_obj

    # 保留你原先的加密逻辑
    return pub.encrypt(data, padding.PKCS1v15())


def rsa_decrypt(private_key_pem, ciphertext: bytes):
    # Accept either a PEM string/bytes or an already-loaded private key object
    if isinstance(private_key_pem, (str, bytes)):
        if isinstance(private_key_pem, str):
            private_key_pem = private_key_pem.encode()
        priv = serialization.load_pem_private_key(private_key_pem, password=None)
    else:
        # assume it's already a private key object compatible with cryptography
        priv = private_key_pem

    return priv.decrypt(ciphertext, padding.PKCS1v15())


def rsa_verify(public_key, message: bytes, signature: bytes) -> bool:
    # Accept either a PEM string/bytes or an already-loaded public key object
    if isinstance(public_key, (str, bytes)):
        if isinstance(public_key, str):
            public_key = public_key.encode()
        public_key_obj = serialization.load_pem_public_key(public_key)
    else:
        public_key_obj = public_key

    public_key_obj.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    print("Signature is valid.")
    return True


# === symmetric encryption ===#


def gen_sym_key():
    return os.urandom(32)  # 32 bytes = 256 bits


def aes_gcm_encrypt(key: bytes, plaintext: bytes):
    # 生成随机 12 字节的 IV（推荐长度）
    iv = os.urandom(12)
    encryptor = Cipher(
        algorithms.AES(key), modes.GCM(iv), backend=default_backend()
    ).encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    tag = encryptor.tag  # 认证标签（防篡改）
    return iv, ciphertext, tag


def aes_gcm_decrypt(key: bytes, iv: bytes, ciphertext: bytes, tag: bytes):
    decryptor = Cipher(
        algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend()
    ).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext


# === save and load keys ===#


def save_keypair(priv, pub, priv_path, pub_path):
    pub_pem = serialize_public_key(pub)
    priv_pem = serialize_private_key(priv)

    with open(pub_path, "w") as f:
        f.write(pub_pem)
    with open(priv_path, "w") as f:
        f.write(priv_pem)


def load_private_key(pem_data):
    """从PEM格式字符串加载私钥"""
    return serialization.load_pem_private_key(
        pem_data.encode("utf-8"), password=None, backend=default_backend()
    )


def load_public_key(pem_data):
    """从PEM格式字符串加载公钥"""
    return serialization.load_pem_public_key(
        pem_data.encode("utf-8"), backend=default_backend()
    )


def load_or_generate_keys(username):
    """加载或生成用户的RSA密钥对"""
    os.makedirs("./keys", exist_ok=True)

    priv_path = f"./keys/{username}_priv.pem"
    pub_path = f"./keys/{username}_pub.pem"

    if os.path.exists(priv_path) and os.path.exists(pub_path):
        with open(priv_path, "r") as f:
            priv_pem = f.read()
        with open(pub_path, "r") as f:
            pub_pem = f.read()

        private_key = load_private_key(priv_pem)
        public_key = load_public_key(pub_pem)
    else:
        private_key, public_key = generate_rsa_keys()

        with open(priv_path, "w") as f:
            f.write(serialize_private_key(private_key))
        with open(pub_path, "w") as f:
            f.write(serialize_public_key(public_key))

    return private_key, public_key
