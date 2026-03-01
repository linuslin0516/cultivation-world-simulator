"""Routes for game control (pause, resume, reset, shutdown, reinit, phenomenon)."""
import os
import signal
import time
import threading
import asyncio

from fastapi import APIRouter, HTTPException

from src.server.state import game_instance
from src.server.serializers import serialize_phenomenon
from src.server.schemas import SetPhenomenonRequest
from src.classes.celestial_phenomenon import celestial_phenomena_by_id

router = APIRouter()


@router.post("/api/control/reset")
def reset_game():
    """重置游戏到 Idle 状态（回到主菜单）"""
    game_instance["world"] = None
    game_instance["sim"] = None
    game_instance["is_paused"] = True
    game_instance["init_status"] = "idle"
    game_instance["init_phase"] = 0
    game_instance["init_progress"] = 0
    game_instance["init_error"] = None
    return {"status": "ok", "message": "Game reset to idle"}


@router.post("/api/control/pause")
def pause_game():
    """暂停游戏循环"""
    game_instance["is_paused"] = True
    return {"status": "ok", "message": "Game paused"}


@router.post("/api/control/resume")
def resume_game():
    """恢复游戏循环"""
    game_instance["is_paused"] = False
    return {"status": "ok", "message": "Game resumed"}


@router.post("/api/control/shutdown")
async def shutdown_server():
    def _shutdown():
        time.sleep(1)  # 给前端一点时间接收 200 OK 响应
        os.kill(os.getpid(), signal.SIGINT)

    # 异步执行关闭，确保先返回响应
    threading.Thread(target=_shutdown).start()
    return {"status": "shutting_down", "message": "Server is shutting down..."}


@router.post("/api/control/reinit")
async def reinit_game():
    """重新初始化游戏（用于错误恢复）。"""
    from src.server.game_loop import init_game_async
    from src.server.main import ASSETS_PATH

    # 清理旧的游戏状态
    game_instance["world"] = None
    game_instance["sim"] = None
    game_instance["init_status"] = "pending"
    game_instance["init_phase"] = 0
    game_instance["init_progress"] = 0
    game_instance["init_error"] = None

    # 启动异步初始化任务
    asyncio.create_task(init_game_async(ASSETS_PATH))

    return {"status": "ok", "message": "Reinitialization started"}


@router.get("/api/meta/phenomena")
def get_phenomena_list():
    """获取所有可选的天地灵机列表"""
    result = []
    for p in sorted(celestial_phenomena_by_id.values(), key=lambda x: x.id):
        result.append(serialize_phenomenon(p))
    return {"phenomena": result}


@router.post("/api/control/set_phenomenon")
def set_phenomenon(req: SetPhenomenonRequest):
    world = game_instance.get("world")
    if not world:
        raise HTTPException(status_code=503, detail="World not initialized")

    p = celestial_phenomena_by_id.get(req.id)
    if not p:
        raise HTTPException(status_code=404, detail="Phenomenon not found")

    world.current_phenomenon = p

    # 重置计时器，使其从当前年份开始重新计算持续时间
    try:
        current_year = int(world.month_stamp.get_year())
        world.phenomenon_start_year = current_year
    except Exception:
        pass

    return {"status": "ok", "message": f"Phenomenon set to {p.name}"}
