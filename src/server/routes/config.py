"""Routes for configuration, language, LLM settings, and game initialization."""
import os
import asyncio
import time

from fastapi import APIRouter, HTTPException
from omegaconf import OmegaConf

from src.server.state import game_instance
from src.server.websocket import manager
from src.server.schemas import (
    GameStartRequest, LanguageRequest, LLMConfigDTO, TestConnectionRequest,
)
from src.utils.config import CONFIG, load_config
from src.utils.llm.client import test_connectivity
from src.utils.llm.config import LLMConfig, LLMMode
from src.classes.language import language_manager, LanguageType
from src.run.data_loader import reload_all_static_data

router = APIRouter()


@router.get("/api/init-status")
def get_init_status():
    """获取初始化状态。"""
    status = game_instance.get("init_status", "idle")
    start_time = game_instance.get("init_start_time")
    elapsed = time.time() - start_time if start_time else 0

    return {
        "status": status,
        "phase": game_instance.get("init_phase", 0),
        "phase_name": game_instance.get("init_phase_name", ""),
        "progress": game_instance.get("init_progress", 0),
        "elapsed_seconds": round(elapsed, 1),
        "error": game_instance.get("init_error"),
        # 额外信息：LLM 状态
        "llm_check_failed": game_instance.get("llm_check_failed", False),
        "llm_error_message": game_instance.get("llm_error_message", ""),
    }


@router.get("/api/config/current")
def get_current_config():
    """获取当前游戏配置（用于回显）"""
    return {
        "game": {
            "init_npc_num": getattr(CONFIG.game, "init_npc_num", 12),
            "sect_num": getattr(CONFIG.game, "sect_num", 3),
            "npc_awakening_rate_per_month": getattr(CONFIG.game, "npc_awakening_rate_per_month", 0.01),
            "world_history": getattr(CONFIG.game, "world_history", "")
        },
        "avatar": {
            "protagonist": getattr(CONFIG.avatar, "protagonist", "none")
        }
    }


@router.get("/api/config/llm/status")
def get_llm_status():
    """获取 LLM 配置状态"""
    key = getattr(CONFIG.llm, "key", "")
    base_url = getattr(CONFIG.llm, "base_url", "")
    return {
        "configured": bool(key and base_url)
    }


@router.post("/api/game/start")
async def start_game(req: GameStartRequest):
    """保存配置并开始新游戏。"""
    from src.server.game_loop import init_game_async
    from src.server.main import ASSETS_PATH

    current_status = game_instance.get("init_status", "idle")
    if current_status == "in_progress":
        raise HTTPException(status_code=400, detail="Game is already initializing")

    # 1. 保存到 local_config.yml
    local_config_path = "static/local_config.yml"

    # 读取现有 local_config 或创建新的
    if os.path.exists(local_config_path):
        conf = OmegaConf.load(local_config_path)
    else:
        conf = OmegaConf.create({})

    # 确保结构存在
    if "game" not in conf: conf.game = {}
    if "avatar" not in conf: conf.avatar = {}

    # 更新值
    conf.game.init_npc_num = req.init_npc_num
    conf.game.sect_num = req.sect_num
    conf.game.npc_awakening_rate_per_month = req.npc_awakening_rate_per_month
    conf.game.world_history = req.world_history or ""
    conf.avatar.protagonist = req.protagonist

    # 写入文件
    try:
        OmegaConf.save(conf, local_config_path)
    except Exception as e:
        print(f"Error saving local config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")

    # 2. 重新加载全局 CONFIG
    try:
        new_config = load_config()
        CONFIG.merge_with(new_config)
    except Exception as e:
        print(f"Error reloading config: {e}")

    # 3. 开始初始化
    if current_status == "ready":
        # 清理旧的游戏状态
        game_instance["world"] = None
        game_instance["sim"] = None

    game_instance["init_status"] = "pending"
    game_instance["init_phase"] = 0
    game_instance["init_progress"] = 0
    game_instance["init_error"] = None

    # 启动异步初始化任务
    asyncio.create_task(init_game_async(ASSETS_PATH))

    return {"status": "ok", "message": "Game initialization started"}


@router.get("/api/config/language")
def get_language_api():
    """获取当前语言设置"""
    return {"lang": str(language_manager)}


@router.post("/api/config/language")
def set_language_api(req: LanguageRequest):
    """设置并保存语言设置"""
    # 1. 更新内存
    language_manager.set_language(req.lang)

    # 2. 更新路径配置
    from src.utils.config import update_paths_for_language
    update_paths_for_language(req.lang)

    # 3. 重新加载 CSV 数据
    from src.utils.df import reload_game_configs
    reload_game_configs()

    # 4. 重新加载所有业务静态数据 (Sects, Techniques, etc.)
    reload_all_static_data()

    # 5. 持久化到 local_config.yml
    local_config_path = "static/local_config.yml"
    try:
        if os.path.exists(local_config_path):
            conf = OmegaConf.load(local_config_path)
        else:
            conf = OmegaConf.create({})

        if "system" not in conf:
            conf.system = {}

        conf.system.language = str(language_manager)

        OmegaConf.save(conf, local_config_path)

        # 同时更新全局 CONFIG
        if not hasattr(CONFIG, "system"):
            pass

        return {"status": "ok"}
    except Exception as e:
        print(f"Error saving language config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save language config: {e}")


@router.get("/api/config/llm")
def get_llm_config():
    """获取当前 LLM 配置"""
    return {
        "base_url": getattr(CONFIG.llm, "base_url", ""),
        "api_key": getattr(CONFIG.llm, "key", ""),
        "model_name": getattr(CONFIG.llm, "model_name", ""),
        "fast_model_name": getattr(CONFIG.llm, "fast_model_name", ""),
        "mode": getattr(CONFIG.llm, "mode", "default"),
        "max_concurrent_requests": getattr(CONFIG.ai, "max_concurrent_requests", 10)
    }


@router.post("/api/config/llm/test")
def test_llm_connection(req: TestConnectionRequest):
    """测试 LLM 连接"""
    try:
        # 构造临时配置
        config = LLMConfig(
            base_url=req.base_url,
            api_key=req.api_key,
            model_name=req.model_name
        )

        success, error_msg = test_connectivity(config=config)

        if success:
            return {"status": "ok", "message": "连接成功"}
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试出错: {str(e)}")


@router.post("/api/config/llm/save")
async def save_llm_config(req: LLMConfigDTO):
    """保存 LLM 配置"""
    try:
        # 1. Update In-Memory Config
        CONFIG.llm.base_url = req.base_url
        CONFIG.llm.key = req.api_key
        CONFIG.llm.model_name = req.model_name
        CONFIG.llm.fast_model_name = req.fast_model_name
        CONFIG.llm.mode = req.mode

        # 更新 ai 配置
        if req.max_concurrent_requests:
            if not hasattr(CONFIG, "ai"):
                 CONFIG.ai = OmegaConf.create({})
            CONFIG.ai.max_concurrent_requests = req.max_concurrent_requests

        # 2. Persist to local_config.yml
        local_config_path = "static/local_config.yml"

        if os.path.exists(local_config_path):
            conf = OmegaConf.load(local_config_path)
        else:
            conf = OmegaConf.create({})

        if "llm" not in conf:
            conf.llm = {}

        conf.llm.base_url = req.base_url
        conf.llm.key = req.api_key
        conf.llm.model_name = req.model_name
        conf.llm.fast_model_name = req.fast_model_name
        conf.llm.mode = req.mode

        if req.max_concurrent_requests:
            if "ai" not in conf:
                conf.ai = {}
            conf.ai.max_concurrent_requests = req.max_concurrent_requests

        OmegaConf.save(conf, local_config_path)

        # ===== 如果之前 LLM 连接失败，现在恢复运行 =====
        if game_instance.get("llm_check_failed", False):
            print("检测到之前 LLM 连接失败，正在恢复 Simulator 运行...")

            game_instance["llm_check_failed"] = False
            game_instance["llm_error_message"] = ""
            game_instance["is_paused"] = False

            print("Simulator 已恢复运行 ✓")

            await manager.broadcast({
                "type": "game_reinitialized",
                "message": "LLM 配置成功，游戏已恢复运行"
            })

        return {"status": "ok", "message": "配置已保存"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")
