"""
MCP 模块
========
MCP 协议客户端 + MCP Server 管理器。
"""

import json
import asyncio
import os
import subprocess
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]


class MCP:
    """MCP 客户端 + 服务器管理器"""
    
    def __init__(self, config_path: str = "mcp_config.json"):
        self.config_path = config_path
        self._servers: Dict[str, Dict] = {}
        self._clients: Dict[str, "MCPClient"] = {}
        self._tools: Dict[str, Tool] = {}
    
    def load(self) -> None:
        """加载配置"""
        if not os.path.exists(self.config_path):
            return
        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for name, cfg in data.get("mcpServers", {}).items():
            self._servers[name] = {
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
                "env": cfg.get("env", {}),
                "timeout": cfg.get("timeout", 60),
                "disabled": cfg.get("disabled", False)
            }
    
    def save(self) -> None:
        """保存配置"""
        servers = {}
        for name, s in self._servers.items():
            servers[name] = {"command": s["command"], "args": s["args"], "env": s["env"], "timeout": s["timeout"], "disabled": s["disabled"]}
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump({"mcpServers": servers}, f, indent=2)
    
    def add(self, name: str, command: str, args: List[str], env: Dict = None, timeout: int = 60) -> None:
        """添加服务器"""
        self._servers[name] = {"command": command, "args": args, "env": env or {}, "timeout": timeout, "disabled": False}
    
    def remove(self, name: str) -> bool:
        """移除服务器"""
        if name in self._servers:
            del self._servers[name]
            return True
        return False
    
    def list_servers(self) -> List[str]:
        """列出服务器"""
        return list(self._servers.keys())
    
    async def start_all(self) -> None:
        """启动所有服务器"""
        for name in self._servers:
            if not self._servers[name]["disabled"]:
                try:
                    await self._start_server(name)
                except Exception as e:
                    print(f"[MCP] 启动 {name} 失败: {e}")
    
    async def _start_server(self, name: str) -> None:
        """启动单个服务器"""
        cfg = self._servers[name]
        if name in self._clients:
            return
        full_env = {**os.environ, **cfg["env"]} if cfg["env"] else None
        
        import platform
        if platform.system() == "Windows":
            # Windows: 使用 shell=True，需要完整命令字符串
            cmd_parts = [cfg["command"]] + cfg["args"]
            cmd_line = subprocess.list2cmdline(cmd_parts)
            process = await asyncio.create_subprocess_shell(
                cmd_line,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=full_env,
                shell=True
            )
        else:
            process = await asyncio.create_subprocess_exec(
                cfg["command"], *cfg["args"],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=full_env
            )
        
        client = MCPClient(process, cfg["timeout"])
        await client.initialize()
        self._clients[name] = client
    
    async def stop_all(self) -> None:
        """停止所有服务器"""
        for name in list(self._clients.keys()):
            await self._stop_server(name)
    
    async def _stop_server(self, name: str) -> None:
        """停止单个服务器"""
        if name in self._clients:
            await self._clients[name].close()
            del self._clients[name]
    
    async def discover(self) -> List[Tool]:
        """发现工具"""
        self._tools.clear()
        for name, client in self._clients.items():
            try:
                tools = await client.list_tools()
                for t in tools:
                    full_name = f"{name}:{t.name}"
                    self._tools[full_name] = Tool(name=full_name, description=t.description, input_schema=t.input_schema)
            except Exception as e:
                print(f"[MCP] {name} 发现工具失败: {e}")
        return list(self._tools.values())
    
    async def call(self, full_name: str, args: Dict) -> Any:
        """调用工具"""
        if ":" in full_name:
            server_name, tool_name = full_name.split(":", 1)
        else:
            server_name, tool_name = None, full_name
        
        if server_name and server_name in self._clients:
            return await self._clients[server_name].call_tool(tool_name, args)
        
        for sname, client in self._clients.items():
            try:
                return await client.call_tool(tool_name, args)
            except:
                continue
        raise ValueError(f"未找到工具: {full_name}")


class MCPClient:
    """MCP 协议客户端"""
    
    def __init__(self, process: asyncio.subprocess.Process, timeout: int = 30):
        self.process = process
        self.timeout = timeout
        self._id = 0
        self._initialized = False
    
    async def _send(self, method: str, params: Dict = None) -> Any:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params:
            req["params"] = params
        self.process.stdin.write((json.dumps(req) + "\n").encode('utf-8'))
        await self.process.stdin.drain()
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=self.timeout)
            resp = json.loads(line.decode('utf-8'))
            if "error" in resp:
                raise Exception(f"MCP错误: {resp['error']}")
            return resp.get("result")
        except asyncio.TimeoutError:
            raise Exception(f"MCP超时: {method}")
    
    async def initialize(self) -> None:
        """初始化"""
        await self._send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "minimax-llm", "version": "1.0"}})
        self._initialized = True
        self.process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n')
        await self.process.stdin.drain()
    
    async def list_tools(self) -> List[Tool]:
        """列出工具"""
        if not self._initialized:
            await self.initialize()
        result = await self._send("tools/list")
        return [Tool(name=t["name"], description=t.get("description",""), input_schema=t.get("inputSchema",{})) for t in result.get("tools", [])]
    
    async def call_tool(self, name: str, args: Dict) -> Any:
        """调用工具"""
        if not self._initialized:
            await self.initialize()
        return await self._send("tools/call", {"name": name, "arguments": args})
    
    async def close(self) -> None:
        """关闭"""
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
