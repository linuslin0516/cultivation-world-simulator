"""Routes for game state, map, and meta queries."""
from fastapi import APIRouter

from src.server.state import game_instance, AVATAR_ASSETS
from src.server.serializers import serialize_events_for_client, serialize_phenomenon
from src.server.utils import resolve_avatar_pic_id, resolve_avatar_action_emoji
from src.utils.config import CONFIG
from src.utils.cache import TTLCache

router = APIRouter()

_state_cache = TTLCache(ttl_seconds=1.0)


@router.get("/api/meta/avatars")
def get_avatar_meta():
    return AVATAR_ASSETS


@router.get("/api/state")
def get_state():
    """获取当前世界的一个快照（调试模式）"""
    return _state_cache.get_or_compute(_compute_state)


def _compute_state():
    try:
        # 1. 基础检查
        world = game_instance.get("world")
        if world is None:
             return {"step": 1, "error": "No world"}

        # 2. 时间检查
        y = 0
        m = 0
        try:
            y = int(world.month_stamp.get_year())
            m = int(world.month_stamp.get_month().value)
        except Exception as e:
            return {"step": 2, "error": str(e)}

        # 3. 角色列表检查
        av_list = []
        try:
            raw_avatars = list(world.avatar_manager.avatars.values())[:50]
            for a in raw_avatars:
                aid = str(getattr(a, "id", "no_id"))
                aname = str(getattr(a, "name", "no_name"))
                ax = int(getattr(a, "pos_x", 0))
                ay = int(getattr(a, "pos_y", 0))
                aaction = "unknown"

                curr = getattr(a, "current_action", None)
                if curr:
                     act = getattr(curr, "action", None)
                     if act:
                         aaction = getattr(act, "name", "unnamed_action")
                     else:
                         aaction = str(curr)

                av_list.append({
                    "id": aid,
                    "name": aname,
                    "x": ax,
                    "y": ay,
                    "action": str(aaction),
                    "action_emoji": resolve_avatar_action_emoji(a),
                    "gender": str(a.gender.value),
                    "pic_id": resolve_avatar_pic_id(a)
                })
        except Exception as e:
            return {"step": 3, "error": str(e)}

        recent_events = []
        try:
            event_manager = getattr(world, "event_manager", None)
            if event_manager:
                recent_events = serialize_events_for_client(event_manager.get_recent_events(limit=50))
        except Exception:
            recent_events = []

        return {
            "status": "ok",
            "year": y,
            "month": m,
            "avatar_count": len(world.avatar_manager.avatars),
            "avatars": av_list,
            "events": recent_events,
            "phenomenon": serialize_phenomenon(world.current_phenomenon),
            "is_paused": game_instance.get("is_paused", False)
        }

    except Exception as e:
        return {"step": 0, "error": "Fatal: " + str(e)}


@router.get("/api/map")
def get_map():
    """获取静态地图数据（仅需加载一次）"""
    world = game_instance.get("world")
    if not world or not world.map:
        return {"error": "No map"}

    # 构造二维数组
    w, h = world.map.width, world.map.height
    map_data = []
    for y in range(h):
        row = []
        for x in range(w):
            tile = world.map.get_tile(x, y)
            row.append(tile.type.name)
        map_data.append(row)

    # 构造区域列表
    regions_data = []
    if world.map and hasattr(world.map, 'regions'):
        for r in world.map.regions.values():
            # 确保有中心点
            if hasattr(r, 'center_loc') and r.center_loc:
                rtype = "unknown"
                if hasattr(r, 'get_region_type'):
                    rtype = r.get_region_type()

            region_dict = {
                "id": r.id,
                "name": r.name,
                "type": rtype,
                "x": r.center_loc[0],
                "y": r.center_loc[1]
            }
            # 如果是宗门区域，传递 sect_id 用于前端加载图片资源
            if hasattr(r, 'sect_id'):
                region_dict["sect_id"] = r.sect_id

            # 如果是修炼区域（洞府/遗迹），传递 sub_type
            if hasattr(r, 'sub_type'):
                region_dict["sub_type"] = r.sub_type

            regions_data.append(region_dict)

    return {
        "width": w,
        "height": h,
        "data": map_data,
        "regions": regions_data,
        "config": CONFIG.get("frontend", {})
    }
