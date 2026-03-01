"""Serialization functions for converting domain objects to JSON-safe dicts."""
from typing import List, Optional

from src.classes.core.world import World
from src.classes.event import Event


def serialize_active_domains(world: World) -> List[dict]:
    """序列化所有秘境列表（包括开启和未开启的）"""
    domains_data = []
    if not world or not world.gathering_manager:
        return []

    # 找到 HiddenDomain 实例
    hidden_domain_gathering = None
    for gathering in world.gathering_manager.gatherings:
        if gathering.__class__.__name__ == "HiddenDomain":
            hidden_domain_gathering = gathering
            break

    if hidden_domain_gathering:
        # 注意：访问受保护方法 _load_configs
        all_configs = hidden_domain_gathering._load_configs()

        # 获取当前开启的 ID 集合
        active_ids = {d.id for d in hidden_domain_gathering._active_domains}

        for d in all_configs:
            is_open = d.id in active_ids

            domains_data.append({
                "id": d.id,
                "name": d.name,
                "desc": d.desc,
                "max_realm": str(d.max_realm),
                "danger_prob": d.danger_prob,
                "drop_prob": d.drop_prob,
                "is_open": is_open,
                "cd_years": d.cd_years,
                "open_prob": d.open_prob
            })

    return domains_data


def serialize_events_for_client(events: List[Event]) -> List[dict]:
    """将事件转换为前端可用的结构。"""
    serialized: List[dict] = []
    for idx, event in enumerate(events):
        month_stamp = getattr(event, "month_stamp", None)
        stamp_int = None
        year = None
        month = None
        if month_stamp is not None:
            try:
                stamp_int = int(month_stamp)
            except Exception:
                stamp_int = None
            try:
                year = int(month_stamp.get_year())
            except Exception:
                year = None
            try:
                month_obj = month_stamp.get_month()
                month = month_obj.value
            except Exception:
                month = None

        related_raw = getattr(event, "related_avatars", None) or []
        related_ids = [str(a) for a in related_raw if a is not None]

        serialized.append({
            "id": getattr(event, "id", None) or f"{stamp_int or 'evt'}-{idx}",
            "text": str(event),
            "content": getattr(event, "content", ""),
            "year": year,
            "month": month,
            "month_stamp": stamp_int,
            "related_avatar_ids": related_ids,
            "is_major": bool(getattr(event, "is_major", False)),
            "is_story": bool(getattr(event, "is_story", False)),
            "created_at": getattr(event, "created_at", 0.0),
        })
    return serialized


def serialize_phenomenon(phenomenon) -> Optional[dict]:
    """序列化天地灵机对象"""
    if not phenomenon:
        return None

    # 安全地获取 rarity.name
    rarity_str = "N"
    if hasattr(phenomenon, "rarity") and phenomenon.rarity:
        # 检查 rarity 是否是 Enum (RarityLevel)
        if hasattr(phenomenon.rarity, "name"):
            rarity_str = phenomenon.rarity.name
        # 检查 rarity 是否是 Rarity dataclass (包含 level 字段)
        elif hasattr(phenomenon.rarity, "level") and hasattr(phenomenon.rarity.level, "name"):
            rarity_str = phenomenon.rarity.level.name

    # 生成效果描述
    from src.classes.effect import format_effects_to_text
    effect_desc = format_effects_to_text(phenomenon.effects) if hasattr(phenomenon, "effects") else ""

    return {
        "id": phenomenon.id,
        "name": phenomenon.name,
        "desc": phenomenon.desc,
        "rarity": rarity_str,
        "duration_years": phenomenon.duration_years,
        "effect_desc": effect_desc
    }
