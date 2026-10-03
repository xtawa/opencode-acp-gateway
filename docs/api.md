# API

所有 `/v1/*` 接口必须提供 `Authorization: Bearer <key>`，管理员 Cookie 不能替代应用 Key。

| 接口 | 用途 |
| --- | --- |
| `GET /v1/models` | Key 可访问的已同步、启用模型，含别名 |
| `POST /v1/chat/completions` | 普通 JSON 或 SSE 对话 |
| `GET /healthz` | 网关进程存活检查，不代表外部模型当前可用 |

对话必填 `model/messages`，可选 `stream`、`stream_options.include_usage`、`tools`、`tool_choice`、`response_format`、`reasoning_effort`、`user`。`user` 仅为兼容接收，不用于计费/持久化。未知字段明确拒绝。

消息接受字符串、仅含 `{type:"text",text:"..."}` 的列表或 null，以及 name、历史 tool_calls、tool_call_id。历史经过提示桥接，不等同于原生角色 API。

工具格式为 `{type:"function",function:{name,description,parameters}}`。tool_choice 支持 auto/none/required 或指定函数。网关检验 Schema、函数名称和参数，客户端执行并在后续请求附带结果。无法满足结构时返回错误，不执行命令。

response_format.type 接受 text/json_object/json_schema；Schema 位于 response_format.json_schema.schema。结果先经过校验，这是提示与验证机制，不是提供商原生约束解码。

普通回复含 choices[0].message，有推理时附 reasoning_content。工具意图含 tool_calls、字符串化 function.arguments 和 finish_reason=tool_calls。ACP 未报告用量时省略 usage。

SSE 每个事件为 `data: <JSON>\n\n`，完成后为 `data: [DONE]\n\n`。请求 include_usage 时，有真实用量才发送 choices=[] 的 usage chunk。JSON/工具模式缓冲校验后发送。客户端必须检查流内 error，不能把 DONE 单独当作成功依据。

错误格式为 `{"error":{"message":"...","type":"gateway_error","code":"..."}}`。400 参数非法/不支持；401 Key 无效；403 白名单/数据政策；404 无模型；409 渠道忙；429 准入限额；502 上游/协议/输出校验；504 超时。流建立后错误转为 SSE，无法改变 HTTP 200。

## 管理接口

同源 WebUI 使用 HttpOnly 会话 Cookie，已认证写操作需 X-CSRF-Token；Origin 与公开 Origin 或当前请求 Origin 一致，不开放跨站管理 CORS。

| 接口 | 用途 |
| --- | --- |
| `GET/POST /api/setup` | 状态 / 一次性初始化，POST 需本机引导令牌 |
| `POST /api/login`、`GET /api/me`、`POST /api/logout` | 登录 / 当前身份与 CSRF / 退出 |
| `POST /api/password` | 原密码验证后改密，撤销全部会话 |
| `GET /api/overview`、`GET /api/settings`、`GET /api/audit` | 统计 / 部署状态 / 审计 |
| `GET/POST /api/channels`、`PUT/DELETE /api/channels/{id}` | 列表 / 新增 / 修改 / 删除 |
| `POST /api/channels/{id}/sync`、`POST /api/channels/{id}/test` | 同步 / 单次测试 |
| `GET/POST /api/keys`、`PUT/DELETE /api/keys/{id}` | 列表 / 新增 / 修改 / 撤销 |
| `GET /api/logs` | 分页、状态与模型筛选 |

Key 只在创建时显示完整值；凭据与代理 URL 不回显。凭据 null 保持、{} 清除；代理空值保持、- 清除。修改渠道后重新同步，有请求预留/排队/运行时禁止修改。
