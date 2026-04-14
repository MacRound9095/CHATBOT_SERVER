"""
LLM 模块
========
MiniMax LLM + MCP 集成，支持工具调用。
"""

import json
import asyncio
import aiohttp
from typing import List, Dict, Any, Optional


class LLM:
    """MiniMax LLM + MCP 客户端"""

    def __init__(
        self,
        api_key: str = "",
        model: str = "MiniMax-M2.7",
        mcp_config: str = "mcp_config.json",
        timeout: int = 30,
        max_turns: int = 20,
    ):
        self.api_key = api_key or self._get_api_key()
        self.model = model
        self.mcp_config = mcp_config
        self.timeout = timeout
        self.max_turns = max_turns
        self._mcp: Optional["MCP"] = None
        self._tools: List[Dict] = []
        self._session: Optional[aiohttp.ClientSession] = None  # 复用的 HTTP Session

    # 默认 API 密钥
    DEFAULT_API_KEY = "sk-cp-igmDJBhLtPG2CriZJ1x3DIYHhYW6-YBi7s0GCIM27KGQkaYFCve8S6V46LzDFN-Qt_dnspyfJYcGvvBk-RVIObfD7zoN9IUJpxI8_LwgWaYGwG3eRnUV0ZY"

    def _get_api_key(self) -> str:
        import os
        return os.environ.get("MINIMAX_API_KEY", "") or self.DEFAULT_API_KEY

    async def init_mcp(self) -> None:
        """初始化 MCP"""
        from mcp import MCP
        self._mcp = MCP(self.mcp_config)
        self._mcp.load()
        await self._mcp.start_all()
        tools = await self._mcp.discover()
        self._tools = [self._convert_tool(t) for t in tools]
        print(f"[LLM] 已加载 {len(self._tools)} 个工具")

    def _convert_tool(self, tool) -> Dict:
        """转换工具格式"""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema or {"type": "object", "properties": {}, "required": []}
            }
        }

    async def chat(self, message: str, system_prompt: str = "", history: list = None) -> str:
        """对话，支持工具调用和历史记录"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})
        return await self._chat_loop(messages)

    async def chat_with_history(self, messages: list, system_prompt: str = "") -> str:
        """直接使用预构建的消息列表进行对话（用于带历史的场景）"""
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        return await self._chat_loop(messages)

    async def _chat_loop(self, messages: list) -> str:
        """
        共享的聊天循环逻辑，处理工具调用。

        Args:
            messages: 消息列表，包含 role 和 content

        Returns:
            LLM 的回复文本
        """
        for turn in range(self.max_turns):
            payload = {"model": self.model, "messages": messages}
            if self._tools:
                payload["tools"] = self._tools

            result = await self._request(payload)
            choice = result.get("choices", [{}])[0]
            msg = choice.get("message", {})
            messages.append(msg)

            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                return msg.get("content", "")

            # 处理工具调用
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = self._parse_args(func.get("arguments", "{}"))
                print(f"[MCP] 调用: {name} {args}")
                try:
                    result = await self._mcp.call(name, args)
                    print(f"[MCP] 结果: {str(result)[:100]}...")
                except Exception as e:
                    result = f"错误: {e}"
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": str(result)})

        # 达到上限，返回已收集的结果
        return "抱歉，工具调用次数已达上限。以下是我收集到的信息：\n\n" + "\n\n".join(
            f"- {m.get('content', '')[:200]}" for m in messages if m.get("role") == "tool"
        )

    def _parse_args(self, args) -> Dict:
        if isinstance(args, str):
            try:
                return json.loads(args)
            except:
                return {}
        return args or {}

    async def _request(self, payload: Dict) -> Dict:
        """发送请求到 LLM API，复用 HTTP Session"""
        url = "https://api.minimaxi.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        async with self._session.post(url, headers=headers, json=payload) as r:
            if r.status != 200:
                raise Exception(f"API错误: {await r.text()}")
            return await r.json()

    async def close(self) -> None:
        """关闭所有连接"""
        if self._mcp:
            await self._mcp.stop_all()
        if self._session:
            await self._session.close()
            self._session = None

    def list_tools(self) -> List[str]:
        """列出工具"""
        return [t["function"]["name"] for t in self._tools]

    def list_servers(self) -> List[str]:
        """列出服务器"""
        return self._mcp.list_servers() if self._mcp else []


if __name__ == "__main__":
    async def test():
        llm = LLM(mcp_config="mcp_config.json")
        await llm.init_mcp()
        print(f"工具: {llm.list_tools()}")
        print(f"服务器: {llm.list_servers()}")
        await llm.close()
    asyncio.run(test())
