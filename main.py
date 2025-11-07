import webbrowser
from flask import Flask, render_template, request, jsonify
from ws_client import WSClient
import requests
from crypto_utils import load_or_generate_keys, serialize_public_key

app = Flask(__name__)
ws_clients = {}  # username -> WSClient实例
server_address = "192.168.1.2:8080"
CHAT_RECORDS_FILE = "chat_records.json"


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
                print(user_id, token)
                username = user_data.get("userName")

                client = WSClient(user_id, username, token)
                ws_clients[username] = client
                client.start()

                return jsonify({"token": token, "message": "登录成功"})
            else:
                return jsonify({"error": "后端未返回有效的code"}), 400
        else:
            error_data = response.json()
            return jsonify(
                {"error": error_data.get("error", "登录失败")}
            ), response.status_code

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"无法连接到后端服务器: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"服务器错误: {str(e)}"}), 500


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
        print(payload)
        response = requests.post(
            backend_url, json=payload, headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@app.route("/api/send_message", methods=["POST"])
def send_message():
    data = request.json
    username = data["username"]
    target_id = data["target_id"]
    message = data["message"]

    client = ws_clients.get(username)
    if client:
        client.send_encrypted_message(target_id, message)
        return jsonify({"status": "ok"})
    return jsonify({"status": "fail", "reason": "no client"})


@app.route("/api/chat/records", methods=["GET"])
def get_chat_records():
    backend_url = f"http://{server_address}/chatRecords"
    try:
        from_id = request.args.get("fromId")
        to_id = request.args.get("toId")

        if not all([from_id, to_id]):
            return jsonify({"code": 0, "msg": "缺少必要参数", "data": None}), 400

        # 加载记录
        records = load_chat_records()

        # 筛选记录
        filtered_records = [
            record
            for record in records["records"]
            if (record["fromId"] == int(from_id) and record["toId"] == int(to_id))
            or (record["fromId"] == int(to_id) and record["toId"] == int(from_id))
        ]

        return jsonify(
            {
                "code": 1,
                "msg": None,
                "data": {"total": len(filtered_records), "records": filtered_records},
            }
        )

    except Exception as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


if __name__ == "__main__":
    # 启动浏览器访问
    # webbrowser.open("http://127.0.0.1:5000")
    app.run(debug=True)
