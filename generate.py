from crypto_utils import generate_rsa_keys, serialize_private_key, serialize_public_key

private_key, public_key = generate_rsa_keys()

# 转为 PEM 格式字符串
pub_pem = serialize_public_key(public_key)
priv_pem = serialize_private_key(private_key)

# 保存文件
with open("server_public.pem", "w") as f:
    f.write(pub_pem)

with open("server_private.pem", "w") as f:
    f.write(priv_pem)

print("✅ 服务器RSA密钥对已生成")
