"""
SYUTAINβ V25 MCP統合マネージャー (Step 15)
設計書 第5章 5.2準拠

MCPサーバー接続を動的に確認し、
接続不可時は直接APIフォールバックで処理を継続する（CLAUDE.mdルール20）。
"""

import os
import asyncio
import logging
from typing import Optional, Any
from pathlib import Path

import yaml
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.mcp_manager")

# MCP設定ファイルパス
MCP_CONFIG_PATH = os.getenv("MCP_CONFIG_PATH", "mcp_servers/config.yaml")


class MCPServerInfo:
    """MCP サーバー情報"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.description = config.get("description", "")
        self.transport = config.get("transport", "stdio")
        self.url = config.get("url", "")
        self.command = config.get("command", "")
        self.args = config.get("args", [])
        self.env = config.get("env", {})
        self.enabled = config.get("enabled", True)
        self.status: str = "unknown"  # available / unavailable / unknown
        self.fallback_fn: Optional[str] = config.get("fallback", None)


class MCPManager:
    """MCP統合マネージャー"""

    def __init__(self):
        self.servers: dict[str, MCPServerInfo] = {}
        self._health_task: Optional[asyncio.Task] = None

    def load_config(self, config_path: Optional[str] = None) -> None:
        """mcp_servers/config.yaml からMCPサーバー設定を読み込む"""
        path = Path(config_path or MCP_CONFIG_PATH)
        try:
            if not path.exists():
                logger.warning(f"MCP設定ファイルなし: {path}")
                return
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            for srv_cfg in cfg.get("mcp_servers", []):
                name = srv_cfg.get("name", "")
                if name:
                    self.servers[name] = MCPServerInfo(name, srv_cfg)
                    logger.info(f"MCPサーバー登録: {name} ({srv_cfg.get('transport', 'stdio')})")
        except Exception as e:
            logger.error(f"MCP設定読み込み失敗: {e}")

    async def start(self) -> None:
        """MCPマネージャーを起動（設定読み込み + ヘルスチェック開始）"""
        self.load_config()
        await self.check_all_connections()
        # 定期ヘルスチェック（5分間隔）
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    # ===== 接続チェック =====

    async def check_connection(self, name: str) -> bool:
        """特定MCPサーバーへの接続を確認"""
        srv = self.servers.get(name)
        if not srv or not srv.enabled:
            return False

        try:
            if srv.transport == "stdio":
                # stdio系はコマンドが実行可能か確認
                ok = await self._check_stdio_server(srv)
            elif srv.url:
                # HTTP系はURL到達性を確認
                ok = await self._check_http_server(srv)
            else:
                ok = False

            srv.status = "available" if ok else "unavailable"
            return ok
        except Exception as e:
            logger.warning(f"MCP接続チェック失敗 ({name}): {e}")
            srv.status = "unavailable"
            return False

    async def check_all_connections(self) -> dict[str, bool]:
        """全MCPサーバーの接続チェック"""
        results = {}
        for name in self.servers:
            try:
                results[name] = await self.check_connection(name)
            except Exception as e:
                logger.error(f"MCPチェック失敗 ({name}): {e}")
                results[name] = False
        return results

    async def _check_stdio_server(self, srv: MCPServerInfo) -> bool:
        """stdio系MCPサーバーのチェック（コマンド存在確認）"""
        if not srv.command:
            return True  # コマンド未指定は常時OK（組み込みサーバー）
        try:
            import shutil
            return shutil.which(srv.command) is not None
        except Exception:
            return False

    async def _check_http_server(self, srv: MCPServerInfo) -> bool:
        """HTTP系MCPサーバーの到達性チェック"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.head(srv.url)
                return resp.status_code < 500
        except Exception:
            return False

    async def _health_loop(self) -> None:
        """5分間隔で全MCPサーバーをヘルスチェック"""
        while True:
            await asyncio.sleep(300)
            try:
                results = await self.check_all_connections()
                unavailable = [n for n, ok in results.items() if not ok]
                if unavailable:
                    logger.warning(f"MCP接続不可サーバー: {unavailable}")
            except Exception as e:
                logger.error(f"MCPヘルスチェックエラー: {e}")

    # ===== ツール実行（MCP優先 → 直接APIフォールバック）=====

    async def call_tool(self, server_name: str, tool_name: str, params: dict = None) -> dict:
        """MCPツール実行。接続不可時は直接APIにフォールバック"""
        srv = self.servers.get(server_name)

        # MCP接続可能であればMCP経由で実行
        if srv and srv.status == "available":
            try:
                result = await self._call_mcp_tool(srv, tool_name, params or {})
                return {"source": "mcp", "server": server_name, "result": result}
            except Exception as e:
                logger.warning(f"MCPツール実行失敗 ({server_name}/{tool_name}): {e}")
                srv.status = "unavailable"

        # 直接APIフォールバック（設計書ルール20: MCP接続不可時は代替手段で処理を継続）
        logger.info(f"MCP不可 → 直接APIフォールバック: {server_name}/{tool_name}")
        try:
            result = await self._direct_api_fallback(server_name, tool_name, params or {})
            return {"source": "direct_api", "server": server_name, "result": result}
        except Exception as e:
            logger.error(f"直接APIフォールバックも失敗 ({server_name}/{tool_name}): {e}")
            return {"source": "error", "server": server_name, "error": str(e)}

    async def _call_mcp_tool(self, srv: MCPServerInfo, tool_name: str, params: dict) -> Any:
        """MCPプロトコル経由でツール実行（プレースホルダー）"""
        # 実際のMCP SDK統合はここに実装
        raise NotImplementedError("MCP SDK統合は別途実装")

    async def _direct_api_fallback(self, server_name: str, tool_name: str, params: dict) -> Any:
        """直接APIフォールバック"""
        fallback_map = {
            "tavily-mcp": self._fallback_tavily,
            "jina-mcp": self._fallback_jina,
            "github-mcp": self._fallback_github,
            "gmail-mcp": self._fallback_gmail,
            "bluesky-mcp": self._fallback_bluesky,
        }
        handler = fallback_map.get(server_name)
        if handler:
            return await handler(tool_name, params)
        raise ValueError(f"フォールバック未定義: {server_name}")

    async def _fallback_tavily(self, tool_name: str, params: dict) -> dict:
        """Tavily直接API"""
        from tools.tavily_client import TavilyClient
        client = TavilyClient()
        return await client.search(params.get("query", ""))

    async def _fallback_jina(self, tool_name: str, params: dict) -> dict:
        """Jina Reader直接API"""
        from tools.jina_client import JinaClient
        client = JinaClient()
        return await client.read_url(params.get("url", ""))

    async def _fallback_github(self, tool_name: str, params: dict) -> dict:
        """GitHub直接API"""
        api_token = os.getenv("GITHUB_TOKEN", "")
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {"Authorization": f"token {api_token}"} if api_token else {}
            resp = await client.get(
                f"https://api.github.com/{params.get('endpoint', 'user')}",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _fallback_gmail(self, tool_name: str, params: dict) -> dict:
        """Gmail直接API（プレースホルダー）"""
        logger.warning("Gmail直接APIフォールバック: OAuth2認証が必要")
        return {"status": "requires_oauth2"}

    async def _fallback_bluesky(self, tool_name: str, params: dict) -> dict:
        """Bluesky AT Protocol直接API"""
        handle = os.getenv("BLUESKY_HANDLE", "")
        password = os.getenv("BLUESKY_APP_PASSWORD", "")
        if not handle or not password:
            return {"status": "credentials_missing"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            # セッション作成
            resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": password},
            )
            resp.raise_for_status()
            return resp.json()

    # ===== ステータス =====

    def get_status(self) -> dict:
        return {
            name: {
                "description": srv.description,
                "transport": srv.transport,
                "status": srv.status,
                "enabled": srv.enabled,
            }
            for name, srv in self.servers.items()
        }


# シングルトン
_manager: Optional[MCPManager] = None


async def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
        await _manager.start()
    return _manager
