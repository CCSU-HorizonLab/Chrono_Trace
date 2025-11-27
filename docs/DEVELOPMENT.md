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

**前端**:
- Vue 3 + TypeScript
- Vite (构建工具)
- 组件库: 自定义组件

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
│   │   ├── components/      # Vue组件
│   │   └── views/           # 页面
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
- 参考 EchoTrace 项目
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

**使用示例**:
```python
from backend.app.services.wechat.db_decryptor_v2 import WeChatDBDecryptorV2

decryptor = WeChatDBDecryptorV2()

# 验证密钥
if decryptor.verify_key_from_file(db_path, key_hex):
    # 解密到临时文件
    decryptor.decrypt_database(encrypted_db, temp_db, key_hex)
    
    # 使用标准sqlite3读取
    import sqlite3
    conn = sqlite3.connect(temp_db)
```

---

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

---

### 3. 联系人解析 (`db/v4/contact.py`)

**核心类**:
```python
class ContactDBV4:
    def __init__(self, db_path: str, db_key: str):
        """初始化并解密数据库"""
        
    def get_contacts(self) -> List[dict]:
        """获取所有联系人"""
        # 返回格式:
        [
            {
                "username": "wxid_xxx",
                "nickname": "昵称",
                "remark": "备注",
                "alias": "微信号",
                "is_friend": True
            },
            ...
        ]
```

**数据库表结构**:
```sql
CREATE TABLE Contact (
    username TEXT PRIMARY KEY,
    nick_name TEXT,
    remark TEXT,
    alias TEXT,
    type INTEGER
);
```

---

### 4. 消息解析 (`db/v4/message.py`)

**核心类**:
```python
class MessageDBV4:
    def __init__(self, db_paths: List[str], db_key: str, my_wxid: str):
        """连接多个数据库分片"""
        
    def get_all_conversation_usernames(self) -> List[str]:
        """获取所有会话的username列表"""
        
    def get_messages(self, username: str, time_range=None, limit=None) -> List[dict]:
        """获取指定会话的消息"""
        # 返回格式:
        [
            {
                "talker": "wxid_xxx",
                "content": "消息内容",
                "timestamp": 1732704000,
                "is_sender": False,
                "msg_type": 1
            },
            ...
        ]
```

**表名生成**:
```python
import hashlib

def _get_table_name(username: str) -> str:
    md5 = hashlib.md5(username.encode('utf-8')).hexdigest()
    return f"MSG_{md5}"
```

---

## 🧪 测试

### 单元测试

```bash
# 测试解密功能
python test_decrypt_v2.py

# 预期输出:
✅ 密钥验证成功
✅ 解密成功
✅ 读取到 354 个联系人
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

---

## 📦 构建发布

### 打包应用

```bash
# 安装打包工具
pip install pyinstaller

# 打包
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

---

**文档版本**: 1.0.0  
**最后更新**: 2025-11-27  
**维护者**: CAN
