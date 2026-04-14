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

### 1.1 异步 + 并发 = 高效处理

**异步是并发的前提条件：**

```python
# websocket_server.py 第486行
asyncio.create_task(process_message(data, websocket))
```

这段代码展示了它们的关系：

| 概念 | 代码作用 |
|------|----------|
| `async def` | 定义异步函数，允许 `await` 挂起 |
| `await llm_client.chat()` | **异步等待**——在等 LLM 时不阻塞其他任务 |
| `asyncio.create_task()` | **创建任务**——交给事件循环调度执行 |
| `semaphore` | **并发控制**——限制同时运行的任务数 |
| `Lock` | **互斥**——保证同一用户的代码串行执行 |

**关键点**：如果没有 `async/await`，程序在等 LLM 响应时会卡住，无法同时处理其他消息。有了异步，才可能实现并发。

**代码流程：**
```python
# 1. handler 是异步的，能"同时"接收很多消息
async def handler(websocket):
    async for raw_message in websocket:  # 不断接收消息
        asyncio.create_task(process_message(...))  # 立即返回，不等待完成

# 2. process_message 内部用 await，不阻塞其他任务
async def process_message(data, websocket):
    async with semaphore:  # 等信号量许可（不阻塞其他用户）
        async with user_locks[key]:  # 等锁（同一用户串行）
            response = await llm_client.chat(message)  # 等 LLM（不阻塞其他任务）
            await websocket.send(...)  # 发消息（不阻塞）
```

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
    task.add_done_callback(tasks.discard)  # 任务完成后自动从集合移除
```

**用途：**
- 记录当前有多少消息正在处理
- 服务器关闭时可以取消所有未完成的任务
- 监控并发状态

**结合信号量和异步的完整例子：**
```python
# 模拟场景：3个用户同时发消息

async def main():
    semaphore = asyncio.Semaphore(3)  # 限制3个并发
    tasks: set[asyncio.Task] = set()

    async def process(name):
        async with semaphore:
            print(f"{name} 开始处理")
            await asyncio.sleep(2)  # 模拟 LLM 调用
            print(f"{name} 完成")
            tasks.discard(asyncio.current_task())

    # 创建3个任务
    for i in range(3):
        task = asyncio.create_task(process(f"用户{i}"))
        tasks.add(task)

    # 等待所有任务完成
    await asyncio.gather(*tasks)

# 输出（注意时间戳）：
# 用户0 开始处理
# 用户1 开始处理
# 用户2 开始处理
# （2秒后）
# 用户0 完成
# 用户1 完成
# 用户2 完成
```

**为什么需要 Tasks Set？**

想象服务器突然要关闭：
- 没有 Tasks Set：不知道有哪些任务在跑，可能强制杀掉正在处理的任务
- 有 Tasks Set：可以先取消所有任务，等待它们完成，再安全退出

---

## 完整流程图解

```
┌─────────────────────────────────────────────────────────────────────┐
│                        异步 + 并发 完整流程                           │
└─────────────────────────────────────────────────────────────────────┘

消息1 (用户A) ──┐
消息2 (用户B) ──┼──→ handler() 接收消息（异步，不阻塞）
消息3 (用户A) ──┘         │
                          ▼ asyncio.create_task() 创建任务（立即返回）
              ┌───────────────────────────────┐
              │  事件循环调度                  │
              │  （所有任务在这里"同时"交替执行） │
              └───────────────────────────────┘
                          │
                          ▼
              ┌─────────────────────┐
              │  semaphore.acquire() │ ← 异步等待，不阻塞其他任务
              └─────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   用户A的锁          用户B的锁          用户C的锁
   (等待中)           (处理中)          (等待中)
        │                 │                 │
        ▼                 ▼                 │
   (获取锁)          await chat()          ......|
        │                 │                 │
        ▼                 ▼                 ▼
   await chat() ──→ 发送回复 ──────→ 释放锁
        │                                   │
        └───────────────────────────────────┘
                          │
              ┌─────────────────────┐
              │  semaphore.release() │
              └─────────────────────┘

【关键点】
1. handler() 用 async for，不阻塞接收
2. create_task() 立即返回，不等任务完成
3. semaphore.acquire() 是异步的，等的时候可以做别的
4. await chat() 等待时不阻塞事件循环，其他任务可以执行
5. Lock 保证同一用户的消息按顺序执行
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

### 概念对照表

| 概念 | 作用 | 类比 |
|------|------|------|
| `async/await` | 异步编程基础，让等待不阻塞 | 点餐后等叫号 |
| `Task` | 表示一个异步执行单元，交给事件循环调度 | 服务员把订单交给厨房 |
| `Semaphore` | 限制最大并发数 | 奶茶店只有3个座位 |
| `Lock` | 保证同一用户消息串行 | 公共厕所一次只能一个人用 |
| `Tasks Set` | 跟踪所有活跃任务 | 记录有多少菜在做着 |

### 异步和并发的关系

```
异步（Asyncio）                    并发（Concurrency）
     │                                  │
     │  提供 async/await 机制            │  在异步基础上实现
     │  让"等待"不阻塞                   │  多任务同时执行
     │                                  │
     └────────────┬────────────────────┘
                  │
                  ▼
         asyncio.create_task()
         任务被提交给事件循环
         多个任务交替执行（并发）
```

**简单理解**：
- **异步** = `await` + 事件循环（不排队等）
- **并发** = Task + Semaphore + Lock（一起干但有序）

本程序正是通过 asyncio 提供的能力，实现了：
1. **不同用户可以同时聊天**（信号量控制最大3个并发）
2. **同一用户的消息顺序不变**（锁控制串行）
3. **API 调用失败自动重试**（重试逻辑）
4. **不会处理自己发送的消息**（过滤逻辑）
5. **服务器可优雅关闭**（Tasks Set 跟踪所有任务）
