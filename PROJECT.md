# Chrono Trace - 项目总览

> **"镌刻对话年轮，丈量心动间距"**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3.x-green.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Chrono Trace** 是一款桌面级微信聊天记录分析工具，通过情绪分析、数据可视化和 AI 建议，帮助用户更好地理解和管理人际关系。

---

## 目录

- [项目概述](#项目概述)
- [核心特性](#核心特性)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [核心功能](#核心功能)
- [开发指南](#开发指南)
- [相关文档](#相关文档)

---

## 项目概述

Chrono Trace 是一个纯本地运行的桌面应用，专注于微信聊天记录的深度分析。通过量化指标（如响应时间、语言风格匹配、情感分析等）生成洞察报告，并提供沟通策略建议。

### 设计理念

- **隐私优先**：全量本地处理，数据不上传云端
- **双模式分析**：长期历史数据 + 短期实时监听
- **AI 驱动**：基于 LLM 生成个性化沟通建议
- **科学量化**：采用学术论文验证的分析方法

---

## 核心特性

### 已实现功能 ✅

- **数据导入**
  - 微信 4.0+ 数据库自动检测与解密（SQLCipher 4）
  - 多数据库分片支持（11 个文件）
  - 自动数据清洗与预处理

- **数据可视化**
  - 情绪曲线图：展示情绪变化趋势
  - 词云分析：高频词与主题识别
  - 聊天频率图：活跃时段分析

- **隐私与安全**
  - 本地 SQLite 数据存储
  - API 密钥加密保存
  - 数据清理与导出功能

- **实时监听**（实验性）
  - Windows 微信客户端实时抓取
  - 单联系人监听支持
  - wxauto4 + 轮询机制

### 规划中功能 🚧

- **语言风格匹配**
  - LSM 分析（基于 jieba.posseg 词性标注）
  - 综合评分系统（积极度、共鸣感、情感值）

### 已实现的高级分析 ✅

- **特征提取模块** (2025-01-05 完成)
  - ✅ Session 会话切割（30 分钟阈值 + 睡眠时间判断）
  - ✅ 响应时间计算（排除睡眠时间 + 异常值过滤）
  - ✅ 主动性统计（会话发起者识别 + 主动率计算）
  - ✅ 字数统计（整体 + 按会话统计）

- **AI 策略建议**
  - 基于历史画像的个性化话术生成
  - 多目标支持（亲密/维持/疏远）
  - 实时建议面板

---

## 技术架构

### 整体架构

```
┌─────────────┐
│   前端 Vue   │ ← 用户界面
└──────┬──────┘
       │ PyWebView Bridge
┌──────▼──────┐
│  后端 Python │ ← 业务逻辑
├─────────────┤
│   SQLite    │ ← 数据存储
└─────────────┘
       │
┌──────▼──────┐
│ 微信数据库   │ ← 解密读取
└─────────────┘
```

### 技术栈

**后端**
- Python 3.8+
- SQLite（数据存储）
- PyWebView（桌面应用框架）
- pycryptodome（SQLCipher 4 解密）
- jieba（中文分词）
- SnowNLP（情感分析）
- scikit-learn（余弦相似度）

**前端**
- Vue 3 + TypeScript
- Vite（构建工具）
- ECharts（数据可视化）

---

## 快速开始

### 系统要求

- **操作系统**：Windows 10/11
- **微信版本**：4.0+（支持新版数据库结构）
- **Python**：3.8+
- **Node.js**：16+

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd Chrono-Trace

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 安装前端依赖
cd frontend && npm install && cd ..

# 4. 启动应用（开发模式）
python app_dev.py

# 应用将在 http://localhost:5173 启动
```

### 使用流程

1. **获取微信数据库密钥**
   - 下载工具：[wx_key](https://github.com/ycccccccy/wx_key)
   - 运行工具获取 64 位 hex 密钥

2. **导入数据**
   - 在应用中输入密钥
   - 应用自动检测微信数据目录
   - 点击"开始导入"

3. **数据分析**
   - 查看情绪曲线、词云等可视化图表
   - 生成个性化沟通策略

---

## 项目结构

```
Chrono-Trace/
├── backend/                 # 后端服务
│   ├── app/
│   │   ├── db/             # 数据库层
│   │   │   ├── connection.py
│   │   │   └── schema.sql
│   │   ├── services/       # 业务逻辑
│   │   │   ├── wechat/     # 微信数据处理
│   │   │   │   ├── db/     # V4 数据库解析
│   │   │   │   │   └── v4/
│   │   │   │   │       ├── contact.py    # 联系人解析
│   │   │   │   │       └── message.py    # 消息解析
│   │   │   │   ├── db_decryptor_v2.py    # SQLCipher 4 解密
│   │   │   │   ├── path_finder.py        # 路径查找
│   │   │   │   └── ingest_service.py     # 导入服务
│   │   │   └── analysis/  # 分析模块
│   │   │       ├── preprocessing_service.py  # 数据预处理
│   │   │       ├── feature_extraction_service.py  # 特征提取
│   │   │       ├── sentiment_service.py  # 情感分析
│   │   │       └── scoring_service.py    # 综合评分
│   │   └── webview/       # 前端桥接
│   │       └── bridge.py
│   └── data/               # 数据文件
│       ├── chrono_trace.db
│       └── settings.json
├── frontend/               # 前端应用
│   ├── src/
│   │   ├── api/           # API 调用
│   │   ├── components/    # Vue 组件
│   │   └── views/         # 页面
│   └── package.json
├── docs/                  # 文档
│   ├── SETUP.md          # 安装指南
│   └── DEVELOPMENT.md    # 开发指南
├── PROJECT.md            # 项目总览（本文件）
├── TODO.md               # 待办事项
├── app.py                # 生产入口
├── app_dev.py            # 开发入口
└── requirements.txt      # Python 依赖
```

---

## 核心功能

### 1. 微信数据库解密

**实现原理**：
- 参考 [EchoTrace](https://github.com/ycccccccy/echotrace) 项目
- SQLCipher 4 标准
- PBKDF2-HMAC-SHA512 密钥派生（256,000 次迭代）
- AES-256-CBC 页面解密

**关键参数**：
```python
PAGE_SIZE = 4096              # 页大小
V4_ITER_COUNT = 256000        # KDF 迭代次数
HMAC_SHA512_SIZE = 64         # HMAC 长度
IV_SIZE = 16                  # AES IV 长度
```

**核心类**：
```python
class WeChatDBDecryptorV2:
    def verify_key_from_file(db_path, key_hex) -> bool:
        """验证密钥是否正确"""

    def decrypt_database(input_path, output_path, key_hex):
        """解密整个数据库到临时文件"""
```

### 2. 微信 4.0+ 数据库解析

**V4 版本关键特性**：
- 路径结构：`xwechat_files/wxid_xxx/db_storage/{contact,message,session}/`
- 消息表命名：`MSG_{MD5(username)}`
- Name2Id 映射表：rowid → username

**已验证数据**：
- ✅ 联系人：354 个
- ✅ 消息：47,698 条
- ✅ 会话：245 个
- ✅ 数据库文件：11 个分片

### 3. 数据预处理（已完成）

**功能**：
- 移除 XML 系统消息、表情和媒体标签
- 字符数和词数统计
- 预处理缓存表（避免重复处理）

**触发时机**：
- 导入时自动预处理（推荐）
- 分析时按需预处理（兜底）
- 手动批量预处理（可选）

**性能优化**：
- 缓存机制：命中率 > 95%
- 批量写入：减少 I/O 操作
- 智能跳过：检测缓存避免重复清洗

### 4. 特征提取（规划中）

**Session 会话切割**：
- 阈值：1800 秒（30 分钟）
- 睡眠时间判断：00:00-07:00
- 跨越睡眠时间强制切割

**响应时间计算**：
- 排除负数和超过 24 小时的异常值
- 睡眠时间处理：调整到次日 07:00
- 统计：平均值、中位数、最快/最慢响应

**语言风格匹配（LSM）**：
- 使用 jieba.posseg 词性标注
- 虚词分类：助词、语气词、副词、代词、连词
- 余弦相似度计算

**主动率统计**：
- 基础指标：对方主动发起的 Session 占比
- 连续主动指标：连续发送多条消息的次数

### 5. 情感分析（规划中）

**实现方案**：
- SnowNLP 情感分值（0-1）
- 滑动窗口分析（最近 N 条消息）
- 情绪趋势按时间分段

### 6. 综合评分（规划中）

**评分维度**：
- **积极度评分**：响应速度（40%）+ 回复率（30%）+ 字数投入（30%）
- **共鸣感评分**：LSM 相似度（60%）+ 表情包重复度（40%）
- **情感值评分**：SnowNLP 平均情感分

**异常值检测**：
- 响应时间 > 24 小时
- 主动率 = 0
- 情感值 < 0.3

---

## 开发指南

### 开发环境设置

```bash
# Python 依赖
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install

# 启动开发服务器
python app_dev.py
```

### 核心模块说明

#### 1. 路径查找（`path_finder.py`）

```python
class WeChatPathFinder:
    @staticmethod
    def find_all_wechat_dbs() -> Dict:
        """查找所有微信数据库"""
        # 返回格式：
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

#### 2. 联系人解析（`db/v4/contact.py`）

```python
class ContactDBV4:
    def __init__(self, db_path: str, db_key: str):
        """初始化并解密数据库"""

    def get_contacts(self) -> List[dict]:
        """获取所有联系人"""
```

#### 3. 消息解析（`db/v4/message.py`）

```python
class MessageDBV4:
    def __init__(self, db_paths: List[str], db_key: str, my_wxid: str):
        """连接多个数据库分片"""

    def get_messages(self, username: str, time_range=None, limit=None) -> List[dict]:
        """获取指定会话的消息"""
```

#### 4. 数据预处理（`preprocessing_service.py`）

```python
class PreprocessingService:
    def preprocess_conversation(conversation_id: int) -> Dict:
        """预处理整个对话"""

    def preprocess_message_batch(message_ids: List[int]) -> Dict:
        """批量预处理指定消息"""
```

### 代码规范

**Python**：
- 类名：`PascalCase`
- 函数/变量：`snake_case`
- 常量：`UPPER_SNAKE_CASE`
- Debug 输出：`print(f"[DEBUG ClassName] 描述: {variable}")`

**TypeScript/Vue**：
- 组件：`PascalCase.vue`
- 函数/变量：`camelCase`
- 常量：`UPPER_SNAKE_CASE`

### API 接口（Bridge）

**导入相关**：
```python
get_wechat_paths() -> Dict[str, Any]
verify_wechat_key(db_key: str) -> Dict[str, Any]
import_wechat_data(db_key: str, options: Dict) -> Dict[str, Any]
```

**分析相关**：
```python
get_analysis(conversation_id: int, date_range: Dict) -> Dict[str, Any]
generate_suggestion(intent: str, context: Dict) -> Dict[str, Any]
```

**设置相关**：
```python
get_settings() -> Dict[str, Any]
set_settings(payload: Dict[str, Any]) -> Dict[str, Any]
```

### 调试技巧

**查看数据库内容**：
```bash
sqlite3 backend/data/chrono_trace.db
.schema
SELECT COUNT(*) FROM contacts;
SELECT COUNT(*) FROM messages;
```

**查看微信数据库结构**：
```python
import sqlite3
conn = sqlite3.connect(temp_db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print(cursor.fetchall())
```

---

## 相关文档

### 项目文档
- [PROJECT.md](PROJECT.md) - 项目总览（本文件）
- [TODO.md](TODO.md) - 开发待办清单
- [CHANGELOG.md](CHANGELOG.md) - 更新日志

### 详细指南
- [docs/SETUP.md](docs/SETUP.md) - 安装与配置指南
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) - 开发技术文档

### 专项文档
- [backend/app/services/wechat/db/README.md](backend/app/services/wechat/db/README.md) - 微信数据库适配层说明

### 外部资源
- [wx_key](https://github.com/ycccccccy/wx_key) - 获取微信数据库密钥
- [EchoTrace](https://github.com/ycccccccy/echotrace) - SQLCipher 4 解密算法参考
- [PyWxDump](https://github.com/xaoyaoo/PyWxDump) - Session 切割算法参考
- [QQchatlog_Analysis](https://github.com/GuangzeGAO/QQchatlog_Analysis) - 情感分析与评分参考

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发流程

1. Fork 项目
2. 创建特性分支（`git checkout -b feature/AmazingFeature`）
3. 提交更改（`git commit -m 'Add some AmazingFeature'`）
4. 推送到分支（`git push origin feature/AmazingFeature`）
5. 提交 Pull Request

### Commit 规范

```
<type>: <description>

[optional body]
```

**Type**：
- `feat`：新功能
- `fix`：Bug 修复
- `docs`：文档更新
- `refactor`：重构
- `test`：测试相关

---

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 免责声明

本工具仅供个人学习和研究使用，请遵守相关法律法规。使用本工具产生的任何后果由使用者自行承担，开发者不承担任何责任。

---

**最后更新**：2025-01-05
**状态**：✅ 已完成微信 V4 数据库支持
**版本**：1.0.0
