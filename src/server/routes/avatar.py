"""Routes for avatar CRUD, detail info, objectives, and game metadata."""
from fastapi import APIRouter, HTTPException, Query

from src.server.state import game_instance, AVATAR_ASSETS
from src.server.utils import resolve_avatar_pic_id
from src.server.schemas import (
    SetObjectiveRequest, ClearObjectiveRequest,
    CreateAvatarRequest, DeleteAvatarRequest,
)
from src.utils.config import CONFIG
from src.utils.cache import TTLCache
from src.classes.core.sect import sects_by_id
from src.classes.technique import techniques_by_id
from src.classes.items.weapon import weapons_by_id
from src.classes.items.auxiliary import auxiliaries_by_id
from src.classes.appearance import get_appearance_by_level
from src.classes.persona import personas_by_id
from src.systems.cultivation import REALM_ORDER
from src.classes.alignment import Alignment
from src.classes.long_term_objective import set_user_long_term_objective, clear_user_long_term_objective
from src.sim.avatar_init import create_avatar_from_request
from src.classes.language import language_manager, LanguageType

router = APIRouter()

_game_data_cache = TTLCache(ttl_seconds=60.0)


@router.get("/api/detail")
def get_detail_info(
    target_type: str = Query(alias="type"),
    target_id: str = Query(alias="id")
):
    """获取结构化详情信息，替代/增强 hover info"""
    world = game_instance.get("world")

    if world is None:
        raise HTTPException(status_code=503, detail="World not initialized")

    target = None
    if target_type == "avatar":
        target = world.avatar_manager.get_avatar(target_id)
    elif target_type == "region":
        if world.map and hasattr(world.map, "regions"):
            regions = world.map.regions
            target = regions.get(target_id)
            if target is None:
                try:
                    target = regions.get(int(target_id))
                except (ValueError, TypeError):
                    target = None
    elif target_type == "sect":
        try:
            sid = int(target_id)
            target = sects_by_id.get(sid)
        except (ValueError, TypeError):
            target = None

    if target is None:
         raise HTTPException(status_code=404, detail="Target not found")

    info = target.get_structured_info()
    return info


@router.post("/api/action/set_long_term_objective")
def set_long_term_objective(req: SetObjectiveRequest):
    world = game_instance.get("world")
    if not world:
        raise HTTPException(status_code=503, detail="World not initialized")

    avatar = world.avatar_manager.avatars.get(req.avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    set_user_long_term_objective(avatar, req.content)
    return {"status": "ok", "message": "Objective set"}


@router.post("/api/action/clear_long_term_objective")
def clear_long_term_objective(req: ClearObjectiveRequest):
    world = game_instance.get("world")
    if not world:
        raise HTTPException(status_code=503, detail="World not initialized")

    avatar = world.avatar_manager.avatars.get(req.avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    cleared = clear_user_long_term_objective(avatar)
    return {
        "status": "ok",
        "message": "Objective cleared" if cleared else "No user objective to clear"
    }


@router.get("/api/meta/game_data")
def get_game_data():
    """获取游戏元数据（宗门、个性、境界等），供前端选择"""
    return _game_data_cache.get_or_compute(_compute_game_data)


def _compute_game_data():
    # 1. 宗门列表
    sects_list = []
    for s in sects_by_id.values():
        sects_list.append({
            "id": s.id,
            "name": s.name,
            "alignment": s.alignment.value
        })

    # 2. 个性列表
    personas_list = []
    for p in personas_by_id.values():
        personas_list.append({
            "id": p.id,
            "name": p.name,
            "desc": p.desc,
            "rarity": p.rarity.level.name if hasattr(p.rarity, 'level') else "N"
        })

    # 3. 境界列表
    realms_list = [r.value for r in REALM_ORDER]

    # 4. 功法 / 兵器 / 辅助装备
    techniques_list = [
        {
            "id": t.id,
            "name": t.name,
            "grade": t.grade.value,
            "attribute": t.attribute.value,
            "sect_id": t.sect_id
        }
        for t in techniques_by_id.values()
    ]

    weapons_list = [
        {
            "id": w.id,
            "name": w.name,
            "type": w.weapon_type.value,
            "grade": w.realm.value,
        }
        for w in weapons_by_id.values()
    ]

    auxiliaries_list = [
        {
            "id": a.id,
            "name": a.name,
            "grade": a.realm.value,
        }
        for a in auxiliaries_by_id.values()
    ]

    alignments_list = [
        {
            "value": align.value,
            "label": str(align)
        }
        for align in Alignment
    ]

    return {
        "sects": sects_list,
        "personas": personas_list,
        "realms": realms_list,
        "techniques": techniques_list,
        "weapons": weapons_list,
        "auxiliaries": auxiliaries_list,
        "alignments": alignments_list
    }


@router.get("/api/meta/avatar_list")
def get_avatar_list_simple():
    """获取简略的角色列表，用于管理界面"""
    world = game_instance.get("world")
    if not world:
        return {"avatars": []}

    result = []
    for a in world.avatar_manager.avatars.values():
        sect_name = a.sect.name if a.sect else "散修"
        realm_str = a.cultivation_progress.realm.value if hasattr(a, 'cultivation_progress') else "未知"

        result.append({
            "id": str(a.id),
            "name": a.name,
            "sect_name": sect_name,
            "realm": realm_str,
            "gender": str(a.gender),
            "age": a.age.age
        })

    # 按名字排序
    result.sort(key=lambda x: x["name"])
    return {"avatars": result}


@router.post("/api/action/create_avatar")
def create_avatar(req: CreateAvatarRequest):
    """创建新角色"""
    world = game_instance.get("world")
    if not world:
        raise HTTPException(status_code=503, detail="World not initialized")

    try:
        # 准备参数
        sect = None
        if req.sect_id is not None:
            sect = sects_by_id.get(req.sect_id)

        personas = None
        if req.persona_ids:
            personas = req.persona_ids

        have_name = False
        final_name = None
        surname = (req.surname or "").strip()
        given_name = (req.given_name or "").strip()
        if surname or given_name:
            if surname and given_name:
                if language_manager.current == LanguageType.EN_US:
                    final_name = f"{surname} {given_name}"
                else:
                    final_name = f"{surname}{given_name}"
                have_name = True
            elif surname:
                final_name = f"{surname}某"
                have_name = True
            else:
                final_name = given_name
                have_name = True
        if not have_name:
            final_name = None

        avatar = create_avatar_from_request(
            world,
            world.month_stamp,
            name=final_name,
            gender=req.gender,
            age=req.age,
            level=req.level,
            sect=sect,
            personas=personas,
            technique=req.technique_id,
            weapon=req.weapon_id,
            auxiliary=req.auxiliary_id,
            appearance=req.appearance,
            relations=req.relations
        )

        if req.pic_id is not None:
            gender_key = "females" if getattr(avatar.gender, "value", "male") == "female" else "males"
            available_ids = set(AVATAR_ASSETS.get(gender_key, []))
            if available_ids and req.pic_id not in available_ids:
                raise HTTPException(status_code=400, detail="Invalid pic_id for selected gender")
            avatar.custom_pic_id = req.pic_id

        if req.alignment:
            avatar.alignment = Alignment.from_str(req.alignment)

        if req.appearance is not None:
            avatar.appearance = get_appearance_by_level(req.appearance)

        if req.alignment:
            avatar.alignment = Alignment.from_str(req.alignment)

        # 注册到管理器
        world.avatar_manager.register_avatar(avatar, is_newly_born=True)

        return {
            "status": "ok",
            "message": f"Created avatar {avatar.name}",
            "avatar_id": str(avatar.id)
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/action/delete_avatar")
def delete_avatar(req: DeleteAvatarRequest):
    """删除角色"""
    world = game_instance.get("world")
    if not world:
        raise HTTPException(status_code=503, detail="World not initialized")

    if req.avatar_id not in world.avatar_manager.avatars:
        raise HTTPException(status_code=404, detail="Avatar not found")

    try:
        world.avatar_manager.remove_avatar(req.avatar_id)
        return {"status": "ok", "message": "Avatar deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
