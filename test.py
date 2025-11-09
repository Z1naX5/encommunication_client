import requests
import json
import time

base_url = "http://127.0.0.1:5000"


def test_register():
    """测试注册接口"""
    print("\n=== 测试注册接口 ===")
    payload = {"username": "testuser", "password": "123456", "repassword": "123456"}
    res = requests.post(f"{base_url}/api/register", json=payload)
    print("注册返回：", res.json())
    return res.json().get("code") == 1


def test_login():
    """测试登录接口"""
    print("\n=== 测试登录接口 ===")
    payload = {"username": "aaa", "password": "aaa"}
    res = requests.post(f"{base_url}/api/login", json=payload)
    print("登录返回：", res.json())
    if res.status_code == 200:
        return res.json().get("data")["token"]
    return None


def test_online_users(token):
    """测试获取在线用户接口"""
    print("\n=== 测试获取在线用户 ===")
    headers = {"token": token}
    res = requests.get(f"{base_url}/api/online_users", headers=headers)
    print("在线用户返回：", res.json())
    return res.status_code == 200


def test_send_message(token, from_id, to_id):
    """测试发送消息接口"""
    print("\n=== 测试发送消息 ===")
    headers = {"token": token}
    data = {
        "from_id": from_id,
        "target_id": to_id,
        "message": "Hello, this is a test message!",
    }

    res = requests.post(f"{base_url}/api/send_message", json=data, headers=headers)
    print("发送消息返回：", res.json())
    if res.status_code != 200:
        print("发送消息失败:", res.text)
    return res.status_code == 200


def test_chat_records(token, from_id, to_id):
    """测试获取聊天记录接口"""
    print("\n=== 测试获取聊天记录 ===")
    headers = {"token": token}
    params = {"fromId": from_id, "toId": to_id}
    res = requests.get(f"{base_url}/api/chat/records", headers=headers, params=params)
    print("聊天记录返回：", res.json())
    return res.status_code == 200


def main():
    # # 测试注册
    # if test_register():
    #     print("注册成功")
    # else:
    #     print("注册失败，可能用户已存在")

    # 测试登录
    token = test_login()
    if not token:
        print("登录失败")
        return

    # 测试获取在线用户
    if test_online_users(token):
        print("获取在线用户成功")
    else:
        print("获取在线用户失败")

    # 测试发送消息
    from_id = 1  # 假设发送者ID为1
    to_id = 2  # 假设接收者ID为2
    if test_send_message(token, from_id, to_id):
        print("发送消息成功")
    else:
        print("发送消息失败")

    time.sleep(10)

    # 测试获取聊天记录
    if test_chat_records(token, from_id=1, to_id=2):
        print("获取聊天记录成功")
    else:
        print("获取聊天记录失败")


if __name__ == "__main__":
    main()
