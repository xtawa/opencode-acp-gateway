# API

所有 `/v1/*` 接口必须提供 `Authorization: Bearer <key>`，管理员 Cookie 不能替代应用 Key。

| 接口 | 用途 |
| --- | --- |
| `GET /v1/models` | Key 可访问的已同步、启用模型，含别名 |
| `POST /v1/chat/completions` | 普通 JSON 或 SSE 对话 |
| `POST /v1/responses` | 无状态 Responses 普通 JSON 或标准事件 SSE |
| `GET /healthz` | 网关进程存活检查，不代表外部模型当前可用 |

对话必填 `model/messages`，可选 `stream`、`stream_options.include_usage`、`tools`、`tool_choice`、`response_format`、`reasoning_effort`、`user`。`user` 仅为兼容接收，不用于计费/持久化。未知字段明确拒绝。

消息接受字符串、仅含 `{type:"text",text:"..."}` 的列表或 null，以及 name、历史 tool_calls、tool_call_id。历史经过提示桥接，不等同于原生角色 API。

工具格式为 `{type:"function",function:{name,description,parameters}}`。tool_choice 支持 auto/none/required 或指定函数。网关检验 Schema、函数名称和参数，客户端执行并在后续请求附带结果。无法满足结构时返回错误，不执行命令。

response_format.type 接受 text/json_object/json_schema；Schema 位于 response_format.json_schema.schema。结果先经过校验，这是提示与验证机制，不是提供商原生约束解码。

普通回复含 choices[0].message，有推理时附 reasoning_content。工具意图含 tool_calls、字符串化 function.arguments 和 finish_reason=tool_calls。ACP 未报告用量时省略 usage。

SSE 每个事件为 `data: <JSON>\n\n`，完成后为 `data: [DONE]\n\n`。请求 include_usage 时，有真实用量才发送 choices=[] 的 usage chunk。JSON/工具模式缓冲校验后发送。客户端必须检查流内 error，不能把 DONE 单独当作成功依据。

错误格式为 `{"error":{"message":"...","type":"gateway_error","code":"..."}}`。400 参数非法/不支持；401 Key 无效；403 白名单/数据政策；404 无模型；409 渠道忙；429 准入限额；502 上游/协议/输出校验；504 超时。流建立后错误转为 SSE，无法改变 HTTP 200。

## Responses

必填 `model/input`，`input` 可以是文本字符串或包含完整会话历史的消息列表。文本块接受 `input_text/output_text`，保留 system/developer/user/assistant 角色；`instructions` 作为系统指令。也接受 `function_call` 和对应 `function_call_output`，调用 ID 在历史中保留。输出 item 可回填下一次请求的 input。

可选 `stream`、`store:false`、`background:false`、`truncation:"disabled"`、`tools`、`tool_choice`、`text.format`、`reasoning.effort/summary`、`user/safety_identifier`。省略 store 时也不保存正文，响应始终声明 store:false。标识字段仅接收，不用于计费或持久化。

Responses 的函数工具使用扁平格式 `{type:"function",name,description,parameters,strict}`，指定工具为 `{type:"function",name}`。JSON Schema 使用 `text.format:{type:"json_schema",name,schema,strict}`，也接受 text/json_object。与 Chat 共用名称、参数和输出校验；strict 通过提示及输出验证实现。工具只返回调用意图，由客户端执行。

普通响应为 `object:"response"`，正文在 `output` 的 message/content/output_text 中，工具在 function_call item 中。有真实用量才填写 usage，否则为 null。请求 reasoning.summary=auto/concise/detailed 时将 ACP 实际推理文本映射为 reasoning/summary_text，并不生成额外的摘要。

流事件使用 `event: <type>\ndata: <JSON>\n\n`，包含连续递增 sequence_number。依次发送 response.created/in_progress、item/part 创建与增量、done 和最终 response.completed；截断发送 response.incomplete。函数参数在校验后发送 function_call_arguments.delta/done。最终事件含完整 response 和实际 usage，不使用 Chat 的 `[DONE]`。流内失败发送 error 和 response.failed，客户端需检查最终状态。

与 Chat 共用鉴权、模型范围和原子配额预留。每次请求新建 ACP 会话并在结束、失败或断开后清理。仅支持无状态用法：客户端提交完整历史；store:true、previous_response_id、Conversations、后台任务、托管工具、图片/音频、encrypted_content 和无法映射的采样/Token 上限参数返回 400，且不消费配额。实现格式依据 [OpenAI 官方 Responses 文档](https://developers.openai.com/api/reference/python/resources/responses/methods/create)。

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
