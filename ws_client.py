import asyncio, threading, json, base64, os
import websockets

from crypto_utils import *


class WSClient:
    def __init__(self, id, username, token):
        self.username = username
        self.token = token
        self.ws = None
        self.loop = asyncio.new_event_loop()
        self.my_id = id
        self.peer_pubkeys = {}  # id -> PEM
        self.sym_keys = {}  # id -> AES key
        self.key_status = {}  # id -> str: 'pending', 'confirmed', 'error'
        self.message_queue = {}  # id -> list: 待发送的消息队列
        self.priv_key, self.pub_key = load_or_generate_keys(username)
        self.server_pub_key = None

    def start(self):
        t = threading.Thread(target=self.run)
        t.daemon = True
        t.start()

    def run(self, server_address="192.168.1.2:8080"):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run(server_address))

    async def _run(self, server_address):
        ws_url = f"ws://{server_address}/chat"
        async with websockets.connect(
            ws_url, additional_headers={"token": self.token}
        ) as ws:
            self.ws = ws
            print(f"[WebSocket已连接] 用户: {self.username} (ID: {self.my_id})")
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("systemMessage"):
                    await self.handle_system_message(msg["message"])
                else:
                    await self.handle_user_message(msg)

    async def handle_system_message(self, users):
        if self.server_pub_key is None:
            with open("./server_public.pem", "r") as f:
                server_pub_pem = f.read()
            self.server_pub_key = server_pub_pem
        for u in users:
            try:
                public_key = u["publicKey"].encode()
                enpublic_key = base64.b64decode(u["enpublicKey"])
                if rsa_verify(self.server_pub_key, public_key, enpublic_key):
                    pub_pem = u["publicKey"]
                self.peer_pubkeys[u["id"]] = pub_pem
            except Exception as e:
                print(f"[系统消息处理错误] 用户 {u.get('id', 'unknown')}: {str(e)}")

    async def handle_user_message(self, msg):
        from_id = msg["fromId"]
        message = msg.get("message", "")
        aes_key = msg.get("aesKey", "")

        # 处理密钥交换
        if not message and aes_key:
            try:
                received_key = rsa_decrypt(self.priv_key, base64.b64decode(aes_key))

                if from_id in self.sym_keys:
                    if self.sym_keys[from_id] == received_key:
                        print(f"[密钥确认] 与用户 {from_id} 的密钥已同步")
                        self.key_status[from_id] = "confirmed"
                        await self._send_queued_messages(from_id)

                    else:
                        print(f"[密钥错误] 与用户 {from_id} 的密钥不匹配")
                        self.key_status[from_id] = "error"

                else:
                    self.sym_keys[from_id] = received_key
                    self.key_status[from_id] = "pending"

                    peer_pub = load_public_key(self.peer_pubkeys[from_id])
                    confirm_key = rsa_encrypt(peer_pub, received_key)

                    await self.ws.send(
                        json.dumps(
                            {
                                "fromId": self.my_id,
                                "toId": from_id,
                                "message": "",
                                "aesKey": base64.b64encode(confirm_key).decode(),
                            }
                        )
                    )
                    print(f"[密钥交换] 已向用户 {from_id} 发送确认")

            except Exception as e:
                print(f"[密钥交换错误] {str(e)}")
                self.key_status[from_id] = "error"
            return

        if message:
            try:
                if from_id not in self.sym_keys:
                    print(f"[错误] 与用户 {from_id} 尚未建立安全连接")
                    return

                if self.key_status.get(from_id) != "confirmed":
                    print(f"[错误] 与用户 {from_id} 的密钥尚未确认")
                    return

                K = self.sym_keys[from_id]
                enc_bytes = base64.b64decode(message)
                iv, ct, tag = enc_bytes[:12], enc_bytes[12:-16], enc_bytes[-16:]
                plaintext = aes_gcm_decrypt(K, iv, ct, tag).decode()

                print(f"[收到消息] 来自 {from_id}: {plaintext}")

            except Exception as e:
                print(f"[消息解密错误] {str(e)}")

    async def _send_queued_messages(self, target_id):
        """发送队列中的消息"""
        if target_id in self.message_queue:
            while self.message_queue[target_id]:
                msg = self.message_queue[target_id].pop(0)
                await self._send_message(target_id, msg)

    async def _send_message(self, target_id, msg):
        """实际发送消息的方法"""
        try:
            K = self.sym_keys[target_id]
            iv, ct, tag = aes_gcm_encrypt(K, msg.encode())
            final = iv + ct + tag

            peer_pub = load_public_key(self.peer_pubkeys[target_id])
            encK = rsa_encrypt(peer_pub, K)
            await self.ws.send(
                json.dumps(
                    {
                        "fromId": self.my_id,
                        "toId": target_id,
                        "message": base64.b64encode(final).decode(),
                        "aesKey": base64.b64encode(encK).decode(),
                    }
                )
            )
        except Exception as e:
            print(f"[消息发送错误] {str(e)}")

    def send_encrypted_message(self, target_id, msg):
        if not self.ws or not self.ws.open:
            print(f"[错误] WebSocket 未连接，无法发送消息")
            return False

        if target_id not in self.peer_pubkeys:
            print(f"[错误] 未知用户: {target_id}")
            return False

        if (
            target_id not in self.sym_keys
            or self.key_status.get(target_id) != "confirmed"
        ):
            self.message_queue.setdefault(target_id, [])
            self.message_queue[target_id].append(msg)

            if target_id not in self.sym_keys:
                K = gen_sym_key()
                self.sym_keys[target_id] = K
                self.key_status[target_id] = "pending"

                peer_pub = load_public_key(self.peer_pubkeys[target_id])
                encK = rsa_encrypt(peer_pub, K)

                # ✅ 在后台事件循环中执行发送
                coro = self.ws.send(
                    json.dumps(
                        {
                            "fromId": self.my_id,
                            "toId": target_id,
                            "message": "",
                            "aesKey": base64.b64encode(encK).decode(),
                        }
                    )
                )
                asyncio.run_coroutine_threadsafe(coro, self.loop)
                print(f"[密钥交换] 已向用户 {target_id} 发送密钥")

            else:
                print(f"[密钥交换等待中] 已加入消息队列")

            return True

        coro = self._send_message(target_id, msg)
        asyncio.run_coroutine_threadsafe(coro, self.loop)
        return True
