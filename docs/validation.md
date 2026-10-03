# 验证记录

日期：2026-10-03。独立本地数据目录，未改动现有 MaiBot、AstrBot 或服务器生产服务。

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
