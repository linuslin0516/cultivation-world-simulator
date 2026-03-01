"""
配置管理模块
使用OmegaConf读取config.yml和local_config.yml
"""
import os
from pathlib import Path
from omegaconf import OmegaConf


# Required config keys and their expected types (for validation)
_REQUIRED_KEYS = {
    "ai.max_concurrent_requests": int,
    "paths.saves": str,
    "game.init_npc_num": int,
    "meta.version": str,
}

# Keys that are allowed to be empty (user configures via UI)
_OPTIONAL_EMPTY_KEYS = {"llm.key", "llm.base_url", "llm.model_name"}


def validate_config(config) -> list[str]:
    """
    Validate that required config keys exist and have appropriate types.
    Returns a list of warning messages (empty = all good).
    """
    warnings = []
    for dotted_key in _REQUIRED_KEYS:
        parts = dotted_key.split(".")
        obj = config
        try:
            for p in parts:
                obj = getattr(obj, p)
        except Exception:
            warnings.append(f"Missing required config key: {dotted_key}")
            continue
        if obj is None or (isinstance(obj, str) and not obj.strip()):
            if dotted_key not in _OPTIONAL_EMPTY_KEYS:
                warnings.append(f"Config key '{dotted_key}' is empty")
    return warnings


def load_config():
    """
    加载配置文件

    Returns:
        DictConfig: 合并后的配置对象
    """
    static_path = Path("static")

    # 配置文件路径
    base_config_path = static_path / "config.yml"
    local_config_path = static_path / "local_config.yml"

    # 读取基础配置
    base_config = OmegaConf.create({})
    if base_config_path.exists():
        try:
            base_config = OmegaConf.load(base_config_path)
        except Exception as e:
            raise SystemExit(f"[Config] Fatal: Cannot parse {base_config_path}: {e}")

    # 读取本地配置
    local_config = OmegaConf.create({})
    if local_config_path.exists():
        try:
            local_config = OmegaConf.load(local_config_path)
        except Exception as e:
            print(f"[Config] WARNING: Failed to parse {local_config_path}: {e}")
            # Continue with base config only -- local override failure is non-fatal

    # 合并配置，local_config优先级更高
    config = OmegaConf.merge(base_config, local_config)

    # 把paths下的所有值pathlib化
    if hasattr(config, "paths"):
        for key, value in config.paths.items():
            config.paths[key] = Path(value)

    # Environment variable overrides for sensitive values
    env_key = os.environ.get("LLM_API_KEY")
    env_base_url = os.environ.get("LLM_BASE_URL")
    if env_key:
        if not hasattr(config, "llm"):
            config.llm = OmegaConf.create({})
        config.llm.key = env_key
    if env_base_url:
        if not hasattr(config, "llm"):
            config.llm = OmegaConf.create({})
        config.llm.base_url = env_base_url

    return config

# 导出配置对象
CONFIG = load_config()

# Validate on startup
_config_warnings = validate_config(CONFIG)
if _config_warnings:
    for w in _config_warnings:
        print(f"[Config] WARNING: {w}")

def update_paths_for_language(lang_code: str = None):
    """根据语言更新 game_configs 和 templates 的路径"""
    from src.classes.language import language_manager

    if lang_code is None:
        # 尝试从配置中同步语言状态到 language_manager (针对 CLI/Test 等非 server 环境)
        if hasattr(CONFIG, "system") and hasattr(CONFIG.system, "language"):
            saved_lang = CONFIG.system.language

            # Avoid triggering set_language -> df import loop during initialization
            try:
                from src.classes.language import LanguageType
                language_manager._current = LanguageType(saved_lang)
            except (ValueError, ImportError):
                pass

            # Reload translations only (safe)
            from src.i18n import reload_translations
            reload_translations()

            lang_code = saved_lang

    if lang_code is None:
        lang_code = "zh-CN"

    # Normalize lang_code (e.g. zh_CN -> zh-CN) to match folder structure in static/locales
    lang_code = lang_code.replace("_", "-")

    # 默认 locales 目录
    locales_dir = CONFIG.paths.get("locales", Path("static/locales"))

    # 构建特定语言的目录
    target_dir = locales_dir / lang_code

    # 更新配置路径
    # 语言无关的配置目录
    CONFIG.paths.shared_game_configs = Path("static/game_configs")
    # 语言相关的配置目录
    CONFIG.paths.localized_game_configs = target_dir / "game_configs"

    # CONFIG.paths.game_configs 指向统一的数据源，不再区分语言目录
    CONFIG.paths.game_configs = Path("static/game_configs")
    CONFIG.paths.templates = target_dir / "templates"

    # 简单的存在性检查日志
    if not CONFIG.paths.game_configs.exists():
        print(f"[Config] Warning: Game configs dir not found at {CONFIG.paths.game_configs}")
    else:
        print(f"[Config] Switched language context to {lang_code} (Configs using Single Source)")

# 模块加载时自动初始化默认路径，确保 CONFIG.paths.game_configs 存在，避免 import 时 KeyError
update_paths_for_language()
