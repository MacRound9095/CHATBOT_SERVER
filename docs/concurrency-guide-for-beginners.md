# 并发编程入门指南

> 用简单易懂的方式解释本程序中使用的并发概念

## 什么是并发？

### 生活中的类比：餐厅厨房

**串行处理**就像只有一位厨师的厨房：
- 厨师一次只能做一道菜
- 客人A点了宫保鸡丁，厨师开始做
- 在宫保鸡丁做好之前，客人B点的鱼香肉丝只能等着

**并发处理**就像有多位厨师的厨房：
- 厨师A做宫保鸡丁
- 同时，厨师B在做鱼香肉丝
- 不同的菜可以同时进行

---

## 本程序中的核心概念

### 1. 异步（Asyncio）

**什么是 asyncio？**

asyncio 是 Python 内置的异步编程库。"异步"意味着：
- 不需要等待一个操作完成就可以开始下一个
- 在等待期间可以去做其他事情

**本程序中的代码：**
```python
async def process_message(data, websocket):
    """这是一个异步函数"""
    response = await llm_client.chat(message)  # 等待 LLM 返回
    await websocket.send(...)  # 等待发送完成
```

**类比：**
- `await` 就像点餐后等待叫号
- 你不需要一直站在柜台前，可以坐着玩手机
- 被叫到时再过去取餐

---

### 2. 任务（Task）

**什么是 Task？**

Task 是 asyncio 中表示"一个异步执行单元"的方式。

**本程序中的代码：**
```python
# 在 handler() 中创建任务
asyncio.create_task(process_message(data, websocket))
```

**类比：**
- `asyncio.create_task()` 就像服务员收到订单后，把订单交给厨房
- 服务员不需要等菜做完，就可以继续接收下一个订单
- 厨房同时在处理多个订单

---

### 3. 信号量（Semaphore）

**什么是 Semaphore？**

Semaphore 是一个"计数器"，用来限制同时执行的操作数量。

**本程序中的代码：**
```python
semaphore = asyncio.Semaphore(3)  # 最多同时处理3个消息

async def process_message(data, websocket):
    async with semaphore:  # 获取许可
        # 处理消息...
```

**类比：**
- 想象一个只有3个座位的奶茶店
- 第1个人来，有座位，坐下点餐
- 第2个人来，有座位，坐下点餐
- 第3个人来，有座位，坐下点餐
- 第4个人来，没座位了，只能等
- 直到有人喝完离开，第4个人才能进去

**为什么需要限制？**
- LLM API 有 rate limit（每分钟最多调用多少次）
- 无限并发可能导致 API 被封禁
- 3个并发是安全和效率的平衡点

---

### 4. 锁（Lock）

**什么是 Lock？**

Lock 确保同一时间只有一个"执行单元"能访问某段代码。

**本程序中的代码：**
```python
user_locks: dict[str, asyncio.Lock] = {}  # 用户锁字典

# 在 process_message() 中
key = f"{message_type}:{target_id}"  # 私聊:用户ID 或 群聊:群ID
async with user_locks.setdefault(key, asyncio.Lock()):
    # 这个 block 里的代码，同一用户/群组的消息会串行执行
```

**类比：**
- 想象一个只有一个坑位的公共厕所
- 第1个人进去后会上锁
- 第2个人来，发现锁着，只能在门外等
- 第1个人出来后解锁，第2个人才能进去
- 不同的人可以去不同的厕所（不同的 key）

**为什么需要锁？**
- 同一用户的连续消息需要有顺序
- 否则回复顺序可能错乱："你好！"、"你是谁？"、"我叫小明"
- 可能变成："我叫小明"、"你好！"、"你是谁？"

---

### 5. 任务集合（Tasks Set）

**什么是 Tasks Set？**

用来跟踪所有正在运行的任务。

**本程序中的代码：**
```python
tasks: set[asyncio.Task] = set()  # 活跃任务集合

# 在 process_message() 中
task = asyncio.current_task()
if task:
    tasks.add(task)
    task.add_done_callback(tasks.discard)
```

**用途：**
- 记录当前有多少消息正在处理
- 服务器关闭时可以取消所有未完成的任务
- 监控并发状态

---

## 完整流程图解

```
消息1 (用户A) ──┐
消息2 (用户B) ──┼──→ handler() ──→ asyncio.create_task()
消息3 (用户A) ──┘                      │
                                      ▼
                           ┌─────────────────────┐
                           │  semaphore.acquire() │ ← 检查是否超过3个并发
                           └─────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
               用户A的锁           用户B的锁          用户C的锁
               (等待中)           (处理中)          (等待中)
                    │                 │                 │
                    ▼                 ▼                 │
               (获取锁)          LLM API 调用        ......|
                    │                 │                 │
                    ▼                 ▼                 ▼
               LLM API 调用 ─────→ 发送回复 ─────→ 释放锁
                    │                                   │
                    └───────────────────────────────────┘
                                      │
                           ┌─────────────────────┐
                           │  semaphore.release() │
                           └─────────────────────┘
```

---

## 关键代码解析

### 1. 全局变量定义
```python
llm_client = None          # LLM 客户端
bot_self_id = None         # 机器人自己的 ID

semaphore = None           # 信号量（限制并发数）
user_locks: dict[str, asyncio.Lock] = {}  # 用户锁字典
tasks: set[asyncio.Task] = set()          # 任务集合
```

### 2. 初始化信号量
```python
async def main():
    global semaphore
    semaphore = asyncio.Semaphore(3)  # 最多3个并发
```

### 3. 创建异步任务
```python
async def handler(websocket):
    async for raw_message in websocket:
        # ... 过滤和检查 ...
        asyncio.create_task(process_message(data, websocket))
        # 立即返回，继续接收下一条消息
```

### 4. 处理消息（带锁和信号量）
```python
async def process_message(data, websocket):
    key = f"{message_type}:{target_id}"  # 用户的唯一标识

    async with semaphore:  # 等待并发许可（最多等3个）
        async with user_locks.setdefault(key, asyncio.Lock()):  # 获取用户锁
            # 调用 LLM
            response = await llm_client.chat(message)
            # 发送回复
            await websocket.send(...)
```

### 5. 重试逻辑
```python
for attempt in range(3):  # 最多3次
    try:
        response = await llm_client.chat(message)
        break
    except Exception as e:
        if attempt < 2:
            print(f"[重试] 失败，第{attempt+1}次重试...")
        else:
            print(f"[错误] 最终失败")
            response = "❌ 服务暂时不可用"
```

---

## 常见问题

### Q: 并发和并行有什么区别？

**并行（Parallelism）**：真正同时执行，需要多个 CPU 核心
**并发（Concurrency）**：通过快速切换，看起来像同时执行

类比：
- 并发 = 一位厨师同时照顾多口锅（交替执行）
- 并行 = 多位厨师各自照顾一口锅（真正同时）

Python 的 asyncio 是**并发**，不是并行。

### Q: 信号量设为多少合适？

取决于：
- LLM API 的 rate limit
- 服务器的处理能力
- 网络延迟

本程序设为 3，是比较保守的数值。

### Q: 为什么要用锁限制同一用户串行？

因为聊天是对话，对话消息需要有顺序：
- 用户："你好"
- 用户："你叫什么名字"
- 机器人应该先回答"你好"，再回答"我叫xxx"

如果并发处理，可能顺序就乱了。

---

## 日志解读

启动服务器后，你会看到这样的日志：

```
[调度] 开始处理 private:12345      # 新任务创建
[并发] 获取锁 private:12345，开始处理  # 获取到锁，开始处理
[LLM] 调用 LLM: 你好...            # 调用 LLM API
[回复] 你好！有什么可以帮助你的吗？    # 收到回复
[并发] 处理完成 private:12345       # 处理完成，释放锁
```

当同一用户连续发消息时：
```
[调度] 开始处理 private:12345      # 消息1到达
[并发] 获取锁 private:12345，开始处理  # 开始处理
[调度] 开始处理 private:12345      # 消息2到达（但获取不到锁）
[调度] 开始处理 private:12345      # 消息3到达（但获取不到锁）
[LLM] 调用 LLM: 你好...            # 消息1的 LLM 返回
[回复] 你好！...
[并发] 处理完成 private:12345       # 消息1完成，释放锁
[并发] 获取锁 private:12345，开始处理  # 消息2获取到锁，开始处理
...（消息2和消息3会串行处理）
```

---

## 总结

| 概念 | 作用 | 类比 |
|------|------|------|
| asyncio | 异步编程基础 | 点餐后等叫号 |
| Task | 表示一个异步执行单元 | 服务员把订单交给厨房 |
| Semaphore | 限制最大并发数 | 奶茶店只有3个座位 |
| Lock | 保证同一用户消息串行 | 公共厕所一次只能一个人用 |
| Tasks Set | 跟踪所有活跃任务 | 记录有多少菜在做着 |

通过这些机制的组合，本程序实现了：
1. **不同用户可以同时聊天**（信号量控制）
2. **同一用户的消息顺序不变**（锁控制）
3. **API 调用失败自动重试**（重试逻辑）
4. **不会处理自己发送的消息**（过滤逻辑）
