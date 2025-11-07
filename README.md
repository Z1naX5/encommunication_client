# encommunication_client

供小组作业协作使用

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

## 客户端

login/register 功能接口标准同后端
