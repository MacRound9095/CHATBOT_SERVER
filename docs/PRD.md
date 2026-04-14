# MiniMax QQ Robot WebSocket Server - 产品需求文档

## 1. Executive Summary

### Problem Statement

当前的 QQ 机器人无法高效处理多用户并发消息，且每次对话都是孤立的，用户无法进行上下文连续的对话交流。

### Proposed Solution

构建一个基于 WebSocket 的 QQ 机器人后端服务，集成 MiniMax LLM 和 MCP 协议，实现：
- 多用户并发消息处理
- 聊天历史上下文维护
- 外部工具调用能力

### Success Criteria

| 指标 | 目标值 |
|------|--------|
| 消息响应延迟 | < 500ms（不含 LLM 调用时间） |
| 最大并发数 | 3 个并发消息处理 |
| 历史上限 | 每对话 20 条消息 |
| 历史过期时间 | 7 天无活动 |

---

## 2. User Experience & Functionality

### User Personas

1. **普通用户**：通过 QQ 与机器人进行日常对话，获取信息
2. **群组用户**：在群聊中 @ 机器人进行问答
3. **开发者**：配置和维护 MCP 服务器，扩展机器人能力

### User Stories

| 角色 | 需求 | 验收标准 |
|------|------|----------|
| 普通用户 | 我想通过私聊向机器人提问 | 机器人能正确回复私聊消息 |
| 群组用户 | 我想在群聊中 @ 机器人提问 | 机器人只回复 @ 它的消息 |
| 普通用户 | 我想进行连续对话 | 机器人能记住之前的对话内容 |
| 群组用户 | 我想在群中和机器人对话 | 群内每个用户的对话历史独立 |
| 开发者 | 我想扩展机器人能力 | 可以通过 MCP 添加新工具 |
| 用户 | 我想查看机器人功能 | `/help` 指令能显示帮助信息 |

### Non-Goals

- 不支持消息撤回、已读回执等高级功能
- 不实现消息持久化存储（历史仅存内存）
- 不支持语音消息处理

---

## 3. AI System Requirements

### Tool Requirements

| 工具 | 用途 | 必需 |
|------|------|------|
| MiniMax API | LLM 对话能力 | 是 |
| BangumiMCP | 番剧信息查询 | 否（可配置） |
| WebSearch MCP | 网络搜索 | 否（可配置） |

### Evaluation Strategy

- **功能测试**：每条指令和消息类型都有正确的响应
- **并发测试**：多用户同时发送消息，确认无消息丢失或顺序错乱
- **历史测试**：连续对话 3 轮以上，确认上下文正确传递

---

## 4. Technical Specifications

### Architecture Overview

```
                    ┌─────────────────┐
                    │   QQ Client     │
                    └────────┬────────┘
                             │ WebSocket
                             ▼
┌──────────────────────────────────────────────────────┐
│              WebSocket Server (8080)                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   Handler   │→ │   Process   │→ │   LLM       │  │
│  │  (消息路由)  │  │  (并发处理)  │  │  (对话+工具) │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│         │                │                │         │
│         ▼                ▼                ▼         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │  Filter     │  │ Semaphore   │  │   MCP       │  │
│  │ (自消息过滤) │  │  Lock       │  │  Manager    │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
└──────────────────────────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  External MCP   │
                    │  Servers        │
                    └─────────────────┘
```

### Component Specifications

#### WebSocket Server

- **端口**：8080
- **协议**：OneBot v11 WebSocket
- **消息格式**：JSON

#### Concurrency Manager

- **信号量**：限制 3 个并发
- **用户锁**：每个用户/群组独立锁
- **任务跟踪**：使用 Task Set 管理活跃任务

#### History Manager

- **存储**：内存字典
- **Key 格式**：
  - 私聊：`private:{user_id}`
  - 群聊：`group:{group_id}:{user_id}`
- **容量**：每对话最多 20 条消息
- **过期**：7 天无活动删除

#### LLM Client

- **模型**：MiniMax-M2.7
- **超时**：30 秒
- **最大轮次**：20 轮工具调用
- **重试**：最多 3 次（1 次原始 + 2 次重试）

### Integration Points

| 集成点 | 协议 | 说明 |
|--------|------|------|
| QQ Robot | WebSocket | 接收消息，发送回复 |
| MiniMax API | HTTP | LLM 对话 |
| MCP Servers | Subprocess + JSON-RPC | 工具调用 |

### Security & Privacy

- **自消息过滤**：不处理机器人自己发送的消息，防止死循环
- **API Key**：使用环境变量或默认 key
- **数据保留**：历史仅存内存，服务器重启后丢失

---

## 5. Risks & Roadmap

### Phased Rollout

| 阶段 | 功能 | 状态 |
|------|------|------|
| MVP | 基础 WebSocket + LLM 对话 | ✅ 已完成 |
| v1.1 | 并发消息处理 | ✅ 已完成 |
| v1.2 | 聊天历史 | ✅ 已完成 |
| v1.3 | MCP 工具集成 | ✅ 已完成 |
| v2.0 | 消息持久化 | 待定 |
| v2.1 | 多机器人支持 | 待定 |

### Technical Risks

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM API 限流 | 消息处理失败 | 信号量限制并发 + 重试机制 |
| 内存溢出 | 历史过多 | 滑动窗口 + 过期清理 |
| WebSocket 断开 | 消息丢失 | 客户端自动重连 |

---

## 6. Configuration

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMAX_API_KEY` | 代码内置 | MiniMax API 密钥 |

### MCP 配置 (mcp_config.json)

```json
{
  "mcpServers": {
    "bangumi": {
      "command": "uv",
      "args": ["--directory", "BangumiMCP", "run", "main.py"],
      "env": {},
      "timeout": 60,
      "disabled": false
    }
  }
}
```

---

## 7. Log Reference

### 日志标签

| 标签 | 含义 |
|------|------|
| `[连接]` | WebSocket 连接状态 |
| `[调度]` | 新任务创建 |
| `[并发]` | 锁获取/释放 |
| `[LLM]` | LLM API 调用 |
| `[MCP]` | MCP 工具调用 |
| `[重试]` | LLM 重试 |
| `[错误]` | 异常发生 |
| `[历史]` | 历史管理操作 |

### 示例日志

```
[连接] 客户端连接
[调度] 开始处理 private:12345
[并发] 获取锁 private:12345，开始处理
[LLM] 调用 LLM: 你好...
[MCP] 调用: search_subjects {"keyword": "海贼王"}
[MCP] 结果: {"name": "海贼王", "id": 1000}...
[回复] 你好！有什么可以帮助你的吗？
[历史] 保存历史 private:12345，共 2 条消息
[并发] 处理完成 private:12345
```
