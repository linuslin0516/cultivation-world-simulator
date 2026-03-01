"""Game initialization and main loop logic."""
import asyncio
import random
import time

from src.server.state import game_instance, AVATAR_ASSETS
from src.server.websocket import manager
from src.server.utils import (
    scan_avatar_assets, resolve_avatar_pic_id,
    resolve_avatar_action_emoji, check_llm_connectivity,
)
from src.server.serializers import (
    serialize_events_for_client, serialize_phenomenon,
    serialize_active_domains,
)
from src.utils.config import CONFIG, load_config
from src.sim.simulator import Simulator
from src.classes.core.world import World
from src.classes.history import HistoryManager
from src.systems.time import Month, Year, create_month_stamp
from src.run.load_map import load_cultivation_world_map
from src.sim.avatar_init import make_avatars as _new_make_random
from src.classes.core.sect import sects_by_id
from src.run.data_loader import reload_all_static_data
from src.utils import protagonist as prot_utils


# 初始化阶段名称映射（用于前端显示）
INIT_PHASE_NAMES = {
    0: "scanning_assets",
    1: "loading_map",
    2: "processing_history",
    3: "initializing_sects",
    4: "generating_avatars",
    5: "checking_llm",
    6: "generating_initial_events",
}


def update_init_progress(phase: int, phase_name: str = ""):
    """更新初始化进度。"""
    game_instance["init_phase"] = phase
    game_instance["init_phase_name"] = phase_name or INIT_PHASE_NAMES.get(phase, "")
    # 最后一阶段到 100%
    progress_map = {0: 0, 1: 10, 2: 25, 3: 40, 4: 55, 5: 70, 6: 85}
    game_instance["init_progress"] = progress_map.get(phase, phase * 14)
    print(f"[Init] Phase {phase}: {game_instance['init_phase_name']} ({game_instance['init_progress']}%)")


async def init_game_async(assets_path: str = ""):
    """异步初始化游戏世界，带进度更新。"""
    game_instance["init_status"] = "in_progress"
    game_instance["init_start_time"] = time.time()
    game_instance["init_error"] = None

    try:
        # 阶段 0: 资源扫描
        update_init_progress(0, "scanning_assets")

        # === 重置所有静态数据，清除历史修改污染 ===
        print("正在重置世界规则数据...")
        reload_all_static_data()

        await asyncio.to_thread(scan_avatar_assets, assets_path)

        # 阶段 1: 地图加载
        update_init_progress(1, "loading_map")
        game_map = await asyncio.to_thread(load_cultivation_world_map)

        # 初始化 SQLite 事件数据库
        from datetime import datetime
        from src.sim import get_events_db_path

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        save_name = f"save_{timestamp}"
        saves_dir = CONFIG.paths.saves
        saves_dir.mkdir(parents=True, exist_ok=True)
        save_path = saves_dir / f"{save_name}.json"
        events_db_path = get_events_db_path(save_path)

        game_instance["current_save_path"] = save_path
        print(f"事件数据库: {events_db_path}")

        start_year = getattr(CONFIG.game, "start_year", 100)
        world = World.create_with_db(
            map=game_map,
            month_stamp=create_month_stamp(Year(start_year), Month.JANUARY),
            events_db_path=events_db_path,
            start_year=start_year,
        )
        sim = Simulator(world)

        # 阶段 2: 历史背景影响 (如果配置了历史)
        update_init_progress(2, "processing_history")
        world_history = getattr(CONFIG.game, "world_history", "")
        if world_history and world_history.strip():
            world.set_history(world_history)
            print(f"正在根据历史背景重塑世界: {world_history[:50]}...")
            try:
                history_mgr = HistoryManager(world)
                await history_mgr.apply_history_influence(world_history)
                print("历史背景应用完成 ✓")
            except Exception as e:
                print(f"[警告] 历史背景应用失败: {e}")

        # 阶段 3: 宗门初始化
        update_init_progress(3, "initializing_sects")
        all_sects = list(sects_by_id.values())
        needed_sects = int(getattr(CONFIG.game, "sect_num", 0) or 0)
        existed_sects = []
        if needed_sects > 0 and all_sects:
            pool = list(all_sects)
            random.shuffle(pool)
            existed_sects = pool[:needed_sects]

        # 阶段 4: 角色生成
        update_init_progress(4, "generating_avatars")
        protagonist_mode = getattr(CONFIG.avatar, "protagonist", "none")
        target_total_count = int(getattr(CONFIG.game, "init_npc_num", 12))
        final_avatars = {}

        spawned_protagonists_count = 0
        if protagonist_mode in ["all", "random"]:
            prob = 1.0 if protagonist_mode == "all" else 0.05
            def _spawn_protagonists_sync():
                return prot_utils.spawn_protagonists(world, world.month_stamp, probability=prob)
            prot_avatars = await asyncio.to_thread(_spawn_protagonists_sync)
            final_avatars.update(prot_avatars)
            spawned_protagonists_count = len(prot_avatars)
            print(f"生成了 {spawned_protagonists_count} 位主角 (Mode: {protagonist_mode})")

        remaining_count = 0
        if protagonist_mode == "all":
            remaining_count = 0
        else:
            remaining_count = max(0, target_total_count - spawned_protagonists_count)

        if remaining_count > 0:
            def _make_random_sync():
                return _new_make_random(
                    world,
                    count=remaining_count,
                    current_month_stamp=world.month_stamp,
                    existed_sects=existed_sects
                )
            random_avatars = await asyncio.to_thread(_make_random_sync)
            final_avatars.update(random_avatars)
            print(f"生成了 {len(random_avatars)} 位随机路人")

        world.avatar_manager.avatars.update(final_avatars)
        game_instance["world"] = world
        game_instance["sim"] = sim

        # 阶段 5: LLM 连通性检测
        update_init_progress(5, "checking_llm")
        print("正在检测 LLM 连通性...")
        # 使用线程池执行，避免阻塞事件循环
        success, error_msg = await asyncio.to_thread(check_llm_connectivity)

        if not success:
            print(f"[警告] LLM 连通性检测失败: {error_msg}")
            game_instance["llm_check_failed"] = True
            game_instance["llm_error_message"] = error_msg
        else:
            print("LLM 连通性检测通过 ✓")
            game_instance["llm_check_failed"] = False
            game_instance["llm_error_message"] = ""

        # 阶段 6: 生成初始事件（第一次 sim.step）
        update_init_progress(6, "generating_initial_events")
        print("正在生成初始事件...")

        # 取消暂停，执行第一步来生成初始事件
        game_instance["is_paused"] = False
        try:
            await sim.step()
            print("初始事件生成完成 ✓")
        except Exception as e:
            print(f"[警告] 初始事件生成失败: {e}")
        finally:
            # 执行完后重新暂停，等待前端准备好
            game_instance["is_paused"] = True

        # 完成
        game_instance["init_status"] = "ready"
        game_instance["init_progress"] = 100
        print("游戏世界初始化完成！")

    except Exception as e:
        import traceback
        traceback.print_exc()
        game_instance["init_status"] = "error"
        game_instance["init_error"] = str(e)
        print(f"[Error] 初始化失败: {e}")


async def game_loop(assets_path: str):
    """后台自动运行游戏循环。"""
    print("后台游戏循环已启动，等待初始化完成...")

    # 等待初始化完成
    while game_instance.get("init_status") not in ("ready", "error"):
        await asyncio.sleep(0.5)

    if game_instance.get("init_status") == "error":
        print("[game_loop] 初始化失败，游戏循环退出。")
        return

    print("[game_loop] 初始化完成，开始游戏循环。")

    while True:
        # 控制游戏速度，例如每秒 1 次更新
        await asyncio.sleep(1.0)

        try:
            # 检查暂停状态
            if game_instance.get("is_paused", False):
                continue

            # 再次检查初始化状态（可能被重新初始化）
            if game_instance.get("init_status") != "ready":
                continue

            sim = game_instance.get("sim")
            world = game_instance.get("world")

            if sim and world:
                # 执行一步
                events = await sim.step()

                # 获取状态变更 (Source of Truth: AvatarManager)
                newly_born_ids = world.avatar_manager.pop_newly_born()
                newly_dead_ids = world.avatar_manager.pop_newly_dead()

                avatar_updates = []

                # 1. 发送新角色的完整信息
                for aid in newly_born_ids:
                    a = world.avatar_manager.avatars.get(aid)
                    if a:
                        avatar_updates.append({
                            "id": str(a.id),
                            "name": a.name,
                            "x": int(getattr(a, "pos_x", 0)),
                            "y": int(getattr(a, "pos_y", 0)),
                            "gender": a.gender.value,
                            "pic_id": resolve_avatar_pic_id(a),
                            "action": a.current_action_name,
                            "action_emoji": resolve_avatar_action_emoji(a),
                            "is_dead": False
                        })

                # 2. 发送刚死角色的状态更新
                for aid in newly_dead_ids:
                    a = world.avatar_manager.get_avatar(aid)
                    if a:
                        avatar_updates.append({
                            "id": str(a.id),
                            "name": a.name,
                            "is_dead": True,
                            "action": "已故"
                        })

                # 3. 常规位置更新（暂时只发前 50 个旧角色，减少数据量）
                limit = 50
                count = 0
                for a in world.avatar_manager.get_living_avatars():
                    if a.id in newly_born_ids:
                        continue

                    if count < limit:
                        avatar_updates.append({
                            "id": str(a.id),
                            "x": int(getattr(a, "pos_x", 0)),
                            "y": int(getattr(a, "pos_y", 0)),
                            "action_emoji": resolve_avatar_action_emoji(a)
                        })
                        count += 1

                # 构造广播数据包
                state = {
                    "type": "tick",
                    "year": int(world.month_stamp.get_year()),
                    "month": world.month_stamp.get_month().value,
                    "events": serialize_events_for_client(events),
                    "avatars": avatar_updates,
                    "phenomenon": serialize_phenomenon(world.current_phenomenon),
                    "active_domains": serialize_active_domains(world)
                }
                await manager.broadcast(state)
        except Exception as e:
            from src.run.log import get_logger
            print(f"Game loop error: {e}")
            get_logger().logger.error(f"Game loop error: {e}", exc_info=True)
