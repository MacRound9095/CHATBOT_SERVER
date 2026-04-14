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
import websockets
from llm import LLM


# ==================== 常量定义 ====================

# 常用指令列表，用于检测用户输入的命令
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
    
    # 正则匹配所有 CQ 码
    cq_pattern = r'\[CQ:([^,\]]+)(?:,([^\]]*))?\]'
    
    last_end = 0
    for match in re.finditer(cq_pattern, text):
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
    
    # 非群聊消息（私聊）始终处理
    if data.get("message_type") != "group":
        return True
    
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
    
    if cmd in ["/help", "!help"]:
        return HELP_TEXT
    
    if cmd in ["/mcp", "!mcp"]:
        servers = llm_client.list_servers() if llm_client else []
        if not servers:
            return "❌ 没有配置任何 MCP 服务器"
        return "📡 MCP 服务器列表：\n" + "\n".join(f"• {s}" for s in servers)
    
    if cmd in ["/tools", "!tools"]:
        tools = llm_client.list_tools() if llm_client else []
        if not tools:
            return "❌ 没有发现任何工具"
        return f"🔧 已发现 {len(tools)} 个工具：\n" + "\n".join(f"• {t}" for t in tools[:20]) + ("\n...等" if len(tools) > 20 else "")
    
    if cmd in ["/reload", "!reload"]:
        try:
            if llm_client:
                await llm_client.close()
                await llm_client.init_mcp()
            return "✅ MCP 服务器已重启"
        except Exception as e:
            return f"❌ 重启失败: {e}"
    
    return ""


# ==================== 消息处理 ====================

async def handler(websocket):
    """
    WebSocket 消息处理主函数
    
    处理流程：
    1. 接收并解析 JSON 消息
    2. 过滤 meta_event（心跳等）和错误响应
    3. 群聊消息检查是否 @ 机器人
    4. 提取消息内容
    5. 处理指令或调用 LLM
    6. 发送回复
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
            
            # ----- 4. 群聊检查 @ -----
            # 只有 @ 机器人的群聊消息才处理
            if not is_at_me(data):
                continue  # 未 @ 机器人，静默忽略
            
            # ----- 5. 提取消息内容 -----
            message = None
            
            # 优先从 message 字段提取
            if "message" in data:
                msg_field = data["message"]
                
                # 字符串格式（私聊或简单群聊）
                if isinstance(msg_field, str):
                    # 检查是否包含 CQ 码
                    if "[CQ:" in msg_field:
                        # 解析 CQ 码，提取纯文本
                        segments = parse_cq_code(msg_field)
                        parts = []
                        for seg in segments:
                            if seg.get("type") == "text":
                                parts.append(seg.get("data", {}).get("text", ""))
                        message = "".join(parts).strip()
                    else:
                        message = msg_field
                
                # 数组格式（包含 at、text 等消息段）
                elif isinstance(msg_field, list):
                    parts = []
                    for seg in msg_field:
                        # 只提取文本段，跳过 at、image 等
                        if isinstance(seg, dict) and seg.get("type") == "text":
                            parts.append(seg.get("text", ""))
                    message = "".join(parts).strip()
            
            # 备选：raw_message 字段（可能是 CQ 码格式）
            if not message and "raw_message" in data:
                raw = data.get("raw_message", "")
                if "[CQ:" in raw:
                    segments = parse_cq_code(raw)
                    parts = []
                    for seg in segments:
                        if seg.get("type") == "text":
                            parts.append(seg.get("data", {}).get("text", ""))
                    message = "".join(parts).strip()
                else:
                    message = raw
            
            # 备选：content 字段
            if not message and "content" in data:
                message = data.get("content")
            
            if not message:
                continue
            
            message = str(message).strip()
            if not message:
                continue
            
            print(f"[消息] {message}")
            
            # ----- 6. 处理指令 -----
            if is_command(message):
                response = await handle_command(message)
                if response:
                    # 判断是私聊还是群聊
                    is_private = data.get("message_type") == "private"
                    # 私聊用 user_id，群聊用 group_id
                    target_id = data.get("user_id") if is_private else data.get("group_id")
                    
                    reply_payload = {
                        "action": "send_private_msg" if is_private else "send_group_msg",
                        "params": {
                            "user_id" if is_private else "group_id": target_id,
                            "message": response
                        }
                    }
                    await websocket.send(json.dumps(reply_payload))
                    print(f"[回复] {response[:100]}")
                continue
            
            # ----- 7. 调用 LLM -----
            if not llm_client:
                await websocket.send(json.dumps({
                    "action": "send_private_msg",
                    "params": {"user_id": data.get("user_id"), "message": "❌ LLM 未初始化"}
                }))
                continue
            
            try:
                response = await llm_client.chat(message,"请你扮演一位活泼可爱略带傲娇的二次元猫娘coser，用俏皮温柔的语气与我对话，句尾偶尔加‘喵~’，并加入动作与情绪描写但保持自然不过度夸张")
                # 去掉 <think>...</think> 包裹的思考内容
                response = re.sub(r'<think>[\s\S]*?</think>', '', response).strip()
                print(f"[回复] {response[:100]}")
                
                is_private = data.get("message_type") == "private"
                target_id = data.get("user_id") if is_private else data.get("group_id")
                
                reply_payload = {
                    "action": "send_private_msg" if is_private else "send_group_msg",
                    "params": {
                        "user_id" if is_private else "group_id": target_id,
                        "message": response
                    }
                }
                # 保留 echo 字段（原样返回）
                if data.get("echo"):
                    reply_payload["echo"] = data["echo"]
                
                await websocket.send(json.dumps(reply_payload))
                
            except Exception as e:
                print(f"[错误] LLM: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        print("[连接] 客户端断开")


# ==================== 启动入口 ====================

async def main():
    """启动服务器"""
    global llm_client
    
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
    
    print(f"🚀 启动 WebSocket 服务器 {host}:{port}")
    async with websockets.serve(handler, host, port):
        # 保持运行
        await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
