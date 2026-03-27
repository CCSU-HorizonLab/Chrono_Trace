# Chrono Trace - 安装与配置指南

> 快速开始使用 Chrono Trace 分析微信聊天记录

---

## 📋 系统要求

- **操作系统**: Windows 10/11
- **微信版本**: 4.0+ (支持新版数据库结构)
- **Python**: 3.8+
- **Node.js**: 16+

---

## 🚀 快速安装

### 1. 克隆项目

```bash
git clone <repository-url>
cd Chrono-Trace
```

### 2. 安装Python依赖

```bash
pip install -r requirements.txt
```

**核心依赖**:
- `pycryptodome` - SQLCipher 4数据库解密
- `pywebview` - 桌面应用框架
- `pywinauto` - Windows UI自动化（实时监听）
- `Pillow` - 图像处理
- `snownlp` - 中文情感分析
- `sentence-transformers` - 句子嵌入
- `scikit-learn` - 机器学习
- `torch` - 深度学习框架

### 3. 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 4. 启动应用

**开发模式**:
```bash
python app_dev.py
```

**生产模式**:
```bash
cd frontend
npm run build
cd ..
python app.py
```

应用将在 `http://localhost:5173` 启动。

---

## 🔑 获取微信数据库密钥

### 使用 wx_key 工具

1. 下载工具: https://github.com/ycccccccy/wx_key
2. 运行工具获取64位hex密钥
3. 复制密钥备用

**密钥格式示例**:
```
1a2b3c4d5e6f7890abcdef1234567890abcdef1234567890abcdef1234567890
```

> ⚠️ **注意**: 密钥是64个十六进制字符(32字节)

---

## ⚙️ 配置微信数据路径

### 方式1: 自动检测 (推荐)

应用会自动查找微信数据目录:
1. 注册表路径
2. `C:\Users\<用户名>\xwechat_files` (微信4.0+)
3. 用户文档目录

大多数情况下无需手动配置。

### 方式2: 手动配置

如果自动检测失败:

1. 打开应用,进入"设置"页面
2. 勾选"使用自定义路径"
3. 点击"浏览并扫描"选择微信数据目录
4. 自动填充数据库路径

**微信4.0+数据目录示例**:
```
C:\Users\<用户名>\xwechat_files\wxid_xxx\db_storage\
├── contact/
│   └── contact.db
├── message/
│   ├── message_0.db
│   ├── message_1.db
│   └── ...
└── session/
    └── session.db
```

---

## 📥 导入数据

### 步骤

1. **输入密钥**
   - 在首页输入64位hex密钥
   - 点击"验证并解包"

2. **验证路径**
   - 应用会显示检测到的路径信息
   - 确认数据源正确

3. **开始导入**
   - 点击"开始导入"
   - 等待解密和导入完成 (~30秒 for 50k条消息)

4. **查看结果**
   - 导入成功后显示统计信息
   - 可以开始数据分析

### 预期结果

```
✅ 导入成功!
联系人: 354
消息: 47,698
会话: 245
```

---

## 🔧 常见问题

### Q1: 提示"未找到微信数据目录"

**解决方案**:
1. 确认微信已安装并登录
2. 检查微信版本是否为4.0+
3. 使用手动配置路径

### Q2: 密钥验证失败

**解决方案**:
1. 确认密钥为64位hex字符
2. 重新运行 wx_key 工具获取密钥
3. 确保微信未在运行

### Q3: 导入成功但数据为0

**解决方案**:
1. 检查控制台debug日志
2. 确认数据库文件路径正确
3. 查看 `CHANGELOG.md` 了解已知问题

### Q4: 前端报错 "echarts not found"

**解决方案**:
```bash
cd frontend
npm install echarts
```

---

## 📊 性能优化建议

### 首次导入

- **小数据集** (<10k消息): ~10秒
- **中等数据集** (10k-100k): ~30秒
- **大数据集** (>100k): ~1-2分钟

### 优化技巧

1. **关闭其他程序** - 释放内存
2. **使用SSD** - 加快文件读写
3. **增量导入** - 只导入新消息

---

## 🔐 数据安全

### 本地存储

- 所有数据存储在本地 `backend/data/chrono_trace.db`
- 不上传任何数据到云端
- 密钥仅存储在内存中,不保存到磁盘

### 临时文件

- 解密过程会创建临时文件
- 应用自动清理临时文件
- 位置: `%TEMP%/tmp*.db`

---

## 📚 下一步

- 查看 [Readme.md](../Readme.md) 了解项目概述
- 查看 [DEVELOPMENT.md](DEVELOPMENT.md) 了解开发指南
- 查看 [CHANGELOG.md](../CHANGELOG.md) 了解更新历史

---

**文档版本**: 2.0.0
**最后更新**: 2026-03-27
