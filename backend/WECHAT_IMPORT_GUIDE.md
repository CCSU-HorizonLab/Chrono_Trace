# 微信数据导入使用指南

## 📋 概述

Chrono Trace 现已支持从微信数据库直接导入聊天记录，实现长期数据分析与短期实时建议功能。

## 🔑 准备工作：获取微信数据库密钥

由于微信4.x版本数据库使用 SQLCipher 加密，需要先获取解密密钥。

### 方法：使用 wx_key 工具

1. **下载工具**
   - 访问 [wx_key GitHub仓库](https://github.com/ycccccccy/wx_key)
   - 下载最新版本的 `wx_key.exe`

2. **获取密钥**
   ```bash
   # 运行工具
   wx_key.exe
   
   # 启动微信并登录
   # 工具会自动检测并提取密钥
   ```

3. **记录密钥**
   - 工具会显示一个 **64位十六进制字符串**（例如：`1a2b3c4d5e6f...`）
   - 复制并保存这个密钥（32字节，64个hex字符）

## 📦 数据库设计

### 核心表结构

#### 1. conversations（会话表）
存储所有对话会话的元数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | TEXT | 微信username（唯一标识） |
| display_name | TEXT | 显示名称 |
| conversation_type | TEXT | 会话类型（private/group） |
| message_count | INTEGER | 消息总数 |
| created_at | INTEGER | 首次聊天时间 |
| updated_at | INTEGER | 最后消息时间 |

#### 2. contacts（联系人表）
存储联系人信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | TEXT | 微信username |
| nickname | TEXT | 昵称 |
| remark | TEXT | 备注名 |
| alias | TEXT | 微信号 |
| is_friend | INTEGER | 是否好友 |

#### 3. messages（消息表）
存储所有聊天消息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| conversation_id | INTEGER | 关联会话ID |
| local_id | INTEGER | 微信本地消息ID |
| talker | TEXT | 对话对象username |
| sender | TEXT | 发送者username（群聊时有效） |
| is_sender | INTEGER | 是否为本人发送 |
| message_type | INTEGER | 消息类型（1=文本，3=图片...） |
| content | TEXT | 消息内容 |
| timestamp | INTEGER | 消息时间戳（秒） |
| source | TEXT | 数据来源（long/realtime） |

#### 4. analysis_segments（分段分析表）
存储按时间段的聚合分析结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| conversation_id | INTEGER | 关联会话ID |
| from_ts | INTEGER | 时间段起始 |
| to_ts | INTEGER | 时间段结束 |
| summary | TEXT | 总结摘要 |
| metrics_json | TEXT | 统计指标JSON |

#### 5. suggestions（建议记录表）
存储LLM生成的话术建议。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| conversation_id | INTEGER | 关联会话ID |
| intent | TEXT | 意图（intimate/maintain/distance） |
| summary | TEXT | 建议摘要 |
| speech_json | TEXT | 话术列表JSON |
| source | TEXT | 来源（manual/realtime） |

## 🚀 使用步骤

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

主要依赖：
- `pycryptodome>=3.20.0` - 用于解密微信数据库(纯 Python 实现)
- `pywin32>=305` - 用于读取Windows注册表

### 2. 启动应用

```bash
python app_dev.py
```

### 3. 在前端导入数据

1. **打开首页**
   - 应用启动后会自动打开前端界面

2. **输入密钥**
   - 在"微信数据导入"卡片中
   - 粘贴之前获取的64位hex密钥

3. **验证密钥**（可选）
   - 点击"验证密钥"按钮
   - 确保密钥正确

4. **查看路径**（可选）
   - 点击"查看路径"按钮
   - 确认自动检测到的微信数据目录

5. **开始导入**
   - 选择导入选项（联系人/消息）
   - 点击"开始导入"按钮
   - 等待导入完成

## 🏗️ 技术实现

### 后端架构

```
backend/app/services/wechat/
├── path_finder.py      # 自动寻址微信数据库路径
├── db_decryptor_v2.py  # 数据库解密(纯 Python 实现)
├── db/v4/              # V4 数据库解析
│   ├── contact.py      # 联系人数据库
│   └── message.py      # 消息数据库
└── ingest_service.py   # 导入服务(整合流程)
```

### 工作流程

1. **路径查找**
   - 读取注册表 `HKEY_CURRENT_USER\Software\Tencent\WeChat`
   - 扫描 `WeChat Files/{wxid}/` 目录
   - 定位 `Msg/MicroMsg.db`、`Contact/Contact.db` 等文件

2. **数据库解密**
   - 使用 SQLCipher 打开加密数据库
   - 设置加密参数（cipher_page_size=1024, kdf_iter=64000...）
   - 验证密钥正确性

3. **数据解析**
   - 读取 `contact` 表 → 转换为 `Contact` 对象
   - 读取 `Msg_{md5}` 表 → 转换为 `Message` 对象
   - 生成器模式避免OOM

4. **批量入库**
   - 创建会话记录（conversations）
   - 批量插入消息（messages，每1000条提交）
   - 更新统计信息

## ⚠️ 注意事项

1. **密钥安全**
   - 密钥是解密数据库的唯一凭证
   - 请妥善保管，不要泄露

2. **数据隐私**
   - 所有数据仅存储在本地 SQLite 数据库
   - 不会上传到任何云端服务

3. **微信版本**
   - 支持微信 4.0 及以上版本
   - 不同版本表结构可能略有差异

4. **性能考虑**
   - 大量数据导入（10万+消息）可能需要数分钟
   - 建议首次导入时设置消息数量限制

5. **扩展性**
   - 当前仅支持文本消息导入
   - 图片/语音/视频等媒体文件预留接口，暂未实现

## 🔧 故障排除

### 密钥验证失败
- 确保密钥格式正确（64位hex字符串）
- 检查微信版本是否支持
- 尝试重新获取密钥

### 未找到数据库
- 确保微信已安装并至少登录过一次
- 检查 `Documents/WeChat Files` 目录是否存在
- 手动检查注册表路径

### 导入失败
- 查看运行日志了解详细错误
- 检查数据库文件是否损坏
- 确保有足够的磁盘空间

## 📚 参考资料

- [EchoTrace 项目](https://github.com/ycccccccy/echotrace) - 微信数据库解析参考
- [wx_key 项目](https://github.com/ycccccccy/wx_key) - 密钥获取工具
- [SQLCipher 文档](https://www.zetetic.net/sqlcipher/) - 数据库加密技术
