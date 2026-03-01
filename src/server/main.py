"""Cultivation World Simulator - FastAPI Server Entry Point."""
import sys
import os
import asyncio
import webbrowser
import subprocess
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

# 确保可以导入 src 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.config import CONFIG

# --- Import from extracted modules ---
# Re-exported for backward compatibility with tests that import from src.server.main
from src.server.state import game_instance, AVATAR_ASSETS  # noqa: F401
from src.server.utils import (  # noqa: F401
    scan_avatar_assets, ensure_npm_dependencies,
    EndpointFilter, IS_DEV_MODE,
    resolve_avatar_pic_id, resolve_avatar_action_emoji,
    check_llm_connectivity, validate_save_name, get_avatar_pic_id,
)
from src.server.schemas import (  # noqa: F401
    GameStartRequest, SetObjectiveRequest, ClearObjectiveRequest,
    CreateAvatarRequest, DeleteAvatarRequest, SetPhenomenonRequest,
    LanguageRequest, LLMConfigDTO, TestConnectionRequest,
    SaveGameRequest, DeleteSaveRequest, LoadGameRequest,
)
from src.server.serializers import (  # noqa: F401
    serialize_events_for_client, serialize_phenomenon, serialize_active_domains,
)
from src.server.websocket import manager, ws_router, ConnectionManager  # noqa: F401
from src.server.game_loop import (  # noqa: F401
    game_loop, init_game_async, update_init_progress, INIT_PHASE_NAMES,
)

# Route imports
from src.server.routes.game_state import router as game_state_router
from src.server.routes.events import router as events_router
from src.server.routes.game_control import router as game_control_router
from src.server.routes.avatar import router as avatar_router
from src.server.routes.config import router as config_router
from src.server.routes.saves import router as saves_router

# Language (for lifespan)
from src.classes.language import language_manager
from src.run.data_loader import reload_all_static_data

# --- Path setup (frozen vs dev) ---
if getattr(sys, 'frozen', False):
    # PyInstaller 打包模式
    exe_dir = os.path.dirname(sys.executable)
    WEB_DIST_PATH = os.path.join(exe_dir, 'web_static')
    ASSETS_PATH = os.path.join(sys._MEIPASS, 'assets')
else:
    # 开发模式
    base_path = os.path.join(os.path.dirname(__file__), '..', '..')
    WEB_DIST_PATH = os.path.join(base_path, 'web', 'dist')
    ASSETS_PATH = os.path.join(base_path, 'assets')

WEB_DIST_PATH = os.path.abspath(WEB_DIST_PATH)
ASSETS_PATH = os.path.abspath(ASSETS_PATH)

print(f"Runtime mode: {'Frozen/Packaged' if getattr(sys, 'frozen', False) else 'Development'}")
print(f"Assets path: {ASSETS_PATH}")
print(f"Web dist path: {WEB_DIST_PATH}")


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Filter out health check / polling logs
    logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

    # 初始化语言设置
    from src.utils.config import update_paths_for_language
    from src.utils.df import reload_game_configs

    system_conf = getattr(CONFIG, "system", None)
    if system_conf:
        lang_code = getattr(system_conf, "language", "zh-CN")
        language_manager.set_language(str(lang_code))
    else:
        language_manager.set_language("zh-CN")

    # 根据语言初始化路径
    update_paths_for_language()
    reload_game_configs()
    reload_all_static_data()

    print(f"Current Language: {language_manager}")

    # 启动时不再自动开始初始化游戏，等待前端指令
    print("服务器启动，等待开始游戏指令...")

    # 启动后台游戏循环（会自动等待初始化完成）
    asyncio.create_task(game_loop(ASSETS_PATH))

    npm_process = None
    host = os.environ.get("SERVER_HOST") or getattr(getattr(CONFIG, "system", None), "host", None) or "127.0.0.1"

    if IS_DEV_MODE:
        print("🚀 启动开发模式 (Dev Mode)...")
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
        web_dir = os.path.join(project_root, 'web')

        ensure_npm_dependencies(web_dir)

        print(f"正在启动前端开发服务 (npm run dev) 于: {web_dir}")
        try:
            import platform
            if platform.system() == "Windows":
                npm_process = subprocess.Popen("npm run dev", cwd=web_dir, shell=True)
            else:
                npm_process = subprocess.Popen(["npm", "run", "dev"], cwd=web_dir, shell=False)
            target_url = "http://localhost:5173"
        except Exception as e:
            print(f"启动前端服务失败: {e}")
            target_url = f"http://{host}:8002"
    else:
        target_url = f"http://{host}:8002"

    # 自动打开浏览器
    print(f"Ready! Opening browser at {target_url}")
    try:
        webbrowser.open(target_url)
    except Exception as e:
        print(f"Failed to open browser: {e}")

    yield

    # 关闭时清理
    if npm_process:
        print("正在关闭前端开发服务...")
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(npm_process.pid)])
            else:
                npm_process.terminate()
        except Exception as e:
            print(f"关闭前端服务时出错: {e}")


# --- App creation ---

app = FastAPI(lifespan=lifespan)

# CORS - configurable via env var
allowed_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(ws_router)
app.include_router(game_state_router)
app.include_router(events_router)
app.include_router(game_control_router)
app.include_router(avatar_router)
app.include_router(config_router)
app.include_router(saves_router)

# --- Static file mounting (must be last) ---

if os.path.exists(ASSETS_PATH):
    app.mount("/assets", StaticFiles(directory=ASSETS_PATH), name="assets")
else:
    print(f"Warning: Assets path not found: {ASSETS_PATH}")

if not IS_DEV_MODE:
    if os.path.exists(WEB_DIST_PATH):
        print(f"Serving Web UI from: {WEB_DIST_PATH}")
        app.mount("/", StaticFiles(directory=WEB_DIST_PATH, html=True), name="web_dist")
    else:
        print(f"Warning: Web dist path not found: {WEB_DIST_PATH}.")
else:
    print("Dev Mode: Skipping static file mount for '/' (using Vite dev server instead)")


def start():
    """启动服务的入口函数"""
    host = os.environ.get("SERVER_HOST") or getattr(getattr(CONFIG, "system", None), "host", None) or "127.0.0.1"
    port = int(os.environ.get("SERVER_PORT") or getattr(getattr(CONFIG, "system", None), "port", None) or 8002)

    # 注意：直接传递 app 对象而不是字符串，避免 PyInstaller 打包后找不到模块的问题。
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start()
