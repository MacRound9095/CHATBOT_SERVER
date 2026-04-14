# MiniMax QQ Robot WebSocket Server

QQ 机器人 WebSocket 服务器，基于 MiniMax LLM 和 MCP 协议，支持并发处理和聊天历史。

## 功能特性

- **WebSocket 消息接收**：通过 WebSocket 接收 QQ 机器人推送的消息
- **LLM 智能对话**：集成 MiniMax LLM，支持自然语言对话
- **MCP 工具调用**：通过 MCP 协议调用外部工具（如 Bangumi 番剧查询）
- **并发消息处理**：不同用户/群组的消息并发处理，同一用户消息串行处理
- **聊天历史**：为每个用户/群组维护对话上下文
- **命令系统**：支持 `/help`、`/mcp`、`/tools`、`/reload` 等指令

## 项目架构

```
CHATBOT_SERVER/
├── websocket_server.py    # WebSocket 服务器主程序
├── llm.py                 # MiniMax LLM 客户端 + MCP 集成
├── mcp.py                 # MCP 协议客户端和服务器管理器
├── mcp_config.json        # MCP 服务器配置
├── docs/
│   └── concurrency-guide-for-beginners.md  # 并发编程入门指南
└── BangumiMCP/           # Bangumi MCP 服务器（子模块）
```

## 快速开始

### 前置要求

- Python 3.10+
- 一键通哥 OneBot 兼容的 QQ 机器人（如 napcat）
- MiniMax API Key

### 安装依赖

```bash
pip install websockets aiohttp
```

### 配置

1. 编辑 `mcp_config.json` 配置 MCP 服务器
2. 设置环境变量 `MINIMAX_API_KEY`（可选，代码中有默认 key）

### 运行

```bash
python websocket_server.py
```

## 协议说明

服务器接收 JSON 格式的 WebSocket 消息，示例：

```json
{
  "post_type": "message",
  "message_type": "private",
  "user_id": 123456,
  "message": "你好",
  "self_id": 2947673606
}
```

详细协议见 [docs/MESSAGE.md](docs/MESSAGE.md)。

## 并发处理

服务器使用 asyncio 实现了高效的并发处理：

- **信号量（Semaphore）**：限制最大并发数为 3，防止 API 限流
- **用户锁（User Lock）**：保证同一用户/群组的消息按顺序处理
- **任务集合（Task Set）**：跟踪活跃任务，支持优雅关闭

详见 [docs/concurrency-guide-for-beginners.md](docs/concurrency-guide-for-beginners.md)。

## 聊天历史

服务器为每个用户/群组维护对话历史：

- **私聊**：每用户独立历史（key = `private:{user_id}`）
- **群聊**：每用户在群内独立历史（key = `group:{group_id}:{user_id}`）
- **存储策略**：滑动窗口（最多 20 条）+ 7 天过期

## 指令系统

| 指令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/mcp` | 查看已配置的 MCP 服务器 |
| `/tools` | 查看已发现的工具 |
| `/reload` | 重启 MCP 服务器 |

## MCP 配置

编辑 `mcp_config.json`：

```json
{
  "mcpServers": {
    "bangumi": {
      "command": "uv",
      "args": ["--directory", "BangumiMCP", "run", "main.py"],
      "env": {}
    }
  }
}
```

## 开发

### 代码结构

- `websocket_server.py`：WebSocket 服务器，处理消息路由和并发
- `llm.py`：LLM 客户端，封装 API 调用和工具调用
- `mcp.py`：MCP 协议实现，管理 MCP 服务器连接

### 添加新功能

1. 消息类型处理：在 `handler()` 中添加新的过滤逻辑
2. 指令处理：在 `handle_command()` 中添加新指令
3. MCP 工具：在 `mcp_config.json` 中配置新的 MCP 服务器

## 许可证

MIT