# encommunication_client

供小组作业协作使用

架构：java 应用作为后端和 flask 应用（这个 python 项目，作为本地客户端）通信，flask 应用再和本地网页服务（js/html）通信（示例：login 与 register 功能）

## TODO:

1.上传不同类型的文件（图片、视频前端应该是转成字符串传给 flask 应用）

2.完善前端 login 页面，能够自动跳转下一页面

3.编写前端 index 页面，内容是当前在线用户，点击即可进入 chat 页面；每五秒轮询当前在线人/或添加一个刷新按钮用于更新当前在线用户

4.编写前端 chat 页面，可以发送消息，有一个按钮/其他交互方式用于获取聊天记录并正确显示在聊天框中

5.实时接收消息，（我忘了把收到的消息像在线用户一样同步出来，晚点补上）

## Flask 应用端口规范：

以下为 `main.py` 中定义的后端接口（Flask 路由），并统一说明请求（Request）与回包（Response）格式。
依赖库见 requirements.txt

### 统一返回格式

所有接口均使用统一的 JSON 返回格式：

{
"code": 1 | 0, // 1 表示成功，0 表示失败
"msg": "描述信息",
"data": {...} | null
}

HTTP 状态码会根据场景设置（例如 200 / 400 / 500）。

### 路由一览

1. 登录

- 路由：POST /api/login
- 请求 body (JSON):
  {
  "username": "用户名称",
  "password": "密码"
  }
- 成功响应 (HTTP 200):
  {
  "code": 1,
  "msg": "登录成功",
  "data": {"token": "..."}
  }
- 失败响应示例 (HTTP 400/500):
  {
  "code": 0,
  "msg": "错误描述",
  "data": null
  }
- 说明：该接口会代理到后端服务 /login，并在成功后为该用户创建并启动一个 `WSClient` 实例（用于 WebSocket 连接）。

2. 注册

- 路由：POST /api/register
- 请求 body (JSON):
  {
  "username": "用户名称",
  "password": "密码",
  "repassword": "确认密码"
  }
- 成功响应 (HTTP 200):
  {
  "code": 1,
  "msg": "注册成功",
  "data": { ... 后端返回的数据 ... }
  }
- 失败响应 (HTTP 400/500):
  {
  "code": 0,
  "msg": "注册失败的描述",
  "data": null
  }
- 说明：注册时会本地生成/加载 RSA 密钥对，并将公钥发送给后端注册接口。

3. 获取在线用户

- 路由：GET /api/online_users
- 请求参数：无
- 成功响应 (HTTP 200):
  {
  "code": 1,
  "msg": "ok",
  "data": {"users": {"id": "username", ...}}
  }

4. 发送加密消息（HTTP API -> 客户端 WSClient）

- 路由：POST /api/send_message
- 请求 body (JSON):
  {
  "from_id": <发送者 id>,
  "target_id": <接收者 id>,
  "message": "明文消息"
  }
- 成功响应 (HTTP 200):
  { "code": 1, "msg": "ok", "data": null }
- 失败响应 (HTTP 400/500):
  { "code": 0, "msg": "错误描述", "data": null }
- 说明：该接口找到对应的 `WSClient`（由登录创建），如果 WSClient 未连接会尝试启动并等待短时连接，再将消息加入客户端的发送流程（会在必要时进行密钥交换并入队列）。

5. 获取聊天记录

- 路由：GET /api/chat/records
- 请求参数（query）:
  - fromId: int（请求方 id）
  - toId: int（目标用户 id）
- 成功响应 (HTTP 200):
  {
  "code": 1,
  "msg": "ok",
  "data": {"records": [ {"id":..., "fromId":..., "toId":..., "chat":"明文或错误标记", "createTime":...}, ... ] }
  }
- 失败响应 (HTTP 400/500):
  { "code": 0, "msg": "错误描述", "data": null }
- 说明：接口会代理请求到后端 `/chatRecords`，并尝试使用本地私钥解密每条记录中的 AES 密钥（会尝试 `toAesKey`、`fromAesKey` 两个字段），再用 AES 解密聊天内容。如果解密失败，会把 `chat` 字段标记为 `[无法解密消息]` 或 `[解密失败]`。

6. SSE 数据流订阅 (Server-Sent Events)

- 路由：GET /api/stream
- 请求参数：无
- 响应类型：text/event-stream
- 响应格式：
  ```
  data: {"消息内容..."}\n\n
  ```
- 说明：
  - 浏览器通过 EventSource 订阅此端点接收服务器推送的消息
  - 连接会保持打开状态，服务器可以持续推送数据
  - 每条消息以 `\n\n` 结尾（SSE 标准格式）
  - JavaScript 使用示例：
    ```javascript
    const evtSource = new EventSource("/api/stream");
    evtSource.onmessage = function (event) {
      const data = JSON.parse(event.data);
      console.log("收到服务器推送:", data);
    };
    ```

7. 消息推送接口（注：前端用不到，这是一个暂时仅用于客户端内部的接口）

- 路由：POST /push
- 请求 body (JSON): 任意 JSON 数据（将被推送给所有 SSE 订阅者）
- 成功响应:
  ```json
  { "status": "ok" }
  ```
- 说明：
  - 此接口供 WebSocket 客户端或内部服务调用
  - 接收到的消息会通过 SSE 推送给所有订阅的浏览器
  - 消息进入队列（Queue）后异步推送

### 关于实时消息推送

系统使用 Server-Sent Events (SSE) 实现服务器向浏览器的实时消息推送：

- 系统使用 Queue 在 WebSocket 接收端和 SSE 推送端之间传递消息
- SSE 连接保持长期开启，支持自动重连
- 每个浏览器客户端通过 EventSource 订阅，可以接收所有推送的消息
- 适用于：聊天消息通知、在线状态更新等需要服务器主动推送的场景

### 关于 WebSocket (WSClient)

- `main.py` 在登录成功后会创建 `WSClient(user_id, username, token)` 并启动：客户端会使用 token 与后端建立 WebSocket 连接，用于接收在线用户信息、密钥交换与消息转发。
- API `/api/send_message` 是把应用层的发送请求转给本地 `WSClient`，实际的加密/密钥交换在客户端内部完成。

## 后端端口规范：

### [GET]/[POST]:

https://s.apifox.cn/d34324e0-c753-4422-b89d-13db913b8d40/367349531e0

### web_sockert:

#### 前端->后端数据格式

{"fromId": 1,"toId": 3,"message": "你好","aesKey":"123"}

#### 后端->前端数据格式

##### websocket 连接成功时返回数据格式

（张三登录/上线/建立 websocket 连接后会向所有此时已经建立 websocket 的用户发送如下消息列表告诉所有人此时列表中的人都处于上线状态，允许向列表中的任意用户发送消息，这是系统消息，所以 systemMessage 是 true，列表中任意下线之后也会重新发送新的在线用户列表）

{"message":[{"id":1,"publicKey":"12345","enpublicKey":"12345en","username":"张三"}],"systemMessage":true}

##### 连接成功后进行通信

（id 为 1 的用户向本人发送了一条消息"你好"）

{"fromId":1,"message":"你好","aesKey":"123",systemMessage":false}
