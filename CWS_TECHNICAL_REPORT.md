# CWS Technical Report — Cultivation World Simulator (修仙世界模擬器)

**Version:** 1.5.1
**License:** CC-BY-NC-SA-4.0
**Repository:** https://github.com/AI-Cultivation/cultivation-world-simulator

> AI 驅動的中國修仙世界模擬器，玩家扮演「道」（天道），觀察並可選擇性地介入開放世界模擬。每個 NPC 均由 LLM 獨立驅動，產生無預設劇情的湧現式故事線。

---

## 技術棧總覽

### Backend (Python)

| 技術 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.10+ (開發用 3.14) | 主要執行環境 |
| **FastAPI** | ≥0.100.0 | Web 框架 / REST API |
| **Uvicorn** | ≥0.20.0 | ASGI Server |
| **WebSockets** | ≥11.0 | 即時通訊 |
| **OmegaConf** | ≥2.3.0 | 分層配置管理 |
| **PyYAML** | ≥6.0 | YAML 解析 |
| **json5** | ≥0.9.0 | 寬鬆 JSON 解析 |
| **SQLite** | 內建 | 事件資料庫 |
| **urllib** | 內建 | LLM API 呼叫 (OpenAI 相容) |

### Frontend (Vue 3)

| 技術 | 版本 | 用途 |
|------|------|------|
| **Vue 3** | 3.x | 前端框架 (Composition API) |
| **Vite** | 5.4.21 | 建構工具 |
| **TypeScript** | 5.9.3 | 型別安全 (strict mode) |
| **Pinia** | 3.0.4 | 狀態管理 |
| **PixiJS** | 8.14.2 | WebGL 遊戲畫布渲染 |
| **vue3-pixi** | 1.0.0-beta.3 | PixiJS Vue 綁定 |
| **Naive UI** | 2.43.2 | UI 元件庫 |
| **vue-i18n** | 9.14.5 | 國際化 (zh-CN / zh-TW / en-US) |
| **@vueuse/core** | 14.0.0 | Vue 組合式工具集 |
| **SASS** | 1.94.1 | CSS 預處理 |
| **pixi-viewport** | 6.0.3 | 遊戲視窗縮放/平移 |

### 測試

| 技術 | 用途 |
|------|------|
| **pytest** ≥8.0.0 | Python 測試框架 |
| **pytest-asyncio** ≥0.23.0 | 非同步測試支援 |
| **pytest-cov** ≥4.1.0 | 覆蓋率報告 |
| **httpx** ≥0.27.0 | HTTP 測試客戶端 |
| **vitest** 2.1.8 | 前端測試框架 |
| **@vue/test-utils** 2.4.6 | Vue 元件測試 |
| **@testing-library/vue** 8.1.0 | Vue DOM 測試 |

### 部署

| 技術 | 用途 |
|------|------|
| **Docker** (multi-stage) | 容器化部署 |
| **Docker Compose** 3.8 | 服務編排 |
| **Nginx** (alpine) | 前端靜態資源服務 |
| **PyInstaller** | 單執行檔打包 |
| **GitHub Actions** | CI/CD 自動化測試 |

---

## 後端架構 (Post-Refactor)

### 模組結構

```
src/server/
├── main.py          (~204 行) App 入口 + CORS + 路由掛載 + 靜態檔案
├── state.py         全域 game_instance dict + AVATAR_ASSETS
├── schemas.py       12 個 Pydantic 請求模型
├── serializers.py   事件/天象序列化
├── utils.py         工具函式 (scan_avatar_assets, resolve_avatar_pic_id...)
├── websocket.py     ConnectionManager + 速率限制 + ws_router
├── game_loop.py     init_game_async + game_loop + INIT_PHASE_NAMES
└── routes/
    ├── game_state.py    GET /api/state (TTL 快取), /api/map, /api/meta/avatars
    ├── events.py        GET /api/events, DELETE /api/events/cleanup
    ├── game_control.py  POST /api/control/{reset,pause,resume,shutdown,reinit}
    ├── avatar.py        角色 CRUD、目標設定
    ├── config.py        LLM 設定、語言切換、/api/game/start
    └── saves.py         存檔/讀檔/列表/刪除
```

### 全域狀態管理 (`state.py`)

```python
game_instance = {
    "world": None,          # World 物件
    "sim": None,            # Simulator 物件
    "is_paused": True,      # 暫停狀態
    "init_status": "idle",  # idle|pending|in_progress|ready|error
    "init_phase": 0,        # 0-6 階段
    "init_progress": 0,     # 0-100%
    "init_error": None,     # 錯誤訊息
    "llm_check_failed": False,
    "llm_error_message": "",
    "current_save_path": None,
}
```

### 初始化 7 階段 (`game_loop.py`)

| 階段 | 名稱 | 進度 |
|------|------|------|
| 0 | scanning_assets | 10% |
| 1 | loading_map | 20% |
| 2 | processing_history | 30% |
| 3 | initializing_sects | 40% |
| 4 | generating_avatars | 55% |
| 5 | checking_llm | 70% |
| 6 | generating_initial_events | 100% |

### WebSocket (`websocket.py`)

- **ConnectionManager**：管理所有 WebSocket 連線
- **速率限制**：每客戶端 10 訊息/秒（滑動視窗）
- **訊息大小限制**：1 KB
- **自動暫停**：最後一個客戶端斷線時暫停遊戲
- **廣播機制**：每 tick 推送角色狀態、事件、天象

---

## LLM 整合架構

### 呼叫鏈

```
AI.decide()
  └─ LLMAI._decide()
       └─ call_llm_with_task_name()
            └─ call_llm_with_template()
                 └─ call_llm() / call_llm_json()
                      └─ urllib (OpenAI-compatible API)
```

### LLM 任務模式

| 任務 | 預設模式 |
|------|---------|
| action_decision | normal |
| long_term_objective | normal |
| nickname | normal |
| relation_resolver | fast |
| story_teller | fast |
| interaction_feedback | fast |
| history_influence | normal |

### 容錯機制

- **Circuit Breaker** (`circuit_breaker.py`)：CLOSED → OPEN → HALF_OPEN 狀態機
  - 失敗門檻：5 次
  - 重置超時：60 秒
- **並行控制**：Semaphore 限制最大 10 個同時 LLM 請求
- **重試機制**：JSON 解析最多重試 3 次
- **超時設定**：每次 LLM 呼叫 120 秒

---

## 遊戲模擬層

### 模擬器步驟 (`simulator.py` - `step()`)

1. **感知更新** `_phase_update_perception_and_knowledge()` — 角色感知範圍、自動佔領區域
2. **行動決策** `_phase_decide_actions()` — LLM 驅動行動規劃
3. **行動提交** `_phase_submit_actions()` — 執行行動（含 try-except 容錯）
4. **互動解析** `_phase_resolve_interactions()` — 多角色互動（戰鬥、交易）
5. **死亡處理** `_phase_handle_deaths()` — 角色死亡
6. **事件生成** — 廣播事件

### 實體類別體系

```
src/classes/
├── core/           World, Avatar, Sect
├── action/         30+ 個行動實作 (移動/戰鬥/修煉/社交/物品)
├── environment/    Map, Tile, Region (城市/修煉地/荒野)
├── items/          Elixir, Weapon, Auxiliary
├── relation/       關係追蹤
├── effect/         狀態效果
├── gathering/      集會系統
├── ai.py           AI 抽象基類 + LLMAI 實作
├── age.py          年齡系統
├── alignment.py    陣營 (正道/魔道/中立)
├── celestial_phenomenon.py  天象
├── cultivation.py  修煉境界
└── ...
```

### 遊戲系統

| 系統 | 檔案 | 功能 |
|------|------|------|
| 時間 | `systems/time.py` | 月份/年份/時間戳 |
| 修煉 | `systems/cultivation.py` | 境界晉升 |
| 戰鬥 | `systems/battle.py` | 傷害計算 |
| 氣運 | `systems/fortune.py` | 幸運/災厄事件 |
| 天劫 | `systems/tribulation.py` | 渡劫機制 |

---

## 前端架構

### Pinia Store 結構

| Store | 職責 |
|-------|------|
| **useWorldStore** | 角色列表、事件、地圖數據、天象 |
| **useSocketStore** | WebSocket 連線狀態、tick 處理 |
| **useSystemStore** | 遊戲初始化狀態、LLM 狀態、暫停控制 |
| **useUiStore** | 選中目標、詳情面板 |
| **useSettingStore** | 語言偏好 |

### 遊戲畫布 (`GameCanvas.vue`)

- **PixiJS WebGL** 渲染引擎
- 三層渲染：
  1. **MapLayer** — 地形格子（背景）
  2. **EntityLayer** — 角色精靈動畫
  3. **CloudLayer** — 視覺特效
- **Viewport** 支援縮放、平移
- **AnimatedAvatar** — 精靈動畫 + 移動插值 + 行動 emoji

### API 客戶端模組

```
web/src/api/
├── http.ts          Fetch 封裝
├── socket.ts        GameSocket (自動重連)
└── modules/
    ├── avatar.ts    角色 API
    ├── event.ts     事件 API
    ├── llm.ts       LLM 設定 API
    ├── system.ts    控制 API
    └── world.ts     狀態 API
```

---

## 配置管理

### 分層配置合併

```
static/config.yml (基礎設定)
  + static/local_config.yml (使用者覆蓋, gitignored)
  + 環境變數覆蓋 (最高優先)
```

### 支援的環境變數

| 變數 | 用途 |
|------|------|
| `LLM_API_KEY` | LLM API 金鑰 |
| `LLM_BASE_URL` | LLM API 端點 |
| `SERVER_HOST` | 伺服器綁定地址 |
| `SERVER_PORT` | 伺服器埠號 |
| `CORS_ORIGINS` | 允許的 CORS 來源 |

### 配置驗證 (`validate_config()`)

啟動時檢查必要欄位：`ai.max_concurrent_requests`, `paths.saves`, `game.init_npc_num`, `meta.version`

---

## 國際化 (i18n)

| 層級 | 實作 |
|------|------|
| **前端 UI** | vue-i18n (JSON 翻譯檔) |
| **後端訊息** | `src/i18n/` + `language_manager` |
| **LLM 提示詞** | `static/locales/{lang}/templates/` |
| **遊戲配置** | `static/locales/{lang}/game_configs/` |

支援語言：**zh-CN** (簡體中文) / **zh-TW** (繁體中文) / **en-US** (英文)

---

## 存檔系統

- **格式**：JSON (世界狀態 + 角色 + 事件) + SQLite (事件資料庫)
- **路徑**：`assets/saves/{save_name}.json`
- **語言記錄**：存檔包含 `meta.language`，讀檔時自動切換語言
- **API**：`/api/saves` (列表), `/api/game/{save,load,delete}`

---

## 測試基礎設施

- **880 個測試**，全部通過
- **13 個新增測試**（circuit breaker 7 + config validation 6）
- **conftest.py** 提供：mock_saves_dir, fixed_random_seed, base_world, dummy_avatar
- **CI/CD**：GitHub Actions 自動在 push/PR 時執行，要求 60% 最低覆蓋率

---

## 部署架構

```
┌─────────────────┐     ┌──────────────────┐
│   Nginx (80)    │────▶│  Vue 3 靜態資源    │
│   Frontend      │     │  (PixiJS WebGL)   │
└────────┬────────┘     └──────────────────┘
         │ /api, /ws proxy
┌────────▼────────┐     ┌──────────────────┐
│  Uvicorn (8002) │────▶│  FastAPI Backend  │
│  ASGI Server    │     │  + WebSocket      │
└────────┬────────┘     └──────────────────┘
         │
┌────────▼────────┐     ┌──────────────────┐
│  LLM API        │────▶│  OpenAI 相容服務   │
│  (Circuit Break) │     │  (任意供應商)      │
└─────────────────┘     └──────────────────┘
```

---

## 效能特性

| 指標 | 數值 |
|------|------|
| 遊戲迴圈頻率 | ~1 Hz (每秒 1 步) |
| 每 tick 角色廣播上限 | 50 個 |
| LLM 並行請求上限 | 10 個 |
| API 狀態快取 TTL | 1 秒 |
| WebSocket 速率限制 | 10 訊息/秒/客戶端 |
| WebSocket 訊息大小限制 | 1 KB |
| LLM 單次請求超時 | 120 秒 |

---

## 完整目錄結構

```
cultivation-world-simulator/
├── src/
│   ├── classes/              # 遊戲實體類別
│   │   ├── core/            # Avatar, Sect, World
│   │   ├── action/          # 30+ 行動實作
│   │   ├── environment/     # Map, Tile, Region
│   │   ├── items/           # Elixir, Weapon, Auxiliary
│   │   ├── relation/        # 關係系統
│   │   ├── effect/          # 狀態效果
│   │   ├── gathering/       # 集會系統
│   │   └── ...              # 其他實體類別
│   ├── sim/                 # 模擬核心
│   │   ├── simulator.py     # 主模擬迴圈
│   │   ├── managers/        # Avatar, Event, Mortal 管理器
│   │   ├── save/            # 存檔序列化
│   │   └── load/            # 讀檔反序列化
│   ├── systems/             # 遊戲系統
│   │   ├── time.py          # 時間/日曆
│   │   ├── cultivation.py   # 境界晉升
│   │   ├── battle.py        # 戰鬥
│   │   ├── fortune.py       # 氣運事件
│   │   └── tribulation.py   # 天劫
│   ├── server/              # FastAPI 後端
│   │   ├── main.py          # App 入口
│   │   ├── state.py         # 全域狀態
│   │   ├── websocket.py     # WS 管理
│   │   ├── game_loop.py     # 遊戲迴圈
│   │   ├── schemas.py       # Pydantic 模型
│   │   ├── serializers.py   # JSON 序列化
│   │   ├── utils.py         # 工具函式
│   │   └── routes/          # 6 個路由模組
│   ├── utils/               # 工具
│   │   ├── config.py        # 配置管理
│   │   ├── cache.py         # TTL 快取
│   │   ├── exceptions.py    # 例外類別
│   │   └── llm/             # LLM 整合
│   │       ├── client.py    # LLM 呼叫
│   │       ├── circuit_breaker.py  # 斷路器
│   │       ├── config.py    # LLM 配置
│   │       ├── parser.py    # JSON 解析
│   │       └── prompt.py    # 提示詞建構
│   ├── i18n/                # 國際化
│   └── run/                 # 執行時工具
│       ├── data_loader.py   # 靜態資料載入
│       ├── load_map.py      # 地圖載入
│       └── log.py           # 日誌
├── web/                     # 前端 (Vue 3)
│   ├── src/
│   │   ├── api/             # API 客戶端
│   │   ├── components/      # Vue 元件
│   │   ├── stores/          # Pinia stores
│   │   ├── composables/     # Vue composables
│   │   ├── types/           # TypeScript 型別
│   │   ├── locales/         # i18n JSON
│   │   ├── App.vue          # 根元件
│   │   └── main.ts          # 入口
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── package.json
├── static/                  # 配置 & 國際化
│   ├── config.yml
│   ├── local_config.yml     # 使用者配置 (gitignored)
│   └── locales/
│       ├── zh-CN/
│       ├── zh-TW/
│       └── en-US/
├── tests/                   # Pytest 測試套件
├── deploy/                  # Docker & 部署
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── assets/                  # 遊戲資源
│   └── saves/              # 存檔
├── .github/workflows/      # CI/CD
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 關鍵設計模式

1. **Circuit Breaker** — LLM 服務容錯（CLOSED → OPEN → HALF_OPEN）
2. **TTL Cache** — 避免重複計算 API 回應
3. **Semaphore 並行控制** — 公平分配 LLM 資源
4. **asyncio.to_thread()** — 在非同步上下文中執行同步工作
5. **OmegaConf 分層合併** — 類型安全的配置管理
6. **Pydantic Schema 驗證** — API 請求驗證
7. **WebSocket 廣播** — 即時前端更新
8. **mock.patch 目標定位** — 測試中必須 patch 名稱被查找的位置
9. **湧現式模擬** — 無預設劇情，NPC 獨立 LLM 驅動
10. **語言感知路徑** — 配置/模板依語言動態切換
