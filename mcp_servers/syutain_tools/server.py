"""
SYUTAINβ V25 MCPサーバー (Step 15)
設計書 第5章 5.2準拠

SYUTAINβ固有ツールをMCPプロトコルで外部に公開する。
Tools: search_web, read_url, check_email, post_social
"""

import os
import json
import asyncio
import logging
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.mcp_server")

# MCPツール定義
TOOLS = [
    {
        "name": "search_web",
        "description": "Tavily APIでWeb検索を実行。日本語対応。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ"},
                "max_results": {"type": "integer", "default": 5},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "default": "basic"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_url",
        "description": "Jina ReaderでURLをMarkdownテキストに変換",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "読み取るURL"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "check_email",
        "description": "Gmail APIで最新メールを確認（AI/Tech関連キーワードフィルタ）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "検索キーワード"},
                "max_results": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "post_social",
        "description": "SNSに投稿（承認必須）。X(Twitter)またはBlueskyに対応。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["x", "bluesky"]},
                "content": {"type": "string", "description": "投稿内容"},
            },
            "required": ["platform", "content"],
        },
    },
]


class SyutainMCPServer:
    """SYUTAINβ MCPサーバー（stdioトランスポート）"""

    def __init__(self):
        self._handlers = {
            "search_web": self._handle_search_web,
            "read_url": self._handle_read_url,
            "check_email": self._handle_check_email,
            "post_social": self._handle_post_social,
        }

    async def handle_request(self, request: dict) -> dict:
        """MCPリクエストを処理"""
        method = request.get("method", "")

        if method == "initialize":
            return self._initialize_response(request)
        elif method == "tools/list":
            return {"tools": TOOLS}
        elif method == "tools/call":
            return await self._call_tool(request)
        else:
            return {"error": {"code": -32601, "message": f"Unknown method: {method}"}}

    def _initialize_response(self, request: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "syutain-tools",
                "version": "0.1.0",
            },
        }

    async def _call_tool(self, request: dict) -> dict:
        """ツール呼び出しを実行"""
        params = request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = self._handlers.get(tool_name)
        if not handler:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        # 2026-04-12 P2-4: malware 検証
        try:
            from tools.mcp_malware_verification import verify_and_log
            verification = await verify_and_log(tool_name, arguments)
            if verification.is_blocked:
                logger.critical(f"MCP BLOCKED: {tool_name} issues={verification.issues[:2]}")
                return {
                    "content": [{"type": "text", "text": f"Blocked by malware verification: {verification.issues[0].get('type', '?')}"}],
                    "isError": True,
                }
        except Exception as e:
            logger.warning(f"malware check failed (continuing): {e}")

        try:
            result = await handler(arguments)
            return {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            }
        except Exception as e:
            logger.error(f"MCPツール実行エラー ({tool_name}): {e}")
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    # ===== ツール実装 =====

    async def _handle_search_web(self, args: dict) -> dict:
        """Tavily検索"""
        try:
            from tools.tavily_client import TavilyClient
            client = TavilyClient()
            return await client.search(
                query=args.get("query", ""),
                max_results=args.get("max_results", 5),
                search_depth=args.get("search_depth", "basic"),
            )
        except Exception as e:
            logger.error(f"search_webエラー: {e}")
            return {"error": str(e)}

    async def _handle_read_url(self, args: dict) -> dict:
        """Jina Reader URL読み取り"""
        try:
            from tools.jina_client import JinaClient
            client = JinaClient()
            return await client.read_url(args.get("url", ""))
        except Exception as e:
            logger.error(f"read_urlエラー: {e}")
            return {"error": str(e)}

    async def _handle_check_email(self, args: dict) -> dict:
        """Gmail確認（プレースホルダー: OAuth2認証が必要）"""
        logger.info("check_email: Gmail OAuth2認証が必要です")
        return {
            "status": "requires_setup",
            "message": "Gmail OAuth2認証を設定してください",
            "keywords_requested": args.get("keywords", []),
        }

    async def _handle_post_social(self, args: dict) -> dict:
        """SNS投稿（承認必須 — CLAUDE.mdルール11）"""
        platform = args.get("platform", "")
        content = args.get("content", "")

        # 承認チェック（ApprovalManager経由が必須）
        logger.info(f"post_social: {platform}投稿は承認が必要です")
        return {
            "status": "approval_required",
            "platform": platform,
            "content": content,
            "message": "SNS投稿にはApprovalManagerによる承認が必要です",
        }


async def run_stdio_server() -> None:
    """stdioトランスポートでMCPサーバーを実行"""
    server = SyutainMCPServer()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, os.fdopen(0, "rb"))

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, os.fdopen(1, "wb")
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_event_loop())

    logger.info("SYUTAINβ MCPサーバー起動 (stdio)")

    while True:
        try:
            # Content-Length ヘッダ読み取り
            header = await reader.readline()
            if not header:
                break
            header_str = header.decode().strip()
            if header_str.startswith("Content-Length:"):
                content_length = int(header_str.split(":")[1].strip())
                await reader.readline()  # 空行をスキップ
                body = await reader.readexactly(content_length)
                request = json.loads(body.decode())

                response = await server.handle_request(request)

                # JSON-RPCレスポンス
                if "id" in request:
                    rpc_response = {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": response,
                    }
                    response_bytes = json.dumps(rpc_response, ensure_ascii=False).encode()
                    writer.write(f"Content-Length: {len(response_bytes)}\r\n\r\n".encode())
                    writer.write(response_bytes)
                    await writer.drain()
        except asyncio.IncompleteReadError:
            break
        except Exception as e:
            logger.error(f"MCPサーバーエラー: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_stdio_server())
