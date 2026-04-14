# Changelog - firstbranch

本文档记录 `firstbranch` 分支相对于 `main` 分支的所有功能更新。

---

## [Unreleased] - 2026-04-14

### Added

#### 1. 并发消息处理

**文件**: `websocket_server.py`

实现了高效的并发消息处理架构：

- **信号量限制**：使用 `asyncio.Semaphore(3)` 限制最大并发数为 3，防止 LLM API 限流
- **用户锁机制**：使用 `user_locks` 字典为每个用户/群组创建独立锁，保证同一用户消息串行处理
- **任务跟踪**：使用 `tasks` 集合跟踪所有活跃任务，支持优雅关闭

**核心组件**：
```python
semaphore = asyncio.Semaphore(3)                    # 限制最大并发数
user_locks: dict[str, asyncio.Lock] = {}            # 用户锁字典
tasks: set[asyncio.Task] = set()                    # 活跃任务集合
```

**调度流程**：
```
消息到达 → 创建任务 asyncio.create_task() → 立即返回继续接收
                ↓
         获取信号量许可（最多3个并发）
                ↓
         获取用户锁（保证同用户串行）
                ↓
         调用 LLM → 发送回复 → 释放锁 → 释放信号量
```

#### 2. 聊天历史功能

**文件**: `websocket_server.py`, `llm.py`

为每个用户/群组维护对话上下文：

- **私聊历史**：key = `private:{user_id}`
- **群聊历史**：key = `group:{group_id}:{user_id}`（每个用户独立历史）
- **存储策略**：
  - 滑动窗口：最多 20 条消息
  - 时间过期：7 天无活动删除
- **历史裁剪**：超过 20 条时删除最早的 2 条

**新增全局变量**：
```python
conversation_history: dict[str, list] = {}  # 对话历史
last_activity: dict[str, float] = {}       # 上次活跃时间戳
MAX_HISTORY = 20                            # 最大消息数
MAX_HISTORY_AGE = 7 * 24 * 3600           # 7天过期（秒）
```

**新增函数**：
- `get_history_key(data)` - 获取对话历史的 key

**LLM 修改**：
- `chat()` 方法新增 `history` 参数支持
- 新增 `chat_with_history()` 方法，直接使用预构建消息列表

#### 3. 教育文档

**文件**: `docs/concurrency-guide-for-beginners.md`

用简单易懂的方式解释并发概念：

- **生活类比**：餐厅厨房、奶茶店、公共厕所
- **核心概念**：
  - Asyncio（异步编程）
  - Task（任务）
  - Semaphore（信号量）
  - Lock（锁）
  - Tasks Set（任务集合）
- **完整流程图解**：展示消息从到达→调度→并发控制→LLM调用→回复的完整流程
- **日志解读**：说明 `[调度]`、`[并发]`、`[LLM]` 等日志的含义

### Fixed

#### 1. 自消息过滤

**文件**: `websocket_server.py`

添加了 `user_id == bot_self_id` 检查，防止机器人处理自己发送的消息导致死循环。

#### 2. 消息解析增强

**文件**: `websocket_server.py`

增强了 CQ 码解析和列表格式消息的处理：

- 正确解析 `[CQ:at,qq=xxx]` 格式的 @ 消息
- 正确处理数组格式的消息段 `[{type:"at",...}, {type:"text",...}]`
- 忽略 @ 消息段中的内容，只提取纯文本

#### 3. 用户锁内存泄漏修复

**文件**: `websocket_server.py`

添加了锁的清理逻辑：

```python
# 清理不再使用的锁，防止字典无限增长
if key in user_locks and not user_locks[key].locked():
    del user_locks[key]
```

#### 4. LLM 重试逻辑

**文件**: `websocket_server.py`

实现了健壮的重试机制：

- 最多 3 次尝试（1 次原始 + 2 次重试）
- 每次重试都有明确的日志输出
- 最终失败后返回友好错误消息

---

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `websocket_server.py` | 修改 | 并发处理 + 聊天历史 |
| `llm.py` | 修改 | 新增 `history` 参数和 `chat_with_history()` 方法 |
| `mcp_config.json` | 新增 | MCP 服务器配置 |
| `docs/concurrency-guide-for-beginners.md` | 新增 | 并发编程教育文档 |

---

## 待办事项

- [ ] 实现消息持久化（历史存文件，重启后可恢复）
- [ ] 添加单元测试
- [ ] 实现优雅关闭（服务器收到信号后取消所有任务）
- [ ] 添加配置项（并发数、历史上限等）

---

## 分支信息

- **分支名**: `firstbranch`
- **基于**: `main`
- **创建时间**: 2026-04-14
