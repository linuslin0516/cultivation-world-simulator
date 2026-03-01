"""Routes for save/load/delete game state."""
import os
import asyncio
import time

from fastapi import APIRouter, HTTPException
from omegaconf import OmegaConf

from src.server.state import game_instance
from src.server.websocket import manager
from src.server.utils import scan_avatar_assets, validate_save_name
from src.server.schemas import SaveGameRequest, DeleteSaveRequest, LoadGameRequest
from src.utils.config import CONFIG
from src.sim import save_game, list_saves, load_game, get_events_db_path
from src.classes.core.sect import sects_by_id
from src.classes.language import language_manager
from src.run.data_loader import reload_all_static_data

router = APIRouter()


@router.get("/api/saves")
def get_saves():
    """获取存档列表"""
    saves_list = list_saves()
    result = []
    for path, meta in saves_list:
        result.append({
            "filename": path.name,
            "save_time": meta.get("save_time", ""),
            "game_time": meta.get("game_time", ""),
            "version": meta.get("version", ""),
            "language": meta.get("language", ""),
            "avatar_count": meta.get("avatar_count", 0),
            "alive_count": meta.get("alive_count", 0),
            "dead_count": meta.get("dead_count", 0),
            "protagonist_name": meta.get("protagonist_name"),
            "custom_name": meta.get("custom_name"),
            "event_count": meta.get("event_count", 0),
        })
    return {"saves": result}


@router.post("/api/game/save")
def api_save_game(req: SaveGameRequest):
    """保存游戏"""
    world = game_instance.get("world")
    sim = game_instance.get("sim")
    if not world or not sim:
        raise HTTPException(status_code=503, detail="Game not initialized")

    existed_sects = getattr(world, "existed_sects", [])
    if not existed_sects:
        existed_sects = list(sects_by_id.values())

    # 名称验证
    custom_name = req.custom_name
    if custom_name and not validate_save_name(custom_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid save name"
        )

    success, filename = save_game(world, sim, existed_sects, custom_name=custom_name)
    if success:
        return {"status": "ok", "filename": filename}
    else:
        raise HTTPException(status_code=500, detail="Save failed")


@router.post("/api/game/delete")
def api_delete_game(req: DeleteSaveRequest):
    """删除存档及其关联文件"""
    # 安全检查
    if ".." in req.filename or "/" in req.filename or "\\" in req.filename:
         raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        saves_dir = CONFIG.paths.saves
        target_path = saves_dir / req.filename

        # 1. 删除 JSON 存档文件
        if target_path.exists():
            os.remove(target_path)

        # 2. 删除对应的 SQL 数据库文件
        events_db_path = get_events_db_path(target_path)
        if os.path.exists(events_db_path):
            try:
                os.remove(events_db_path)
            except Exception as e:
                print(f"[Warning] Failed to delete db file {events_db_path}: {e}")

        return {"status": "ok", "message": "Save deleted"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@router.post("/api/game/load")
async def api_load_game(req: LoadGameRequest):
    """加载游戏（异步，支持进度更新）。"""
    from src.server.main import ASSETS_PATH

    # 安全检查
    if ".." in req.filename or "/" in req.filename or "\\" in req.filename:
         raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        saves_dir = CONFIG.paths.saves
        target_path = saves_dir / req.filename

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        # --- 语言环境自动切换 ---
        from src.sim import get_save_info
        save_meta = get_save_info(target_path)
        if save_meta:
            save_lang = save_meta.get("language")
            current_lang = str(language_manager)

            print(f"[Debug] Load Game - Save Lang: {save_lang}, Current Lang: {current_lang}")

            if save_lang:
                print(f"[Auto-Switch] Enforcing language sync to {save_lang}...")

                # 1. 通知前端
                await manager.broadcast({
                    "type": "toast",
                    "level": "info",
                    "message": f"正在同步语言设置: {save_lang}...",
                    "language": save_lang
                })

                await asyncio.sleep(0.2)

                # 2. 只有当后端语言确实不同步时，才执行后端切换逻辑
                if save_lang != current_lang:
                    print(f"[Auto-Switch] Switching backend language from {current_lang} to {save_lang}...")
                    await asyncio.to_thread(language_manager.set_language, save_lang)
                    await asyncio.to_thread(reload_all_static_data)

                    # 持久化语言设置
                    local_config_path = "static/local_config.yml"
                    try:
                        if os.path.exists(local_config_path):
                            conf = OmegaConf.load(local_config_path)
                        else:
                            conf = OmegaConf.create({})

                        if "system" not in conf:
                            conf.system = OmegaConf.create({})
                        conf.system.language = save_lang
                        OmegaConf.save(conf, local_config_path)
                    except Exception as e:
                        print(f"Warning: Failed to persist language switch: {e}")
        # -----------------------

        # 设置加载状态
        game_instance["init_status"] = "in_progress"
        game_instance["init_start_time"] = time.time()
        game_instance["init_error"] = None
        game_instance["init_phase"] = 0

        # 0. 扫描资源
        game_instance["init_phase_name"] = "scanning_assets"
        await asyncio.to_thread(scan_avatar_assets, ASSETS_PATH)

        game_instance["init_phase_name"] = "loading_save"
        game_instance["init_progress"] = 10

        # 暂停游戏
        game_instance["is_paused"] = True
        await asyncio.sleep(0)

        game_instance["init_progress"] = 30
        game_instance["init_phase_name"] = "parsing_data"
        await asyncio.sleep(0)

        # 关闭旧 World 的 EventManager
        old_world = game_instance.get("world")
        if old_world and hasattr(old_world, "event_manager"):
            old_world.event_manager.close()

        # 加载
        new_world, new_sim, new_sects = load_game(target_path)

        game_instance["init_progress"] = 70
        game_instance["init_phase_name"] = "restoring_state"
        await asyncio.sleep(0)

        new_world.existed_sects = new_sects

        # 替换全局实例
        game_instance["world"] = new_world
        game_instance["sim"] = new_sim
        game_instance["current_save_path"] = target_path

        game_instance["init_progress"] = 90
        game_instance["init_phase_name"] = "finalizing"
        await asyncio.sleep(0)

        # 加载完成
        game_instance["init_status"] = "ready"
        game_instance["init_progress"] = 100
        game_instance["init_phase_name"] = "complete"

        return {"status": "ok", "message": "Game loaded"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        game_instance["init_status"] = "error"
        game_instance["init_error"] = str(e)
        raise HTTPException(status_code=500, detail=f"Load failed: {str(e)}")
