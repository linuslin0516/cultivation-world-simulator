"""Global mutable game state shared across server modules."""

# 全局游戏实例
game_instance = {
    "world": None,
    "sim": None,
    "is_paused": True,  # 默认启动为暂停状态，等待前端连接唤醒
    # 初始化状态字段
    "init_status": "idle",  # idle | pending | in_progress | ready | error
    "init_phase": 0,         # 当前阶段 (0-5)
    "init_phase_name": "",   # 当前阶段名称
    "init_progress": 0,      # 总体进度 (0-100)
    "init_error": None,      # 错误信息
    "init_start_time": None, # 初始化开始时间戳
}

# Cache for avatar IDs
AVATAR_ASSETS = {
    "males": [],
    "females": []
}
