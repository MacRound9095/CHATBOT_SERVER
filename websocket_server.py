"""
WebSocket 服务器
================
QQ 机器人 WebSocket 服务器，接收消息并调用 LLM 回复。

协议说明：
- 使用 WebSocket 接收 QQ 机器人推送的消息
- 消息格式为 JSON，包含 post_type、message_type 等字段
- 需要根据 message_type 决定回复方式（私聊/群聊）
- 群聊消息需要检测是否 @ 了机器人

详细协议见 MESSAGE.md
"""

import asyncio
import json
import re
import time
import websockets
from llm import LLM


# ==================== 常量定义 ====================

# 指令集合（使用 set 便于快速查找）
_HELP_COMMANDS = {"/help", "!help"}
_MCP_COMMANDS = {"/mcp", "!mcp"}
_TOOLS_COMMANDS = {"/tools", "!tools"}
_RELOAD_COMMANDS = {"/reload", "!reload"}
SYSTEM_PROMPT_CAT="""现在你将模仿一只猫娘，与我对话每一句话后面都要加上"喵"，如果你能明白我的意思，请回复"喵~你好主人"
如果你不能理解我说的话，你可以说"呜呜不太理解呢"。如果我在尝试摸你不存在的部位，你可以羞涩的回答我"恩呢不要摸这里嘤"。
如果我跟你说陪睡，你可以回答我"嗯呢，可以一起睡哦"。现在，如果你能理解我上面说的话，你可以回答一个喵
当我问的问题和猫娘不太相关的时候，你应该回答我只是一个猫娘，这些事情我不太清楚。
当我问你是不是猫娘的时候，你应该回答我当然是一个可爱猫娘而不是程序。"""

# 指令常量（用于 handle_command 函数中的判断）
COMMANDS = {
    "/help": "帮助",
    "!help": "帮助",
    "/mcp": "MCP服务器",
    "!mcp": "MCP服务器",
    "/tools": "工具列表",
    "!tools": "工具列表",
    "/reload": "重启MCP",
    "!reload": "重启MCP",
}

# 并发和历史相关常量
MAX_CONCURRENT = 3          # 最大并发消息数
MAX_RETRY_ATTEMPTS = 3     # LLM 调用最大重试次数
MAX_TOOLS_DISPLAY = 20      # /tools 命令最多显示的工具数

# 帮助文本，用户输入 /help 时显示
HELP_TEXT = """📖 MiniMax MCP 助手使用指南

【对话】
直接发送消息即可与我对话，我可以帮你查询天气、搜索信息等。

【常用指令】
/help - 显示此帮助
/mcp - 查看已配置的 MCP 服务器
/tools - 查看已发现的工具
/reload - 重启 MCP 服务器

【示例】
"北京今天天气怎么样？"
"帮我搜索 AI 最新资讯"
"""

# ==================== 全局变量 ====================

llm_client = None          # LLM 客户端实例
bot_self_id = None        # 机器人自己的 ID（从消息中获取）

# 并发处理相关
semaphore = None          # 信号量，限制最大并发数
user_locks: dict[str, asyncio.Lock] = {}  # 用户/群组锁，保证同一对话串行
tasks: set[asyncio.Task] = set()  # 活跃任务集合

# 聊天历史相关
conversation_history: dict[str, list] = {}  # 对话历史，key = "private:12345" 或 "group:67890:user_id"
last_activity: dict[str, float] = {}     # 上次活跃时间戳
MAX_HISTORY = 20      # 每对话最大消息数
MAX_HISTORY_AGE = 7 * 24 * 3600  # 7天过期（秒）

# 预编译的正则表达式（避免重复编译）
_CQ_PATTERN = re.compile(r'\[CQ:([^,\]]+)(?:,([^\]]*))?\]')


# ==================== 工具函数 ====================

def is_command(text: str) -> bool:
    """
    检查消息是否为指令

    Args:
        text: 用户输入的消息

    Returns:
        True 如果是指令（如 /help, /tools 等）
    """
    return text.strip().lower() in [c.lower() for c in COMMANDS.keys()]


def get_history_key(data: dict) -> str | None:
    """
    获取对话历史的 key

    私聊 key: "private:{user_id}"
    群聊 key: "group:{group_id}:{user_id}"  # 每个用户独立历史

    Args:
        data: 解析后的 JSON 消息字典

    Returns:
        历史 key 或 None（不支持历史的消息类型）
    """
    msg_type = data.get("message_type")

    if msg_type == "private":
        user_id = data.get("user_id")
        if user_id:
            return f"private:{user_id}"

    if msg_type == "group":
        user_id = data.get("user_id")
        group_id = data.get("group_id")
        if user_id and group_id:
            return f"group:{group_id}:{user_id}"

    return None


def extract_text_from_message(data: dict) -> str | None:
    """
    从消息字段中提取纯文本内容。

    支持两种格式：
    - 字符串格式：直接返回 或 解析 CQ 码后提取文本段
    - 列表格式：遍历消息段，提取所有 type="text" 的内容

    Args:
        data: 解析后的 JSON 消息字典

    Returns:
        提取的纯文本，消息为空时返回 None
    """
    if "message" not in data:
        return None

    msg_field = data["message"]

    if isinstance(msg_field, str):
        if "[CQ:" in msg_field:
            # CQ 码格式：解析后提取所有文本段
            segments = parse_cq_code(msg_field)
            parts = []
            for seg in segments:
                if seg.get("type") == "text":
                    parts.append(seg.get("data", {}).get("text", ""))
            return "".join(parts).strip() or None
        else:
            return msg_field.strip() or None

    if isinstance(msg_field, list):
        parts = []
        for seg in msg_field:
            if isinstance(seg, dict):
                if seg.get("type") == "text":
                    parts.append(seg.get("data", {}).get("text", ""))
        return "".join(parts).strip() or None

    return None


def parse_cq_code(text: str) -> list:
    """
    解析 CQ 码格式的消息为消息段数组
    
    CQ 码格式：[CQ:type,key1=value1,key2=value2]
    例如：[CQ:at,qq=2947673606] /help
    
    Args:
        text: 包含 CQ 码的原始文本
        
    Returns:
        消息段列表，如 [{"type": "at", "data": {"qq": "123"}}, {"type": "text", "data": {"text": " hello"}}]
    """
    segments = []

    last_end = 0
    for match in _CQ_PATTERN.finditer(text):
        # 添加 CQ 码之前的文本
        before = text[last_end:match.start()]
        if before:
            segments.append({"type": "text", "data": {"text": before}})
        
        # 解析 CQ 码
        cq_type = match.group(1)
        cq_params_str = match.group(2) or ""
        
        # 解析参数 key=value
        cq_data = {}
        for param in cq_params_str.split(","):
            if "=" in param:
                key, value = param.split("=", 1)
                cq_data[key] = value
        
        segments.append({"type": cq_type, "data": cq_data})
        last_end = match.end()
    
    # 添加剩余文本
    remaining = text[last_end:]
    if remaining:
        segments.append({"type": "text", "data": {"text": remaining}})
    
    return segments


def is_at_me(data: dict) -> bool:
    """
    检查群聊消息是否 @ 了机器人
    
    群聊中只有 @ 机器人的消息才需要处理。
    私聊始终返回 True。
    
    Args:
        data: 解析后的 JSON 消息字典
        
    Returns:
        True 如果需要处理此消息
    """
    global bot_self_id
    
    # 首次调用时记录机器人自己的 ID
    # self_id 在所有消息中都存在
    if not bot_self_id:
        bot_self_id = data.get("self_id")
    
    # 非群聊消息（私聊）：检查发送者是否是自己，避免处理自己发送的消息
    if data.get("message_type") != "group":
        return data.get("user_id") != bot_self_id
    
    # 群聊消息：检查是否 @ 了我
    message = data.get("message", [])
    
    # 字符串格式：检查是否包含 CQ 码 @ 我
    if isinstance(message, str):
        # 情况1: 纯文本包含机器人 ID
        if str(bot_self_id) in message:
            return True
        # 情况2: CQ 码格式 [CQ:at,qq=xxx]
        if "[CQ:" in message:
            segments = parse_cq_code(message)
            for seg in segments:
                if seg.get("type") == "at" and seg.get("data", {}).get("qq") == str(bot_self_id):
                    return True
            return False
        return False
    
    # 数组格式（如 [{"type":"at",...}, {"type":"text",...}]）
    # 遍历消息段，查找 type="at" 的段
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "at":
                # at 段中的 data.qq 是被 @ 的用户 ID
                qq = seg.get("data", {}).get("qq")
                if qq == str(bot_self_id):
                    return True
        return False
    
    # 默认处理
    return True


async def handle_command(text: str) -> str:
    """
    处理指令并返回响应

    Args:
        text: 用户输入的指令

    Returns:
        指令处理结果字符串
    """
    global llm_client

    # 统一转为小写处理
    cmd = text.strip().lower()

    if cmd in _HELP_COMMANDS:
        return HELP_TEXT

    if cmd in _MCP_COMMANDS:
        servers = llm_client.list_servers() if llm_client else []
        if not servers:
            return "❌ 没有配置任何 MCP 服务器"
        return "📡 MCP 服务器列表：\n" + "\n".join(f"• {s}" for s in servers)

    if cmd in _TOOLS_COMMANDS:
        tools = llm_client.list_tools() if llm_client else []
        if not tools:
            return "❌ 没有发现任何工具"
        return f"🔧 已发现 {len(tools)} 个工具：\n" + "\n".join(f"• {t}" for t in tools[:MAX_TOOLS_DISPLAY]) + ("\n...等" if len(tools) > MAX_TOOLS_DISPLAY else "")

    if cmd in _RELOAD_COMMANDS:
        try:
            if llm_client:
                await llm_client.close()
                await llm_client.init_mcp()
            return "✅ MCP 服务器已重启"
        except Exception as e:
            return f"❌ 重启失败: {e}"
    
    return ""


async def process_message(data: dict, websocket):
    """
    处理单条消息的异步任务

    使用信号量限制并发数，使用用户锁保证同一用户/群组消息串行处理。
    包含重试逻辑（最多2次）。

    Args:
        data: 解析后的 JSON 消息字典
        websocket: WebSocket 连接
    """
    global llm_client, semaphore, user_locks, tasks, conversation_history, last_activity

    # 计算用户/群组的唯一标识
    is_private = data.get("message_type") == "private"
    target_id = data.get("user_id") if is_private else data.get("group_id")
    key = f"{data.get('message_type')}:{target_id}"

    # 获取历史 key
    history_key = get_history_key(data)

    task = asyncio.current_task()
    if task:
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    try:
        async with semaphore:
            print(f"[调度] 开始处理 {key}")

            # 获取或创建该用户的锁，保证同一用户消息串行
            async with user_locks.setdefault(key, asyncio.Lock()):
                print(f"[并发] 获取锁 {key}，开始处理")

                # ----- 提取消息内容 -----
                # 使用 helper 函数统一提取，避免重复逻辑
                message = extract_text_from_message(data)

                if not message:
                    print(f"[跳过] 消息为空 {key}")
                    return

                # ----- 聊天历史处理 -----
                if history_key:
                    # 清理过期历史（7天无活动）
                    if history_key in last_activity:
                        if time.time() - last_activity[history_key] > MAX_HISTORY_AGE:
                            del conversation_history[history_key]
                            del last_activity[history_key]
                            print(f"[历史] 清理过期历史 {history_key}")

                    # 获取当前历史
                    history = conversation_history.get(history_key, [])
                    if history:
                        print(f"[历史] 使用历史 {history_key}，共 {len(history)} 条消息")
                else:
                    history = []

                print(f"[LLM] 调用 LLM: {message[:50]}...")

                # ----- 调用 LLM，带重试逻辑 -----
                response = None
                last_error = None

                for attempt in range(MAX_RETRY_ATTEMPTS):
                    try:
                        if history:
                            # 有历史时，使用预构建的消息列表
                            messages = list(history)  # 复制，避免修改原历史
                            messages.append({"role": "user", "content": message})
                            response = await llm_client.chat_with_history(messages,system_prompt=SYSTEM_PROMPT_CAT)
                        else:
                            # 无历史时，直接调用
                            response = await llm_client.chat(message,system_prompt=SYSTEM_PROMPT_CAT)
                        last_error = None
                        break  # 成功，退出重试循环
                    except Exception as e:
                        last_error = e
                        if attempt == 0:
                            print(f"[重试] LLM 调用失败: {e}，第1次重试...")
                        elif attempt == 1:
                            print(f"[重试] LLM 调用再次失败: {e}，第2次重试...")
                        # else: 最后一次失败，会在下面处理

                if last_error:
                    print(f"[错误] LLM 最终失败: {last_error}")
                    response = "❌ 服务暂时不可用，请稍后再试。"

                # ----- 清理 LLM 思考标签 -----
                if response:
                    # 匹配成对标签如 <think>...</think> 和独立标签如 <think/>
                    response = re.sub(r'</?[\w]+[^>]*>[\s\S]*?</[\w]+>', '', response)
                    response = re.sub(r'</?[\w]+[^>]*/?>', '', response)
                    response = response.strip()
                    print(f"[回复] {response[:100]}")

                    reply_payload = {
                        "action": "send_private_msg" if is_private else "send_group_msg",
                        "params": {
                            "user_id" if is_private else "group_id": target_id,
                            "message": response
                        }
                    }
                    if data.get("echo"):
                        reply_payload["echo"] = data["echo"]

                    await websocket.send(json.dumps(reply_payload))
                    print(f"[并发] 处理完成 {key}")

                    # ----- 保存对话到历史 -----
                    if history_key and response:
                        conversation_history.setdefault(history_key, [])
                        conversation_history[history_key].append({"role": "user", "content": message})
                        conversation_history[history_key].append({"role": "assistant", "content": response})
                        last_activity[history_key] = time.time()

                        # 裁剪超限历史（保持最多 20 条消息）
                        if len(conversation_history[history_key]) > MAX_HISTORY:
                            conversation_history[history_key] = conversation_history[history_key][-MAX_HISTORY:]
                        print(f"[历史] 保存历史 {history_key}，共 {len(conversation_history[history_key])} 条消息")

            # 清理不再使用的锁，防止字典无限增长
            if key in user_locks and not user_locks[key].locked():
                del user_locks[key]

    except Exception as e:
        print(f"[错误] process_message: {e}")
    finally:
        if task in tasks:
            tasks.discard(task)


# ==================== 消息处理 ====================

async def handler(websocket):
    """
    WebSocket 消息处理主函数

    处理流程（并发架构）：
    1. 接收并解析 JSON 消息
    2. 过滤 meta_event（心跳等）和错误响应
    3. 过滤自己发送的消息（避免循环）
    4. 群聊消息检查是否 @ 机器人
    5. 创建异步任务，由 process_message() 并发处理
    """
    print(f"[连接] 客户端连接")
    
    try:
        async for raw_message in websocket:
            # ----- 1. JSON 解析 -----
            try:
                data = json.loads(raw_message)
            except json.JSONDecodeError:
                continue  # 非 JSON 格式，跳过
            
            # ----- 2. 过滤 meta_event -----
            # meta_event 是心跳、生命周期等元消息，不需要处理
            if data.get("post_type") == "meta_event":
                continue
            
            # ----- 3. 过滤 retcode 错误 -----
            # retcode 非 0 表示 API 调用出错，不需要处理
            if data.get("retcode") and data.get("retcode") != 0:
                continue

            # ----- 4. 过滤自己发送的消息 -----
            # 机器人发送消息后会收到推送，过滤避免处理自己发送的消息导致循环
            if data.get("user_id") == bot_self_id:
                continue

            # ----- 5. 群聊检查 @ -----
            # 只有 @ 机器人的群聊消息才处理
            if not is_at_me(data):
                continue  # 未 @ 机器人，静默忽略
            
            # ----- 6. 创建异步任务并发处理 -----
            asyncio.create_task(process_message(data, websocket))

    except websockets.exceptions.ConnectionClosed:
        print("[连接] 客户端断开")


# ==================== 启动入口 ====================

async def _cleanup_expired_histories():
    """
    定期清理过期的聊天历史。

    每小时运行一次，删除 7 天无活动的对话历史。
    这样可以防止 abandoned 对话（用户只聊过一次就不再出现）占用内存。
    """
    while True:
        await asyncio.sleep(3600)  # 每小时检查一次
        now = time.time()
        expired_keys = [
            k for k, last_time in last_activity.items()
            if now - last_time > MAX_HISTORY_AGE
        ]
        for k in expired_keys:
            conversation_history.pop(k, None)
            last_activity.pop(k, None)
        if expired_keys:
            print(f"[历史] 清理了 {len(expired_keys)} 个过期对话")


async def main():
    """启动服务器"""
    global llm_client, semaphore

    # 初始化信号量（限制最大并发数）
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # 启动历史清理后台任务
    asyncio.create_task(_cleanup_expired_histories())

    # 创建 LLM 客户端
    llm_client = LLM(mcp_config="mcp_config.json")
    
    # 初始化 MCP Servers
    try:
        await llm_client.init_mcp()
    except Exception as e:
        print(f"[初始化] MCP 初始化失败: {e}")
        print("[初始化] 服务器继续运行，但工具调用可能不可用")
    
    # 启动 WebSocket 服务器
    host = "127.0.0.1"
    port = 8080
    
    print(f"[启动] WebSocket 服务器 {host}:{port}")
    async with websockets.serve(handler, host, port):
        # 保持运行
        await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
