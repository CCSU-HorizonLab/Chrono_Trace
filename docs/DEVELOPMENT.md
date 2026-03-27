# Chrono Trace - 开发指南

> 为开发者提供的技术文档和开发规范

---

## 🏗️ 项目架构

### 技术栈

**后端**:
- Python 3.8+
- SQLite (数据存储)
- PyWebView (桌面应用框架)
- pycryptodome (加密/解密)
- pywinauto (UI自动化)

**前端**:
- Vue 3 + TypeScript
- Vite (构建工具)
- ECharts (图表可视化)

**数据流**:
```
前端 (Vue) ←→ Bridge (PyWebView API) ←→ 后端服务 ←→ SQLite
                                      ↓
                              微信数据库解密
```

---

## 📁 目录结构

```
Chrono-Trace/
├── backend/
│   ├── app/
│   │   ├── db/              # 数据库层
│   │   │   ├── connection.py
│   │   │   └── schema.sql
│   │   ├── services/        # 业务逻辑
│   │   │   ├── analysis/    # 历史分析与好感度分析
│   │   │   │   ├── affinity_analysis_service.py    # 主编排器
│   │   │   │   ├── emotional_resonance_service.py  # 情感共振率
│   │   │   │   ├── chat_positivity_service.py      # 聊天积极度
│   │   │   │   ├── attitude_tendency_service.py     # 态度倾向
│   │   │   │   ├── preference_compatibility_service.py  # 喜好兼容度
│   │   │   │   ├── sentiment_service.py            # 情感分析
│   │   │   │   ├── preprocessing_service.py        # 预处理
│   │   │   │   └── preprocessing_orchestrator.py   # 预处理编排器
│   │   │   ├── realtime/    # 实时监听、情绪分析、AI 建议
│   │   │   │   ├── monitor_service.py              # 监听服务
│   │   │   │   ├── providers/
│   │   │   │   │   ├── native_uia.py               # 主监听后端
│   │   │   │   │   ├── factory.py                  # 提供器工厂
│   │   │   │   │   └── detector.py                 # 消息检测
│   │   │   │   ├── floating_window_service.py      # 悬浮窗服务
│   │   │   │   ├── suggestion_engine.py            # 建议引擎
│   │   │   │   ├── llm_engine.py                   # LLM 引擎
│   │   │   │   ├── emotion_state_tracker.py        # 情绪状态追踪
│   │   │   │   └── trigger_resolver.py             # 触发解析器
│   │   │   └── wechat/      # 微信数据处理
│   │   │       ├── db/      # V4数据库解析
│   │   │       │   └── v4/
│   │   │       │       ├── contact.py
│   │   │       │       └── message.py
│   │   │       ├── db_decryptor_v2.py
│   │   │       ├── path_finder.py
│   │   │       └── ingest_service.py
│   │   └── webview/         # 前端桥接
│   │       └── bridge.py
│   └── data/                # 数据文件
│       ├── chrono_trace.db
│       └── settings.json
├── frontend/
│   ├── src/
│   │   ├── api/             # API调用
│   │   │   ├── bridge.ts
│   │   │   └── affinity.ts
│   │   ├── components/      # Vue组件
│   │   │   ├── affinity/    # 关系分析组件
│   │   │   ├── charts/      # 图表组件
│   │   │   └── base/        # 基础组件
│   │   └── views/           # 页面
│   │       ├── Home.vue
│   │       ├── Analytics.vue
│   │       ├── Suggestions.vue
│   │       ├── Settings.vue
│   │       └── FloatingPanel.vue
│   └── package.json
├── docs/                    # 文档
│   ├── SETUP.md
│   └── DEVELOPMENT.md
├── app.py                   # 生产入口
├── app_dev.py              # 开发入口
├── CHANGELOG.md            # 变更日志
└── Readme.md               # 项目说明
```

---

## 🔧 开发环境设置

### 1. 安装依赖

```bash
# Python依赖
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
```

### 2. 启动开发服务器

```bash
# 开发模式 (自动启动前端dev server)
python app_dev.py

# 或分别启动
# 终端1: 前端
cd frontend
npm run dev

# 终端2: 后端
python app.py
```

### 3. 调试工具

**后端调试**:
- 使用 `print()` 输出debug日志
- 日志格式: `[DEBUG ClassName] 消息`
- 查看控制台输出

**前端调试**:
- Chrome DevTools
- Vue DevTools扩展
- 查看 `console.log()` 输出

---

## 📝 核心模块说明

### 1. 微信数据库解密 (`db_decryptor_v2.py`)

**实现原理**:
- SQLCipher 4 标准
- PBKDF2-HMAC-SHA512 密钥派生
- AES-256-CBC 页面解密

**核心类**:
```python
class WeChatDBDecryptorV2:
    PAGE_SIZE = 4096              # 页大小
    V4_ITER_COUNT = 256000        # KDF迭代次数

    def verify_key_from_file(db_path, key_hex) -> bool:
        """验证密钥是否正确"""

    def decrypt_database(input_path, output_path, key_hex):
        """解密整个数据库到临时文件"""
```

### 2. 路径查找 (`path_finder.py`)

**功能**:
- 自动检测微信数据目录
- 扫描数据库文件
- 支持自定义路径

**核心方法**:
```python
class WeChatPathFinder:
    @staticmethod
    def find_all_wechat_dbs() -> Dict:
        """完整流程: 查找所有微信数据库"""
        # 返回格式:
        {
            "wechat_dir": "C:/Users/xxx/xwechat_files",
            "current_user": "wxid_xxx",
            "databases": {
                "contact": "path/to/contact.db",
                "message": ["path/to/message_0.db", ...],
                "session": "path/to/session.db"
            }
        }
```

**路径优先级**:
1. 注册表配置
2. `C:/Users/<user>/xwechat_files` (微信4.0+)
3. 用户文档目录

### 3. 实时监听 (`monitor_service.py` + `native_uia.py`)

**架构**:
- `RealtimeProviderFactory` - 提供器工厂（现在只创建 `native_uia`）
- `RealtimeMonitorService` - 监听服务
- `native_uia.py` - 主监听后端（Windows UI自动化）
- `detector.py` - 消息检测与识别

**关键功能**:
- 启动时建立可见消息基线，避免历史消息误触发
- 监听阶段去重（内容+时间锚点+同屏次序）
- LLM上下文去重（同sender/同内容/同时间）
- 跨会话切换不串上下文
- 断点恢复（上下文滑窗+自适应滚动）

### 4. 好感度分析 (`affinity_analysis_service.py`)

**四个维度**:
- **情感共振率** (30%) - 双向情感响应、极性一致性、强度匹配
- **聊天积极度** (30%) - 日均消息数、回复及时性、话题延续性
- **态度倾向** (20%) - 正负词汇、多媒体使用、隐私分享等
- **喜好兼容度** (20%) - 话题提及、话题延续性（可选维度）

**架构**:
```python
class AffinityAnalysisService:
    def analyze(self, conversation_id: int) -> Dict:
        """主入口点：触发完整分析流程"""
        # 1. 预处理编排
        # 2. 计算四个维度
        # 3. 加权求和总分
        # 4. 保存结果

    def get_scores(self, conversation_id: int) -> Dict:
        """获取已计算的分数"""

    def reanalyze(self, conversation_id: int) -> Dict:
        """重新分析"""
```

---

## 🧪 测试

### 单元测试

```bash
# 运行所有测试
pytest backend/tests/

# 运行特定测试文件
pytest backend/tests/test_sentiment_service.py
pytest backend/tests/test_monitor_service_message_dedupe.py
pytest backend/tests/test_native_uia_scroll.py

# 运行实时监听相关测试
pytest backend/tests/test_monitor_service_message_dedupe.py \
       backend/tests/test_native_uia_scroll.py \
       backend/tests/test_realtime_provider_factory.py \
       backend/tests/test_local_wxauto_shim.py \
       backend/tests/test_soak_realtime_listener.py
```

### 集成测试

1. 启动应用
2. 导入测试数据
3. 验证统计结果

---

## 📐 代码规范

### Python

**命名规范**:
- 类名: `PascalCase`
- 函数/变量: `snake_case`
- 常量: `UPPER_SNAKE_CASE`

**Debug输出**:
```python
print(f"[DEBUG ClassName] 描述: {variable}")
```

**错误处理**:
```python
try:
    # 操作
except Exception as e:
    print(f"[ERROR] 错误描述: {e}")
    # 记录日志或返回错误
```

### TypeScript/Vue

**命名规范**:
- 组件: `PascalCase.vue`
- 函数/变量: `camelCase`
- 常量: `UPPER_SNAKE_CASE`

**API调用**:
```typescript
import { api } from '@/api/bridge'

// 使用async/await
const result = await api.import_wechat_data(key, options)
```

---

## 🔌 API接口

### Bridge API (`bridge.py`)

**导入相关**:
```python
# 获取微信路径
get_wechat_paths() -> Dict[str, Any]

# 验证密钥
verify_wechat_key(db_key: str) -> Dict[str, Any]

# 导入数据
import_wechat_data(
    db_key: str,
    options: Dict[str, Any]
) -> Dict[str, Any]
```

**设置相关**:
```python
# 获取设置
get_settings() -> Dict[str, Any]

# 保存设置
set_settings(payload: Dict[str, Any]) -> Dict[str, Any]
```

**文件选择**:
```python
# 选择文件
select_file(title: str, file_types: str) -> Dict[str, Any]

# 选择目录
select_directory(title: str) -> Dict[str, Any]
```

**分析相关**:
```python
# 分析好感度
analyze_affinity(conversation_id: int, force_reanalyze: bool = False) -> Dict

# 获取好感度分数
get_affinity_scores(conversation_id: int) -> Dict

# 获取好感度配置
get_affinity_config(conversation_id: int) -> Dict
```

**实时监听相关**:
```python
# 开始监听
start_realtime_listener(contact_name: str) -> Dict

# 停止监听
stop_realtime_listener() -> Dict

# 获取监听状态
get_listener_status() -> Dict
```

---

## 🐛 调试技巧

### 查看数据库内容

```bash
# 打开SQLite数据库
sqlite3 backend/data/chrono_trace.db

# 查看表结构
.schema

# 查询数据
SELECT COUNT(*) FROM contacts;
SELECT COUNT(*) FROM messages;
```

### 查看微信数据库结构

```python
import sqlite3

# 解密后连接
conn = sqlite3.connect(temp_db_path)
cursor = conn.cursor()

# 查看所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print(cursor.fetchall())

# 查看表结构
cursor.execute("PRAGMA table_info(Contact)")
print(cursor.fetchall())
```

### 常见问题排查

1. **路径查找失败**
   - 检查 `[DEBUG PathFinder]` 输出
   - 确认 `db_storage` 目录存在

2. **解密失败**
   - 检查密钥格式(64位hex)
   - 确认微信版本4.0+

3. **数据导入为0**
   - 检查数据库路径
   - 查看SQL查询日志

4. **实时监听问题**
   - 检查微信窗口是否可见
   - 确认微信版本是4.0+
   - 查看 `[DEBUG Realtime]` 相关日志

---

## 📦 构建发布

### 打包应用

```bash
# 安装打包工具
pip install pyinstaller

# 构建前端
cd frontend
npm run build
cd ..

# 打包Python后端
pyinstaller --onefile --windowed app.py
```

### 发布检查清单

- [ ] 更新版本号
- [ ] 测试所有功能
- [ ] 更新 CHANGELOG.md
- [ ] 打包应用
- [ ] 创建 Release

---

## 🤝 贡献指南

### Pull Request流程

1. Fork项目
2. 创建特性分支
3. 提交代码
4. 编写测试
5. 更新文档
6. 提交PR

### Commit规范

```
<type>: <description>

[optional body]
```

**Type**:
- `feat`: 新功能
- `fix`: Bug修复
- `docs`: 文档更新
- `refactor`: 重构
- `test`: 测试相关

---

## 📚 参考资源

### 相关项目

- **EchoTrace**: https://github.com/ycccccccy/echotrace
  - 参考解密算法实现

- **wx_key**: https://github.com/ycccccccy/wx_key
  - 获取微信数据库密钥

### 技术文档

- SQLCipher 4: https://www.zetetic.net/sqlcipher/
- PyWebView: https://pywebview.flowrl.com/
- Vue 3: https://vuejs.org/
- Pywinauto: https://pywinauto.github.io/

---

**文档版本**: 2.0.0
**最后更新**: 2026-03-27
