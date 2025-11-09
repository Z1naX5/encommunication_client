import asyncio
import threading
import json
import base64
import websockets
import time
from flask import Flask
from crypto_utils import (
    load_or_generate_keys,
    load_public_key,
    rsa_verify,
    rsa_decrypt,
    rsa_encrypt,
    gen_sym_key,
    aes_gcm_encrypt,
    aes_gcm_decrypt,
)

online_users = {}  # id -> username
message = {}


class WSClient:
    def __init__(self, id, username, token):
        self.username = username
        self.token = token
        self.ws = None
        self.connected = False
        self._lock = threading.Lock()  # 用于同步操作
        self.loop = None  # 延迟初始化事件循环
        self._async_lock = None  # 延迟初始化异步锁
        self.my_id = id
        self.peer_pubkeys = {}  # id -> PEM
        self.sym_keys = {}  # id -> AES key
        self.key_status = {}  # id -> str: 'pending', 'confirmed', 'error'
        self.message_queue = {}  # id -> list: 待发送的消息队列
        self.priv_key, self.pub_key = load_or_generate_keys(username)
        self.server_pub_key = None

    def start(self):
        if not self.connected:
            t = threading.Thread(target=self.run)
            t.daemon = True
            t.start()

    def run(self, server_address="192.168.1.5:8080"):
        try:
            if not self.loop:
                self.loop = asyncio.new_event_loop()
                self._async_lock = asyncio.Lock()
                asyncio.set_event_loop(self.loop)

            if not self.loop.is_running():
                self.loop.run_until_complete(self._run(server_address))
            else:
                # 如果loop已经在运行，使用run_coroutine_threadsafe
                asyncio.run_coroutine_threadsafe(self._run(server_address), self.loop)
        except Exception as e:
            print(f"[错误] Event loop 错误: {e}")

    async def _run(self, server_address):
        ws_url = f"ws://{server_address}/chat"
        while True:
            try:
                async with websockets.connect(
                    ws_url, additional_headers={"token": self.token}
                ) as ws:
                    with self._lock:
                        self.ws = ws
                        self.connected = True
                    print(f"[WebSocket已连接] 用户: {self.username} (ID: {self.my_id})")

                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("systemMessage"):
                            await self.handle_system_message(msg["message"])
                        else:
                            await self.handle_user_message(msg)

            except Exception as e:
                print(f"[错误] WebSocket连接断开: {e}，5秒后重连...")
                with self._lock:
                    self.ws = None
                    self.connected = False
                await asyncio.sleep(4)

    async def ensure_connection(self):
        """确保WebSocket连接存在"""
        if not self.connected or self.ws is None:
            print("[警告] WebSocket未连接，尝试重新连接...")
            self.start()
            # 等待连接建立
            timeout = 5
            while not self.connected and timeout > 0:
                await asyncio.sleep(0.1)
                timeout -= 0.1
            if not self.connected:
                raise Exception("无法建立WebSocket连接")
        return self.ws

    def decrypt_message(self, from_id, message, K=None):
        if K is None:
            K = self.sym_keys[from_id]
        enc_bytes = base64.b64decode(message)
        iv, ct, tag = enc_bytes[:12], enc_bytes[12:-16], enc_bytes[-16:]
        plaintext = aes_gcm_decrypt(K, iv, ct, tag).decode()
        return plaintext

    async def handle_system_message(self, users):
        if self.server_pub_key is None:
            with open("./server_public.pem", "r") as f:
                server_pub_pem = f.read()
            self.server_pub_key = server_pub_pem

        new_online = {}
        for u in users:
            try:
                public_key = u["publicKey"].encode()
                enpublic_key = base64.b64decode(u["enpublicKey"])

                if rsa_verify(self.server_pub_key, public_key, enpublic_key):
                    pub_pem = u["publicKey"]
                    user_id = int(u["id"])  # 确保 ID 是整数
                    self.peer_pubkeys[user_id] = pub_pem
                    new_online[user_id] = u["username"]
                    print(f"[系统消息] 成功加载用户 {user_id} 的公钥")

            except Exception as e:
                print(f"[系统消息处理错误] 用户 {u.get('id', 'unknown')}: {str(e)}")

        online_users.clear()
        online_users.update(new_online)

        print("[系统消息] 当前在线用户：", online_users)

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
                        # 添加延迟，等待服务器处理密钥确认
                        # await asyncio.sleep(0.5)  # 500ms delay
                        await self._send_queued_messages(from_id)

                    else:
                        print(f"[密钥错误] 与用户 {from_id} 的密钥不匹配")
                        self.key_status[from_id] = "error"

                else:
                    self.sym_keys[from_id] = received_key
                    self.key_status[from_id] = "pending"

                    peer_pub = load_public_key(self.peer_pubkeys[from_id])
                    confirm_key = rsa_encrypt(peer_pub, received_key)

                    # 使用异步锁序列化所有发送，防止并发导致的协议错误
                    if not self._async_lock:
                        self._async_lock = asyncio.Lock()
                    async with self._async_lock:
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

                plaintext = self.decrypt_message(from_id, message)
                print(f"[收到消息] 来自 {from_id}: {plaintext}")

            except Exception as e:
                print(f"[消息解密错误] {str(e)}")

    async def _send_queued_messages(self, target_id):
        """发送队列中的消息"""
        print("entry _send_queued_messages")
        if target_id in self.message_queue:
            while self.message_queue[target_id]:
                msg = self.message_queue[target_id].pop(0)
                try:
                    print(f"[队列发送] 发送消息到用户 {target_id}")
                    await self._send_message(target_id, msg)
                except Exception as e:
                    print(f"[队列发送错误] {e}")
                    # 如果发送失败，放回队列前端等待重试
                    self.message_queue[target_id].insert(0, msg)
                    break

    async def _send_message(self, target_id, msg):
        """实际发送消息的方法"""
        print("entry _send_message")
        if not self._async_lock:
            self._async_lock = asyncio.Lock()

        try:
            # 确保连接存在
            ws = await self.ensure_connection()
            if not ws:
                raise Exception("WebSocket连接无效")

            K = self.sym_keys[target_id]
            iv, ct, tag = aes_gcm_encrypt(K, msg.encode())
            final = iv + ct + tag

            peer_pub = load_public_key(self.peer_pubkeys[target_id])
            encK = rsa_encrypt(peer_pub, K)

            data = {
                "fromId": self.my_id,
                "toId": target_id,
                "message": base64.b64encode(final).decode(),
                "aesKey": base64.b64encode(encK).decode(),
            }
            print("send message")
            print(data)
            async with self._async_lock:
                await ws.send(json.dumps(data))

        except Exception as e:
            print(f"[消息发送错误] {str(e)}")
            raise

    def send_encrypted_message(self, target_id, msg):
        print("[发送消息] 发送加密消息到用户")

        # 检查基本条件
        if not self.loop:
            print("[错误] 事件循环未初始化")
            return False

        # 检查连接状态
        with self._lock:
            ws = self.ws
            connected = self.connected

        if not ws or not connected:
            print("[错误] WebSocket 未连接，无法发送消息")
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

            # 如果完全没有密钥，则新建并发起交换
            if target_id not in self.sym_keys:
                try:
                    K = gen_sym_key()
                    self.sym_keys[target_id] = K
                    self.key_status[target_id] = "pending"

                    peer_pub_obj = self.peer_pubkeys[target_id]
                    if isinstance(peer_pub_obj, (bytes, str)):
                        peer_pub = load_public_key(peer_pub_obj)
                    else:
                        peer_pub = peer_pub_obj

                    encK = rsa_encrypt(peer_pub, K)

                    payload = json.dumps(
                        {
                            "fromId": self.my_id,
                            "toId": target_id,
                            "message": "",
                            "aesKey": base64.b64encode(encK).decode(),
                        }
                    )

                    async def send_key():
                        ws = await self.ensure_connection()
                        if not self._async_lock:
                            self._async_lock = asyncio.Lock()
                        async with self._async_lock:
                            await ws.send(payload)

                    asyncio.run_coroutine_threadsafe(send_key(), self.loop)

                except Exception as e:
                    print(f"[密钥交换错误] {e}")

            else:
                print("[密钥交换等待中] 已加入消息队列")

            return True

        coro = self._send_message(target_id, msg)
        asyncio.run_coroutine_threadsafe(coro, self.loop)
        return True
