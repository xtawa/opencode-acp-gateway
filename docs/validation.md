# 验证记录

日期：2026-10-03。以下 v0.1.0 初始验证使用独立本地数据目录；v0.1.1 的服务器回归记录另列在文末。

## 自动验证

- Python：31 个测试通过，覆盖认证/CSRF、哈希与加密、撤销/到期/白名单、原子限额、参数拒绝、JSON/工具校验、元数据、用量与错误恢复。
- ACP 测试使用真实 stdio 模拟子进程，验证会话分流、权限拒绝、取消/关闭/HTTP 删除、清理失败报错和服务器取消作用域下的清理。
- 前端：2 个 SSE 测试通过，覆盖 UTF-8 分片、DONE 和非法 JSON；TypeScript 检查与 Vite 生产构建通过。
- Linux Actions 已通过：Docker 构建、Compose 校验、容器 WebUI/健康/引导令牌和捆绑 CLI 均成功。对应代码提交 `67d8bf7`，见 [工作流结果](https://github.com/xtawa/opencode-acp-gateway/actions/runs/37120701846)。

## 真实上游

官方 OpenCode 1.18.34，隔离运行目录和临时 Key。同步模型后，用别名 mimo-free 指向当时可用的 opencode/mimo-v2.6-flash-free。目录会变化，此记录不保证长期可用。

只发送公开测试指令 `Only reply with ACP_GATEWAY_OK.`：

| 模式 | 结果 | 耗时 | 首字延迟 | 实际 Token |
| --- | --- | --- | --- | --- |
| 普通 | HTTP 200，正确标记，stop | 18.64 s | 13.55 s | 8,043 |
| SSE | HTTP 200，正确标记，无 error，DONE | 7.94 s | 5.36 s | 8,043 |

每次 usage 为 prompt 8,021、completion 22、total 8,043，包含 16 reasoning tokens。提示用量包含 OpenCode 自身提示。临时 Key 已撤销，成功状态在会话清理后才写入。

真实测试证明普通/流式文本链路；工具/JSON 由模拟协议对端验证，不宣称全部模型稳定服从 Schema，也未验证跨机生产部署或多实例运行。

## 界面

使用真实后端数据检查桌面浅色/深色、390px 手机布局、导航抽屉与管理页面。

- [桌面浅色](screenshots/overview-light.jpg)
- [桌面深色](screenshots/overview-dark.jpg)
- [手机布局](screenshots/overview-mobile.jpg)

## v0.1.1 Responses 兼容

- 修复 Responses 客户端 POST /v1/responses 返回 405 的问题。两个对话接口共用 ACP 生成、配额和清理流程。
- 64 项后端测试通过，包含 33 项 Responses 测试：官方 SDK 严格对象校验、SSE 事件与累积器、输入角色和完整历史、函数意图回填、JSON Schema、跨接口限额、取消、错误、清理失败、截断与缺失用量。官方 Python SDK 3.22.1 完整套件通过，SDK 2.54.0 的 33 项 Responses 回归也通过。
- 2 项前端测试、Ruff、TypeScript 与生产构建通过。代码提交 `d99a23e` 的 [Linux Actions](https://github.com/xtawa/opencode-acp-gateway/actions/runs/37132631563) 已通过，含 Docker 构建和容器检查。
- 154.36.171.175 已部署 v0.1.1，公网 `https://oc-gateway.zcwww.cc` 证书校验与健康检查通过。仅更新 gateway 容器，现有 HTTPS 代理保持运行；未经授权的 Responses 请求返回 401。

通过公网 HTTPS 对截图中的 `opencode/muse-spark-1.3-contributor-free` 发送公开标记指令，普通和流式均得到正确标记及 completed 状态：

| Responses 模式 | 总耗时 | 文本首字 | input / output / total tokens |
| --- | --- | --- | --- |
| JSON | 2.31 s | 未单独测量 | 7,850 / 30 / 7,880 |
| SSE | 2.06 s | 1.91 s | 7,850 / 82 / 7,932 |

流事件编号连续，最终 usage 与元数据日志一致；验证结束后活跃请求为 0。临时测试 Key 已撤销、临时渠道已删除。原 OpenCode Zen 渠道的数据政策确认仍关闭，使用其免费模型前需由用户在 WebUI 明确勾选。
