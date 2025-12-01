# 微信V4数据库支持实施日志

> **完成时间**: 2025-11-27  
> **状态**: ✅ 成功  
> **导入结果**: 354个联系人 + 47,698条消息 + 245个会话

---

## 🎯 实施目标

实现对微信4.0+版本新数据库结构的完整支持,包括:
1. SQLCipher 4加密数据库解密
2. 新目录结构适配 (`xwechat_files/wxid_xxx/db_storage/`)
3. 多数据库分片处理
4. 自定义路径配置

---

## 📋 实施过程

### 阶段1: 问题诊断 (2025-11-27 上午)

**初始症状**:
- 导入成功但数据为0
- 日志显示: `databases: {'message': [], 'contact': ''}`

**诊断步骤**:
1. 执行 `tree` 命令查看实际目录结构
2. 发现数据库位于 `db_storage` 子目录下
3. 发现前端传递的databases字段为空

**根本原因**:
- 前端只保存了 `wechat_dir` 和 `current_user`
- 后端错误地直接使用了前端传来的空 `databases` 字段
- 路径查找函数未被调用

---

### 阶段2: 路径查找修复 (2025-11-27)

**修改文件**: `backend/app/services/wechat/ingest_service.py`

**修改内容**:
```python
# 修改前:
if custom_paths and custom_paths.get("databases"):
    databases = custom_paths.get("databases", {})  # 直接使用空值

# 修改后:
if custom_paths and custom_paths.get("wechat_dir") and custom_paths.get("current_user"):
    wechat_dir = custom_paths["wechat_dir"]
    wxid = custom_paths["current_user"]
    # 重新查找数据库文件
    databases = WeChatPathFinder.find_databases(wxid, wechat_dir)
```

**效果**:
- ✅ 成功找到11个数据库文件
- ✅ contact.db路径正确
- ✅ message_0~3.db, biz_message_0~3.db等全部找到

---

### 阶段3: 解密器修复 (2025-11-27)

**问题**: `'builtin_function_or_method' object has no attribute 'digest_size'`

**修改文件**: `backend/app/services/wechat/db_decryptor_v2.py`

**修改内容**:
```python
# 修改前:
from Crypto.Protocol.KDF import PBKDF2
enc_key = PBKDF2(key, salt, dkLen=32, count=256000, hmac_hash_module=hashlib.sha512)

# 修改后:
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512
enc_key = PBKDF2(key, salt, dkLen=32, count=256000, hmac_hash_module=SHA512)
```

**原因**:
- `pycryptodome` 的 `PBKDF2` 需要 `Crypto.Hash` 模块对象
- 而不是 `hashlib` 的函数对象

**效果**:
- ✅ 密钥验证成功
- ✅ HMAC-SHA512验证通过
- ✅ 所有数据库成功解密

---

### 阶段4: Bridge层优化 (2025-11-27)

**修改文件**: `backend/app/webview/bridge.py`

**修改内容**:
```python
# 修改前: 传递空的databases字典
custom_paths = {
    "wechat_dir": self.settings.get("wechat_data_dir"),
    "current_user": self.settings.get("wechat_user_wxid"),
    "databases": {
        "message": [msg_db] if msg_db else [],
        "contact": contact_db,
    }
}

# 修改后: 只传递必要信息,databases由后端查找
custom_paths = {
    "wechat_dir": wechat_dir,
    "current_user": wxid
}
```

**优化点**:
- 移除对 `wechat_use_custom_path` 标志的强依赖
- 简化数据传递,只传关键路径信息
- 数据库文件列表由后端实时查找

---

## 📊 最终实现架构

### 数据流向

```
用户输入密钥
    ↓
Bridge.import_wechat_data(db_key, options)
    ↓
获取settings中的wechat_dir和current_user
    ↓
IngestService.import_wechat_data(db_key, options, custom_paths)
    ↓
PathFinder.find_databases(wxid, wechat_dir)
    ↓
扫描 db_storage/{contact,message,session}/ 目录
    ↓
找到11个.db文件
    ↓
ContactDBV4: 解密contact.db → 读取354个联系人
MessageDBV4: 解密11个message_*.db → 读取47,698条消息
    ↓
写入chrono_trace.db
    ↓
清理临时文件
    ↓
返回统计结果
```

### 技术栈

**解密层**:
- 库: `pycryptodome`
- 算法: PBKDF2-HMAC-SHA512 (256000迭代)
- 加密: AES-256-CBC
- 验证: HMAC-SHA512

**数据库层**:
- SQLCipher 4 格式
- 页大小: 4096字节
- 保留区: 16(IV) + 64(HMAC) + padding

**文件管理**:
- 临时文件: `tempfile.mktemp(suffix='.db')`
- 自动清理: `os.remove()` in `__del__()`

---

## 🔍 关键代码片段

### 1. 路径查找核心逻辑

```python
# path_finder.py: _find_databases_v4()
def _find_databases_v4(db_storage_dir: Path) -> Dict[str, List[str]]:
    result = {
        "message": [],
        "session": None,
        "contact": None
    }
    
    # 查找联系人数据库
    contact_dir = db_storage_dir / "contact"
    if contact_dir.exists():
        for file in contact_dir.iterdir():
            if file.suffix.lower() == ".db":
                result["contact"] = str(file)
                break
    
    # 查找消息数据库(可能有多个分片)
    message_dir = db_storage_dir / "message"
    if message_dir.exists():
        for file in message_dir.iterdir():
            if file.suffix.lower() == ".db":
                result["message"].append(str(file))
        result["message"].sort()
    
    return result
```

### 2. SQLCipher 4解密核心

```python
# db_decryptor_v2.py: derive_keys()
def derive_keys(self, key: bytes, salt: bytes) -> Tuple[bytes, bytes]:
    from Crypto.Hash import SHA512
    
    # 生成加密密钥
    enc_key = PBKDF2(
        key, 
        salt, 
        dkLen=32,
        count=256000,
        hmac_hash_module=SHA512
    )
    
    # 生成MAC密钥
    mac_salt = bytes(b ^ 0x3a for b in salt)
    mac_key = PBKDF2(
        enc_key,
        mac_salt,
        dkLen=32,
        count=2,
        hmac_hash_module=SHA512
    )
    
    return enc_key, mac_key
```

### 3. 消息表名生成

```python
# db/v4/message.py: _get_table_name()
def _get_table_name(self, username: str) -> str:
    """生成消息表名 (MD5哈希)"""
    md5_hash = hashlib.md5(username.encode('utf-8')).hexdigest()
    return f"MSG_{md5_hash}"
```

---

## 📈 性能指标

### 导入性能
- **总时长**: ~30秒 (47,698条消息)
- **解密速度**: ~2秒/数据库 (11个文件)
- **插入速度**: ~1500条/秒

### 资源使用
- **临时文件**: 11个 (总计~200MB)
- **内存峰值**: ~150MB
- **磁盘IO**: 读取~200MB, 写入~50MB

### 数据统计
| 类型 | 数量 | 来源 |
|------|------|------|
| 联系人 | 354 | contact.db |
| 消息 | 47,698 | message_*.db × 11 |
| 会话 | 245 | 消息聚合 |
| 数据库文件 | 11 | db_storage/message/ |

---

## ⚠️ 遇到的问题与解决

### 问题1: 数据库为空

**症状**: `databases: {'message': [], 'contact': ''}`

**解决**: 
1. 修改 `ingest_service.py` 使用 `wechat_dir` 重新查找
2. 修改 `bridge.py` 只传递必要字段

**教训**: 前端不应传递复杂的数据结构,应由后端实时查找

---

### 问题2: PBKDF2参数错误

**症状**: `'builtin_function_or_method' object has no attribute 'digest_size'`

**解决**: 使用 `Crypto.Hash.SHA512` 代替 `hashlib.sha512`

**教训**: `pycryptodome` 的API与标准库不同,需要传递模块对象

---

### 问题3: 临时文件泄漏

**症状**: 解密后的临时文件未清理

**解决**: 在 `__del__()` 中添加清理逻辑

```python
def __del__(self):
    self.close()

def close(self):
    if self.conn:
        self.conn.close()
    if self.temp_db_path and os.path.exists(self.temp_db_path):
        os.remove(self.temp_db_path)
```

**教训**: 使用临时文件时务必确保清理机制

---

## ✅ 验证清单

- [x] 路径查找正确 (11个文件全部找到)
- [x] 密钥验证通过 (HMAC验证成功)
- [x] 数据库解密成功 (11个文件)
- [x] 联系人导入正确 (354个)
- [x] 消息导入正确 (47,698条)
- [x] 会话统计正确 (245个)
- [x] 临时文件清理 (11个文件已删除)
- [x] 错误日志正常 (无异常堆栈)
- [x] 性能可接受 (~30秒完成)

---

## 🎓 技术要点总结

### SQLCipher 4 解密要点

1. **密钥派生**: PBKDF2-HMAC-SHA512, 256000次迭代
2. **页大小**: 4096字节 (微信V4固定)
3. **保留区**: 末尾80字节 (16 IV + 64 HMAC)
4. **MAC验证**: 每页都有HMAC-SHA512签名
5. **加密算法**: AES-256-CBC

### 微信V4目录结构

```
xwechat_files/
└── wxid_anon_account/
    └── db_storage/
        ├── contact/
        │   ├── contact.db          # 联系人主库
        │   └── contact_fts.db      # 全文搜索索引
        ├── message/
        │   ├── message_0.db        # 消息分片0
        │   ├── message_1.db        # 消息分片1
        │   ├── message_2.db        # 消息分片2
        │   ├── message_3.db        # 消息分片3
        │   ├── biz_message_0.db    # 企业消息0
        │   ├── biz_message_1.db    # 企业消息1
        │   ├── biz_message_2.db    # 企业消息2
        │   ├── biz_message_3.db    # 企业消息3
        │   ├── media_0.db          # 媒体库
        │   ├── message_fts.db      # 全文搜索
        │   └── message_resource.db # 资源库
        └── session/
            └── session.db          # 会话库
```

### 表名哈希规则

微信V4使用MD5哈希生成消息表名:
```python
table_name = f"MSG_{hashlib.md5(username.encode('utf-8')).hexdigest()}"
# 例如: MSG_1a2b3c4d5e6f7890abcdef1234567890
```

---

## 📝 文档更新

已更新的文档:
- [x] `TODO.md` - 任务清单标记完成
- [x] `V4_IMPLEMENTATION_LOG.md` - 本实施日志

待创建的文档:
- [ ] API文档 (数据库接口说明)
- [ ] 用户手册 (如何获取密钥和配置路径)
- [ ] 故障排除指南

---

## 🚀 后续工作建议

### 短期优化 (1-2天)

1. **安装echarts依赖**
   ```bash
   cd frontend
   npm install echarts
   ```

2. **添加进度显示**
   - 在前端显示解密进度条
   - 显示当前处理的数据库文件名

3. **错误处理增强**
   - 捕获并展示更友好的错误信息
   - 添加重试机制

### 中期优化 (1周)

1. **增量导入**
   - 记录上次导入时间
   - 只导入新增消息

2. **性能优化**
   - 使用多线程并发解密
   - 优化SQL批量插入

3. **数据验证**
   - 添加导入后数据校验
   - 生成导入报告

### 长期规划 (1个月)

1. **支持更多数据类型**
   - 图片/视频元数据
   - 文件传输记录
   - 语音通话记录

2. **数据分析功能**
   - 情绪分析
   - 词频统计
   - 关系图谱

3. **导出功能**
   - 导出为JSON/CSV
   - 生成可读HTML报告

---

## 🔄 实时监听功能（实验特性）

- 新增基于 `wxauto4` 的单会话实时监听能力，用于捕获当前聊天窗口的新消息。
- 后端新增 `RealtimeMonitorService` 与 `MessageBuffer`，通过轮询线程每 1 秒主动从微信主窗口拉取消息并写入暂存表 `realtime_message_buffer`。
- 前端通过 Bridge 暴露的接口调用：
  - `start_realtime_monitor(display_name)`：开始监听指定联系人
  - `stop_realtime_monitor()`：停止当前监听
  - `get_realtime_status()` / `get_realtime_messages(batch_id)`：查询监听状态与本次会话的实时消息
- 当前限制：
  - 仅支持 Windows + 微信 4.0.5 客户端
  - 仅支持微信主窗口的单聊会话（单击联系人显示的聊天区域），不支持独立弹窗与多开
  - 单实例单会话：同一时间只监听一个对象

**文档维护者**: CAN  
**最后更新**: 2025-12-01  
**版本**: 1.1.0
