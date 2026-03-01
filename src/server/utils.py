"""Server utility functions (avatar assets, LLM connectivity, etc.)."""
import os
import sys
import re
import logging
import subprocess

from src.server.state import AVATAR_ASSETS


# 简易的命令行参数检查 (不使用 argparse 以避免冲突和时序问题)
IS_DEV_MODE = "--dev" in sys.argv


class EndpointFilter(logging.Filter):
    """
    Log filter to hide successful /api/init-status requests (polling)
    to reduce console noise.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("GET /api/init-status") == -1


def scan_avatar_assets(assets_path: str):
    """Scan assets directory for avatar images."""
    def get_ids(subdir):
        directory = os.path.join(assets_path, subdir)
        if not os.path.exists(directory):
            return []
        ids = []
        for f in os.listdir(directory):
            if f.lower().endswith('.png'):
                try:
                    name = os.path.splitext(f)[0]
                    ids.append(int(name))
                except ValueError:
                    pass
        return sorted(ids)

    AVATAR_ASSETS["males"] = get_ids("males")
    AVATAR_ASSETS["females"] = get_ids("females")
    print(f"Loaded avatar assets: {len(AVATAR_ASSETS['males'])} males, {len(AVATAR_ASSETS['females'])} females")


def get_avatar_pic_id(avatar_id: str, gender_val: str) -> int:
    """Deterministically get a valid pic_id for an avatar"""
    key = "females" if gender_val == "female" else "males"
    available = AVATAR_ASSETS.get(key, [])

    if not available:
        return 1

    # Use hash to pick an index from available IDs
    idx = abs(hash(str(avatar_id))) % len(available)
    return available[idx]


def resolve_avatar_pic_id(avatar) -> int:
    """Return the actual avatar portrait ID, respecting custom overrides."""
    if avatar is None:
        return 1
    custom_pic_id = getattr(avatar, "custom_pic_id", None)
    if custom_pic_id is not None:
        return custom_pic_id
    gender_val = getattr(getattr(avatar, "gender", None), "value", "male")
    return get_avatar_pic_id(str(getattr(avatar, "id", "")), gender_val or "male")


def resolve_avatar_action_emoji(avatar) -> str:
    """获取角色当前动作的 Emoji"""
    if not avatar:
        return ""
    curr = getattr(avatar, "current_action", None)
    if not curr:
        return ""

    # ActionInstance.action -> Action 实例
    act_instance = getattr(curr, "action", None)
    if not act_instance:
        return ""

    return getattr(act_instance, "EMOJI", "")


def check_llm_connectivity() -> tuple[bool, str]:
    """
    检查 LLM 连通性

    Returns:
        (是否成功, 错误信息)
    """
    try:
        from src.utils.llm.config import LLMMode, LLMConfig
        from src.utils.llm.client import test_connectivity

        normal_config = LLMConfig.from_mode(LLMMode.NORMAL)
        fast_config = LLMConfig.from_mode(LLMMode.FAST)

        # 检查配置是否完整
        if not normal_config.api_key or not normal_config.base_url:
            return False, "LLM 配置不完整：请填写 API Key 和 Base URL"

        if not normal_config.model_name:
            return False, "LLM 配置不完整：请填写智能模型名称"

        # 判断是否需要测试两次
        same_model = (normal_config.model_name == fast_config.model_name and
                     normal_config.base_url == fast_config.base_url and
                     normal_config.api_key == fast_config.api_key)

        if same_model:
            # 只测试一次
            print(f"检测 LLM 连通性（单模型）: {normal_config.model_name}")
            success, error = test_connectivity(LLMMode.NORMAL, normal_config)
            if not success:
                return False, f"连接失败：{error}"
        else:
            # 测试两次
            print(f"检测智能模型连通性: {normal_config.model_name}")
            success, error = test_connectivity(LLMMode.NORMAL, normal_config)
            if not success:
                return False, f"智能模型连接失败：{error}"

            print(f"检测快速模型连通性: {fast_config.model_name}")
            success, error = test_connectivity(LLMMode.FAST, fast_config)
            if not success:
                return False, f"快速模型连接失败：{error}"

        return True, ""

    except Exception as e:
        return False, f"连通性检测异常：{str(e)}"


def validate_save_name(name: str) -> bool:
    """验证存档名称是否合法。"""
    if not name or len(name) > 50:
        return False
    # 只允许中文、字母、数字和下划线。
    pattern = r'^[\w\u4e00-\u9fff]+$'
    return bool(re.match(pattern, name))


def ensure_npm_dependencies(web_dir: str) -> bool:
    """
    确保 npm 依赖是最新的。

    Args:
        web_dir: web 目录路径。

    Returns:
        True 如果安装成功，False 如果失败。
    """
    import platform
    print("📦 正在检查前端依赖...")
    try:
        if platform.system() == "Windows":
            subprocess.run("npm install", cwd=web_dir, shell=True, check=True)
        else:
            subprocess.run(["npm", "install"], cwd=web_dir, shell=False, check=True)
        print("✅ 前端依赖已就绪")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️ npm install 失败: {e}，继续启动...")
        return False
