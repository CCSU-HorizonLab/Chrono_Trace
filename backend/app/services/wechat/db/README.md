# 微信数据库适配层

## 📖 快速了解

### 为什么要有这个文件夹？

**问题**: 新版微信的数据库结构和旧版完全不同，导致导入失败（0人0消息）

**解决**: 创建数据库适配层，自动识别微信版本并使用对应的解析逻辑

---

## 🏗️ 架构说明

```
db/
├── base.py          # 所有数据库类的统一接口（抽象类）
├── detector.py      # 自动检测微信是 V3 还是 V4 版本
├── v3/              # 旧版微信支持（暂未实现）
└── v4/              # 新版微信支持（重点）
    ├── contact.py   # 读取联系人数据
    └── message.py   # 读取消息数据
```

---

## 🎯 核心概念

### V3 vs V4 数据库结构对比

| 特征 | V3 (旧版) | V4 (新版) |
|------|----------|----------|
| 路径 | `Msg/MicroMsg.db` | `contact/contact.db` |
| 消息表 | `MSG0.db` | `message/message_0.db` |
| 表命名 | 直接用表名 | `Msg_{MD5(username)}` |
| 发送者 | 直接存wxid | 通过 `Name2Id` 表映射 |

### V4 版本关键点

#### 1. 消息表命名规则
```python
# 每个聊天对象都有独立的表
username = "wxid_abc123"
table_name = f"Msg_{hashlib.md5(username.encode()).hexdigest()}"
# 结果: "Msg_5d41402abc4b2a76b9719d911017c592"
```

#### 2. Name2Id 映射表
```sql
-- Name2Id 表结构
CREATE TABLE Name2Id (
    rowid INTEGER PRIMARY KEY,  -- SQLite 自动生成
    user_name TEXT              -- 微信ID (wxid_xxx)
);

-- 消息表中存储的是 rowid
SELECT msg.*, Name2Id.user_name
FROM Msg_xxx AS msg
JOIN Name2Id ON msg.real_sender_id = Name2Id.rowid
```

#### 3. 联系人字段
```sql
SELECT 
    username,          -- wxid_xxx
    alias,             -- 微信号
    local_type,        -- 1=普通人, 2=群聊, 5=OpenIM
    flag,              -- 标志位 (星标/置顶)
    remark,            -- 备注名
    nick_name,         -- 昵称
    extra_buffer       -- protobuf 数据 (性别/签名/地区)
FROM contact
WHERE local_type IN (1, 2, 5)
```

---

## 🔧 开发指南

### 如果你要添加新功能

#### 步骤1: 在 `base.py` 定义接口
```python
class WeChatDBBase(ABC):
    @abstractmethod
    def get_new_feature(self):
        """你的新功能说明"""
        pass
```

#### 步骤2: 在 `v4/` 实现具体逻辑
```python
class ContactDBV4(WeChatDBBase):
    def get_new_feature(self):
        # 实现 V4 版本的逻辑
        sql = "SELECT ..."
        self.cursor.execute(sql)
        return self.cursor.fetchall()
```

#### 步骤3: 在 `ingest_service.py` 调用
```python
# 自动选择版本
db = create_db_instance(version)  # 内部根据版本创建对应实例
result = db.get_new_feature()
```

---

## 📝 关键代码示例

### 示例1: 读取联系人
```python
from .v4.contact import ContactDBV4

# 初始化
db = ContactDBV4("WeChat Files/wxid_xxx/contact/contact.db")

# 获取所有联系人
contacts = db.get_contacts()

# 遍历
for contact in contacts:
    print(f"{contact.remark} ({contact.username})")
```

### 示例2: 读取消息
```python
from .v4.message import MessageDBV4

# 初始化（可能有多个数据库文件）
db = MessageDBV4([
    "WeChat Files/wxid_xxx/message/message_0.db",
    "WeChat Files/wxid_xxx/message/message_1.db",
])

# 获取与某人的聊天记录
messages = db.get_messages(
    username="wxid_friend123",
    time_range=(start_timestamp, end_timestamp)
)

# 遍历
for msg in messages:
    print(f"{msg.sender}: {msg.content}")
```

### 示例3: 版本检测
```python
from .detector import detect_wechat_version

version = detect_wechat_version("WeChat Files/wxid_xxx")

if version == "v4":
    print("使用新版微信数据库解析器")
elif version == "v3":
    print("使用旧版微信数据库解析器")
else:
    print("无法识别微信版本")
```

---

## 🐛 调试技巧

### 问题: 找不到消息表
```python
# 检查表名是否正确
import hashlib
username = "wxid_abc123"
table_name = f"Msg_{hashlib.md5(username.encode()).hexdigest()}"
print(f"应该查询的表名: {table_name}")

# 列出数据库中所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("实际存在的表:", cursor.fetchall())
```

### 问题: Name2Id 映射失败
```sql
-- 检查 Name2Id 表内容
SELECT rowid, user_name FROM Name2Id LIMIT 10;

-- 检查消息表的 real_sender_id
SELECT DISTINCT real_sender_id FROM Msg_xxx LIMIT 10;
```

### 问题: 时间字段解析错误
```python
# V4 的 create_time 是 Unix 时间戳（整数）
create_time = 1699876543  # 数据库中的值

# 转换成可读时间
from datetime import datetime
readable = datetime.fromtimestamp(create_time)
print(readable)  # 2023-11-13 12:34:03
```

---

## ⚠️ 常见陷阱

1. **字段名大小写**
   - ❌ `UserName` (驼峰)
   - ✅ `user_name` (下划线)

2. **时间格式**
   - ❌ `"2023-11-13 12:34:03"` (字符串)
   - ✅ `1699876543` (Unix时间戳)

3. **消息表查询**
   - ❌ `FROM MSG0` (旧版表名)
   - ✅ `FROM Msg_{MD5(username)}` (V4表名)

4. **发送者识别**
   - ❌ 直接从消息表读 sender
   - ✅ JOIN Name2Id 表获取 user_name

---

## 📚 参考文档

- **完整迁移计划**: 查看同目录下的 `MIGRATION_PLAN.md`
- **WeChatMsg 项目**: https://github.com/TC999/WeChatMsg
- **Protobuf 文档**: https://developers.google.com/protocol-buffers

---

## 🤝 贡献指南

如果你要修改这个模块：

1. **阅读**: 先看 `MIGRATION_PLAN.md` 了解整体架构
2. **遵循**: 所有新类必须继承 `WeChatDBBase`
3. **测试**: 修改后用真实数据库测试
4. **文档**: 更新这个 README.md

---

**最后更新**: 2025-11-13  
**维护者**: 待分配
