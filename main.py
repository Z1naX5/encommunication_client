import webbrowser
from flask import Flask, render_template, request, jsonify, Response
from ws_client import WSClient, online_users
import requests
from crypto_utils import (
    load_or_generate_keys,
    serialize_public_key,
    rsa_decrypt,
    aes_gcm_decrypt,
)
import base64
import queue
import time

app = Flask(__name__)
host = "127.0.0.1"
port = 5000
message_queue = queue.Queue()
ws_clients = {}  # id -> WSClient实例
server_address = "172.16.2.82:8080"
CHAT_RECORDS_FILE = "chat_records.json"


def _make_resp(code: int, msg: str, data=None, status_code: int = 200):
    """统一返回格式：{ code: 1|0, msg: str, data: ... } 以及 HTTP 状态码

    code: 1 表示成功，0 表示失败
    """
    payload = {"code": code, "msg": msg, "data": data}
    return jsonify(payload), status_code


# ------------------------------
# 页面路由
# ------------------------------
@app.route("/")
def login_page():
    return render_template("login.html")


@app.route("/users")
def user_list_page():
    return render_template("user_list.html")


@app.route("/chat/<int:target_id>")
def chat_page(target_id):
    return render_template("chat.html", target_id=target_id)


# ------------------------------
# 后端接口
# ------------------------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data["username"]
    password = data["password"]
    print(username, password)

    backend_url = f"http://{server_address}/login"
    payload = {"username": username, "password": password}
    try:
        response = requests.post(
            backend_url, json=payload, headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            backend_data = response.json()
            print(backend_data)

            if backend_data.get("code") != 0:
                user_data = backend_data.get("data", {})

                user_id = user_data.get("id")
                token = user_data.get("token")
                username = user_data.get("username")
                client = WSClient(user_id, username, token, host, port)
                ws_clients[user_id] = client
                client.start()

                return _make_resp(1, "登录成功", {"token": token})
            else:
                return _make_resp(0, "后端未返回有效的 code", backend_data, 400)
        else:
            try:
                error_data = response.json()
            except Exception:
                error_data = None
            return _make_resp(0, "登录失败", error_data, response.status_code)

    except requests.exceptions.RequestException as e:
        return _make_resp(0, f"无法连接到后端服务器: {str(e)}", None, 500)
    except Exception as e:
        return _make_resp(0, f"服务器错误: {str(e)}", None, 500)


@app.route("/api/register", methods=["POST"])
def register():
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")
        repassword = data.get("repassword")

        # 验证数据
        if not all([username, password, repassword]):
            return jsonify({"code": 0, "msg": "缺少必要参数", "data": None}), 400

        priv_key, pub_key = load_or_generate_keys(username)

        backend_url = f"http://{server_address}/register"
        payload = {
            "username": username,
            "password": password,
            "repassword": repassword,
            "publicKey": serialize_public_key(pub_key),
        }
        # print(payload)
        response = requests.post(
            backend_url, json=payload, headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            backend_data = response.json()
            if backend_data.get("code") != 0:
                return _make_resp(1, "注册成功", backend_data.get("data"))
            else:
                return _make_resp(0, "注册失败", backend_data, 400)
        else:
            return _make_resp(0, "注册失败: 后端返回非200", None, response.status_code)

    except Exception as e:
        return _make_resp(0, str(e), None, 500)


@app.route("/api/online_users", methods=["GET"])
def get_online_users():
    return _make_resp(1, "ok", {"users": online_users})


# push仅用于websocket向前推送消息
@app.route("/push", methods=["POST"])
def push_message():
    """WebSocket 或内部调用，把消息推送给浏览器"""
    data = request.json
    message_queue.put(data)
    print(f"[推送消息] {data}")
    return {"status": "ok"}


@app.route("/api/stream")
def stream():
    """SSE 数据流：浏览器通过 EventSource 订阅"""

    def event_stream():
        while True:
            msg = message_queue.get()  # 阻塞等待消息
            yield f"data: {msg}\n\n"  # SSE 格式：每条消息以 \n\n 结尾

    return Response(event_stream(), content_type="text/event-stream")


@app.route("/api/send_message", methods=["POST"])
def send_message():
    data = request.json
    if not data:
        return _make_resp(0, "No JSON data", None, 400)

    try:
        from_id = int(data["from_id"])
        target_id = int(data["target_id"])
        message = data["message"]
    except (KeyError, ValueError, TypeError):
        return _make_resp(0, "Invalid message format", None, 400)

    client = ws_clients.get(from_id)
    if client:
        if not client.connected:
            print("[Flask] 等待 WebSocket 连接...")
            client.start()
            time.sleep(1)  # 等待连接几秒再试

        ok = client.send_encrypted_message(target_id, message)
        if ok:
            return _make_resp(1, "ok", None)
        else:
            return _make_resp(0, "发送失败: 客户端未就绪", None, 500)
    return _make_resp(0, "no client", None, 400)


@app.route("/api/chat/records", methods=["GET"])
def get_chat_records():
    backend_url = f"http://{server_address}/chatRecords"
    try:
        # 获取并验证参数
        from_id = request.args.get("fromId")
        to_id = request.args.get("toId")
        if not from_id or not to_id:
            return jsonify(
                {"code": 0, "msg": "Missing fromId or toId", "data": None}
            ), 400

        try:
            from_id = int(from_id)
            to_id = int(to_id)
        except (ValueError, TypeError):
            return jsonify({"code": 0, "msg": "Invalid ID format", "data": None}), 400

        # 验证客户端存在
        if from_id not in ws_clients:
            return jsonify({"code": 0, "msg": "Sender not found", "data": None}), 400

        # 加载记录
        payload = {"fromId": from_id, "toId": to_id}
        response = requests.get(
            backend_url,
            params=payload,
            headers={"token": ws_clients[from_id].token},
        )
        if response.status_code == 200:
            records = response.json()
            print(records)

            records_ret = []

            for record in records:
                try:
                    create_time = record.get("createTime")
                    en_msg = record.get("message", "")

                    if from_id == record.get("fromId"):
                        aes_key = record.get("toAesKey", "")
                    else:
                        aes_key = record.get("fromAesKey", "")
                    K = rsa_decrypt(
                        ws_clients[from_id].priv_key, base64.b64decode(aes_key)
                    )
                    enc_bytes = base64.b64decode(en_msg)
                    iv, ct, tag = enc_bytes[:12], enc_bytes[12:-16], enc_bytes[-16:]
                    plaintext = aes_gcm_decrypt(K, iv, ct, tag).decode()

                    records_ret.append(
                        {
                            "id": record.get("id"),
                            "fromId": record.get("fromId"),
                            "toId": record.get("toId"),
                            "chat": plaintext,
                            "createTime": create_time,
                        }
                    )
                except Exception as e:
                    # 单条记录处理失败时继续处理其他记录
                    print(f"[记录处理错误] {e}")

            return _make_resp(1, "ok", {"records": records_ret})
        else:
            return _make_resp(0, "无法获取聊天记录: 后端非200响应", None, 500)

    except Exception as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


if __name__ == "__main__":
    # 启动浏览器访问
    # webbrowser.open("http://127.0.0.1:5000")

    # 如需要开启两个客户端，可以复制一摸一样的命名为 main.py，修改端口
    app.run(host=host, port=port, debug=True)
