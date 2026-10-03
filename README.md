# OpenCode ACP Gateway

独立部署的 OpenCode ACP → OpenAI 兼容网关，配有参考 New API 信息架构的管理控制台。

项目正在实现：官方 ACP 子进程管理、模型与渠道配置、API Key、流式对话、真实用量统计、访问日志及 Linux Docker 部署。

无需安装 MaiBot 或 AstrBot。核心桥接机制从已有 MaiBot OpenCode ACP 插件抽离；网关不会继承原插件的运行数据、账号或密钥。

## 设计来源

- [OpenCode ACP](https://opencode.ai/docs/acp/)
- [Agent Client Protocol](https://agentclientprotocol.com/protocol/prompt-turn)
- [New API](https://github.com/QuantumNous/new-api)：仅作为界面信息架构参考，不复制其实现。
