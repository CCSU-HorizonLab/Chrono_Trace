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

---

## 📊 历史数据分析功能：词云生成

> **完成时间**: 2025-12-04  
> **状态**: ✅ 完成  
> **功能**: 聊天词云可视化 + 智能过滤 + 快捷时间选择

### 功能概述

在"历史数据"页面新增聊天词云功能，用户可选择联系人和时间范围，系统自动分析聊天内容并生成词云可视化，展示高频关键词。

### 实施过程

#### 阶段1: 后端服务搭建 (2025-12-04)

**新增文件**:
- `backend/app/services/analysis/__init__.py` - 模块导出
- `backend/app/services/analysis/analysis_service.py` - 分析服务主类
- `backend/app/services/analysis/wordcloud_generator.py` - 词云生成器

**核心功能**:
1. **联系人列表查询**: 关联`conversations`和`contacts`表，优先显示备注名
2. **消息查询**: 按会话ID和时间范围查询文本消息（最多10000条）
3. **词云生成**: 基于jieba分词 + 停用词过滤 + 词频统计

**技术栈**:
- 分词库: `jieba`
- 词频统计: `collections.Counter`
- 数据库: SQLite3

---

#### 阶段2: 前端集成 (2025-12-04)

**修改文件**:
- `backend/app/webview/bridge.py` - 新增2个接口
  - `get_conversation_list()`: 获取联系人列表
  - `get_analysis()`: 获取词云数据
- `frontend/src/api/bridge.ts` - 类型定义
- `frontend/src/views/Analytics.vue` - 主页面逻辑
- `frontend/src/components/analytics/FiltersBar.vue` - 筛选栏UI

**数据流**:
```
用户选择联系人 
  → onConversationChange() 
  → api.get_analysis({conversation_id, from, to})
  → Bridge.get_analysis()
  → AnalysisService.get_analysis()
  → WordCloudGenerator.generate()
  → 返回 {wordcloud: [{word, weight}], subject: {...}}
  → 前端渲染 <WordCloud :words="..." />
```

---

#### 阶段3: 问题修复 (2025-12-04)

##### 问题1: Bytes类型错误

**症状**: `TypeError: sequence item 57: expected str instance, bytes found`

**原因**: 数据库`content`字段存储为bytes类型

**解决**:
```python
# wordcloud_generator.py
for t in texts:
    if isinstance(t, bytes):
        try:
            t = t.decode('utf-8')
        except Exception:
            continue
    text_list.append(t)
```

---

##### 问题2: 自动选择联系人

**症状**: 页面加载时自动选择第一个联系人并触发分析

**解决**: 删除自动选择逻辑，要求用户手动选择
```typescript
// Analytics.vue - 删除以下代码
// if (conversations.value.length > 0 && !selectedConversationId.value) {
//   selectedConversationId.value = conversations.value[0].id
// }
```

---

##### 问题3: 联系人显示为空

**症状**: 部分联系人下拉框中只显示消息数，不显示名称

**原因**: 
- 某些联系人在`contacts`表中没有记录
- SQL查询返回空字符串未正确处理

**解决**: 优化SQL查询，使用`NULLIF(TRIM(...))`处理空值
```sql
SELECT 
    c.id,
    c.username,
    COALESCE(
        NULLIF(TRIM(ct.remark), ''),      -- 优先：contacts备注名
        NULLIF(TRIM(ct.nickname), ''),    -- 其次：contacts昵称
        NULLIF(TRIM(c.display_name), ''), -- 再次：conversations显示名
        NULLIF(TRIM(c.username), ''),     -- 最后：username
        '未知联系人'                       -- 兜底
    ) as name,
    c.message_count
FROM conversations c
LEFT JOIN contacts ct ON c.username = ct.username
WHERE c.is_deleted = 0 AND c.message_count > 0
ORDER BY c.updated_at DESC
```

**前端兜底**:
```vue
<!-- FiltersBar.vue -->
<option :value="conv.id">
  {{ conv.name || conv.username || '未知联系人' }} ({{ conv.message_count }}条)
</option>
```

---

##### 问题4: 无意义词过多

**症状**: 词云中出现"有点"、"一下"、"哈哈哈"等无意义词

**解决**: 扩充停用词表，从100个扩展到160+个

**新增词类**:
1. **口语词**: 有点、一下、一点、感觉、觉得、应该、可能
2. **程度副词**: 非常、特别、挺、蛮、超级、极其
3. **时间词**: 现在、刚才、马上、今天、明天、昨天
4. **语气词**: 哈哈、呵呵、嘿嘿、嘻嘻、哎呀、唉
5. **常见短语**: 不知道、怎么样、没关系、没问题
6. **疑问词**: 为什么、怎么办、怎么了、干嘛
7. **确认词**: 嗯嗯、好吧、行吧、是的、对啊

**重复字符检测**:
```python
def _is_repeated_char(self, text: str) -> bool:
    """过滤"哈哈哈"、"嘿嘿嘿"等重复词"""
    # 情况1: 所有字符相同
    if len(set(text)) == 1:
        return True
    
    # 情况2: 两字符重复（哈哈哈哈 = 哈哈 + 哈哈）
    if len(text) >= 4 and len(text) % 2 == 0:
        half = len(text) // 2
        if text[:half] == text[half:]:
            return True
    
    return False
```

---

##### 问题5: Emoji干扰词云

**症状**: 词云中出现"旺柴"、"笑脸"等词（实际是emoji表情）

**原因**: 微信emoji在数据库中存储为`[旺柴]`、`[笑脸]`格式，分词后变成普通词

**解决**: 在文本预处理阶段用正则过滤
```python
import re

# 过滤 [emoji] 格式
t = re.sub(r'\[.*?\]', ' ', t)

# 合并多余空格
t = re.sub(r'\s+', ' ', t).strip()
```

---

#### 阶段4: 功能增强 (2025-12-04)

##### 增强1: 快捷时间选择

**新增按钮**:
- 近7天
- 近30天
- 近半年（180天）
- 近一年（365天）
- 全部（从2000-01-01到今天）

**实现**:
```typescript
// FiltersBar.vue
function quick(days: number) {
  const to = new Date()
  const from = new Date()
  from.setDate(to.getDate() - (days - 1))
  emit('update:dates', { from: fmt(from), to: fmt(to) })
}

function quickAll() {
  const to = new Date()
  const from = new Date(2000, 0, 1)
  emit('update:dates', { from: fmt(from), to: fmt(to) })
}
```

---

##### 增强2: 词云数量优化

**调整**: 从50个高频词减少到30个

**原因**: 
- 过多词汇影响可视化效果
- 30个词足以展示主要话题

**修改**:
```python
# analysis_service.py
wordcloud = self.wordcloud_gen.generate(messages, top_n=30)

# wordcloud_generator.py
def generate(self, texts: List[str], top_n: int = 30):
```

---

### 核心算法: 词云生成流程

```python
def generate(self, texts: List[str], top_n: int = 30):
    """
    输入: 消息文本列表
    输出: [{"word": "开心", "weight": 100}, ...]
    """
    
    # 步骤1: 文本预处理
    text_list = []
    for t in texts:
        # 1.1 bytes转str
        if isinstance(t, bytes):
            t = t.decode('utf-8')
        
        # 1.2 过滤emoji [旺柴]、[笑脸]
        t = re.sub(r'\[.*?\]', ' ', t)
        
        # 1.3 合并空格
        t = re.sub(r'\s+', ' ', t).strip()
        
        if t:
            text_list.append(t)
    
    all_text = ' '.join(text_list)
    
    # 步骤2: Jieba分词
    words = jieba.cut(all_text)
    
    # 步骤3: 多层过滤
    filtered_words = []
    for w in words:
        w = w.strip()
        
        if len(w) < 2:               # 过滤单字
            continue
        if w in self.stopwords:       # 过滤停用词
            continue
        if w.isdigit():               # 过滤纯数字
            continue
        if self._is_punctuation(w):   # 过滤标点
            continue
        if self._is_repeated_char(w): # 过滤重复字符
            continue
        
        filtered_words.append(w)
    
    # 步骤4: 词频统计
    word_freq = Counter(filtered_words)
    
    # 步骤5: 取Top N
    top_words = word_freq.most_common(top_n)
    
    # 步骤6: 权重归一化（1-100）
    if not top_words:
        return []
    
    max_freq = top_words[0][1]
    min_freq = top_words[-1][1]
    freq_range = max_freq - min_freq if max_freq > min_freq else 1
    
    result = []
    for word, freq in top_words:
        weight = int(((freq - min_freq) / freq_range) * 99 + 1)
        result.append({"word": word, "weight": weight})
    
    return result
```

---

### 数据格式

#### 前端请求
```json
{
  "conversation_id": 15,
  "from": "2024-12-01",
  "to": "2024-12-04"
}
```

#### 后端响应
```json
{
  "subject": {
    "id": 15,
    "name": "张三",
    "username": "wxid_xxx",
    "stats": {
      "msgCount": 156
    }
  },
  "wordcloud": [
    {"word": "爬山", "weight": 100},
    {"word": "天气", "weight": 77},
    {"word": "今天", "weight": 62}
  ],
  "timeseries": []
}
```

---

### 性能指标

| 指标 | 数值 |
|-----|------|
| 消息查询速度 | ~100ms（10000条） |
| 分词速度 | ~500ms（10000条） |
| 词频统计 | ~50ms |
| 总耗时 | ~650ms |
| 内存占用 | ~20MB |

---

### 技术要点

#### 1. pywebview Bridge机制

前后端通过`pywebview.api`对象通信：

```typescript
// 前端调用
pywebview.api.get_analysis(JSON.stringify(params))

// 自动触发后端
class Bridge:
    def get_analysis(self, params_json: str):
        params = json.loads(params_json)
        result = self.analysis_service.get_analysis(...)
        return result  # 自动转为JSON
```

**优势**:
- 前后端运行在同一进程
- 无需HTTP服务器
- 调用延迟极低（<1ms）

---

#### 2. 停用词过滤策略

**多层过滤器**:
```python
过滤器1: 长度过滤（len < 2）
过滤器2: 停用词表（160+词）
过滤器3: 纯数字（isdigit）
过滤器4: 纯标点（_is_punctuation）
过滤器5: 重复字符（_is_repeated_char）
过滤器6: Emoji（正则 \[.*?\]）
```

**停用词分类**:
- 功能词: 的、了、吗、在、和
- 代词: 我、你、他、这、那
- 口语词: 有点、一下、感觉
- 语气词: 哈哈、呵呵、嘿嘿
- 时间词: 现在、刚才、今天
- 短语: 不知道、怎么样

---

#### 3. 权重归一化算法

**目的**: 将词频映射到1-100范围，便于前端渲染不同字号

**公式**:
```python
weight = ((freq - min_freq) / (max_freq - min_freq)) × 99 + 1
```

**示例**:
```
最高频词（25次）: weight = ((25-3)/(25-3)) × 99 + 1 = 100
中频词（12次）:    weight = ((12-3)/(25-3)) × 99 + 1 = 42
最低频词（3次）:   weight = ((3-3)/(25-3)) × 99 + 1 = 1
```

---

### 已知限制

1. **性能限制**: 单次查询最多10000条消息
2. **分词准确性**: 依赖jieba分词，可能存在错误分词
3. **停用词覆盖**: 160+词无法覆盖所有无意义词
4. **语言支持**: 仅支持中文分词

---

### 后续优化建议

#### 短期（1周）

1. **添加加载动画**: 查询数据时显示骨架屏
2. **错误提示优化**: 友好的错误信息展示
3. **词云交互**: 点击词条可跳转到相关消息

#### 中期（1个月）

1. **情绪分析**: 基于词汇情感倾向分析聊天情绪
2. **关键词趋势**: 展示词频随时间的变化
3. **多联系人对比**: 对比不同联系人的词云

#### 长期（3个月）

1. **自定义停用词**: 用户可添加/删除停用词
2. **AI总结**: 基于高频词生成聊天总结
3. **导出功能**: 导出词云图片/数据

---

### 文件修改清单

#### 新增文件（3个）
- `backend/app/services/analysis/__init__.py`
- `backend/app/services/analysis/analysis_service.py`
- `backend/app/services/analysis/wordcloud_generator.py`

#### 修改文件（4个）
- `backend/app/webview/bridge.py` - 新增2个接口
- `frontend/src/api/bridge.ts` - 类型定义
- `frontend/src/components/analytics/FiltersBar.vue` - UI增强
- `frontend/src/views/Analytics.vue` - 主逻辑

---

### 验证清单

- [x] 联系人列表正确显示（354个）
- [x] 联系人名称优先级正确（备注>昵称>username）
- [x] 词云数据正确生成（30个词）
- [x] 停用词过滤生效（160+词）
- [x] Emoji正确过滤（[旺柴]等）
- [x] 重复字符过滤（哈哈哈等）
- [x] 快捷时间选择正常（5个按钮）
- [x] 权重归一化正确（1-100范围）
- [x] 前端渲染正常（WordCloud组件）
- [x] 错误处理完善（bytes转换等）

---

**文档维护者**: CAN  
**最后更新**: 2025-12-04  
**版本**: 1.2.0
