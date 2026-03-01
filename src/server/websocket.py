"""WebSocket connection management and endpoint."""
import json
import time

from fastapi import WebSocket, WebSocketDisconnect, APIRouter

from src.server.state import game_instance

ws_router = APIRouter()


class ConnectionManager:
    def __init__(self, max_messages_per_second: int = 10):
        self.active_connections: list[WebSocket] = []
        self._rate_limit = max_messages_per_second
        self._message_counts: dict[WebSocket, list[float]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

        # 不再自动恢复游戏，让用户明确选择"新游戏"或"加载存档"。
        if len(self.active_connections) == 1:
            print("[Auto-Control] 检测到客户端连接，游戏保持暂停状态，等待用户操作。")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        # Clean up rate limit data
        self._message_counts.pop(websocket, None)

        # 当最后一个客户端断开时，自动暂停游戏
        if len(self.active_connections) == 0:
            self._set_pause_state(True, "所有客户端已断开，自动暂停游戏以节省资源。")

    def _set_pause_state(self, should_pause: bool, log_msg: str):
        """辅助方法：切换暂停状态并打印日志"""
        if game_instance.get("is_paused") != should_pause:
            game_instance["is_paused"] = should_pause
            print(f"[Auto-Control] {log_msg}")

    def _check_rate_limit(self, websocket: WebSocket) -> bool:
        """Check if a WebSocket client has exceeded the rate limit."""
        now = time.monotonic()
        timestamps = self._message_counts.get(websocket, [])
        # Remove timestamps older than 1 second
        timestamps = [t for t in timestamps if now - t < 1.0]
        if len(timestamps) >= self._rate_limit:
            return False
        timestamps.append(now)
        self._message_counts[websocket] = timestamps
        return True

    async def broadcast(self, message: dict):
        try:
            txt = json.dumps(message, default=str)
            for connection in self.active_connections:
                await connection.send_text(txt)
        except Exception as e:
            print(f"Broadcast error: {e}")


manager = ConnectionManager()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    # ===== 检查 LLM 状态并通知前端 =====
    if game_instance.get("llm_check_failed", False):
        error_msg = game_instance.get("llm_error_message", "LLM 连接失败")
        await websocket.send_json({
            "type": "llm_config_required",
            "error": error_msg
        })
        print(f"已向客户端发送 LLM 配置要求: {error_msg}")
    # ===== 检测结束 =====

    try:
        while True:
            # 保持连接活跃，接收客户端指令
            data = await websocket.receive_text()

            # Rate limiting
            if not manager._check_rate_limit(websocket):
                await websocket.send_text('{"type":"error","message":"Rate limit exceeded"}')
                continue

            # Message size limit (1KB)
            if len(data) > 1024:
                await websocket.send_text('{"type":"error","message":"Message too large"}')
                continue

            # echo test
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WS Error: {e}")
        manager.disconnect(websocket)
