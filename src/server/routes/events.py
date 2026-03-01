"""Routes for event queries and management."""
from fastapi import APIRouter

from src.server.state import game_instance
from src.server.serializers import serialize_events_for_client

router = APIRouter()


@router.get("/api/events")
def get_events(
    avatar_id: str = None,
    avatar_id_1: str = None,
    avatar_id_2: str = None,
    cursor: str = None,
    limit: int = 100,
):
    """
    分页获取事件列表。

    Query Parameters:
        avatar_id: 按单个角色筛选。
        avatar_id_1: Pair 查询：角色 1。
        avatar_id_2: Pair 查询：角色 2（需同时提供 avatar_id_1）。
        cursor: 分页 cursor，获取该位置之前的事件。
        limit: 每页数量，默认 100。
    """
    world = game_instance.get("world")
    if world is None:
        return {"events": [], "next_cursor": None, "has_more": False}

    event_manager = getattr(world, "event_manager", None)
    if event_manager is None:
        return {"events": [], "next_cursor": None, "has_more": False}

    # 构建 pair 参数
    avatar_id_pair = None
    if avatar_id_1 and avatar_id_2:
        avatar_id_pair = (avatar_id_1, avatar_id_2)

    # 调用分页查询
    events, next_cursor, has_more = event_manager.get_events_paginated(
        avatar_id=avatar_id,
        avatar_id_pair=avatar_id_pair,
        cursor=cursor,
        limit=limit,
    )

    return {
        "events": serialize_events_for_client(events),
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.delete("/api/events/cleanup")
def cleanup_events(
    keep_major: bool = True,
    before_month_stamp: int = None,
):
    """
    清理历史事件（用户触发）。

    Query Parameters:
        keep_major: 是否保留大事，默认 true。
        before_month_stamp: 删除此时间之前的事件。
    """
    world = game_instance.get("world")
    if world is None:
        return {"deleted": 0, "error": "No world"}

    event_manager = getattr(world, "event_manager", None)
    if event_manager is None:
        return {"deleted": 0, "error": "No event manager"}

    deleted = event_manager.cleanup(
        keep_major=keep_major,
        before_month_stamp=before_month_stamp,
    )
    return {"deleted": deleted}
