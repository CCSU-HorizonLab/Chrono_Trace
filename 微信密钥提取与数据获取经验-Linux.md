# 微信密钥提取与数据获取经验（Linux 4.1 实战记录）

> 2026-09-25 实测环境：Linux (Debian 12) / 微信 4.1.x 原生版（module `xwechat_linux`, build 4067692804，当日更新）
> 数据：`~/文档/xwechat_files/lishao378_86f8/`（自定义微信号账号，非 wxid 前缀）
> 结局：**密钥一次捕获，31/31 数据库验证通过，82,218 条消息 45 秒导入成功**
> 本文档不入库，供其它版本/平台适配参考。项目内实现：`backend/app/services/wechat/key_capture_linux.py`

---

## 一、死路清单（按验证顺序，避免重走）

| # | 方案 | 死因 | 关键证据 |
|---|------|------|---------|
| 1 | 复用 Windows wx_key wheel | win_amd64 PE 二进制 + DLL注入机制，Linux 双重不可行 | `packaging/vendor/wx_key-*-win_amd64.whl`；[wx_key 仓库](https://github.com/ycccccccy/wx_key) 明确只支持 Windows |
| 2 | LD_PRELOAD 拦截 sqlite3_key / EVP API | **微信把 SQLite(SQLCipher)+crypto 全部静态编译**，无任何动态符号可拦 | `objdump -T /opt/wechat/wechat` 零命中；`ldd` 无 libcrypto；二进制 strip；`strings` 见 `sqlcipher_export` |
| 3 | 内存扫描 pragma `x'<64hex><64hex><32hex salt>'db` 模式 | 微信 4.0.3.36+ **不再缓存明文密钥**（社区共识）；实测找到锚点但 A/B 段做 raw-key/passphrase/ASCII/XOR/SHA/参数变体全不命中 | 锚点 5 处真实存在（`x'51c380be...15a38cd0...6385ba9d...'db`），但均非密钥 |
| 4 | 内存扫描派生 enc_key（快速校验 ~15µs/候选） | 未命中锚点邻域；全量扫描未跑完即被正确方案取代 | 公式自证正确（derive_keys 输出可反校验）；据此推断派生密钥也被混淆或即时擦除 |
| 5 | PBKDF2 本体断点（SHA512 K表 LEA → 块函数入口，ipad `^0x36` 模式检测器） | 定位到的 K 表版本是**从不被调用的 C 兜底实现**（运行时用 AVX2 变体，且 AVX2 版不 LEA 同一张表——全二进制仅 1 处 K 表 LEA 引用） | 正确地址断点挂 15 分钟零命中（含一次完整重登） |

**方法论教训**：先跑 5 号方案的「断点挂 30 秒看是否被调用」再做重登类用户操作，可以提前排除死路 1-4 的大部分时间。

## 二、成功路径：ELF 锚点 + GDB 断点（参考 wcdb-key-tool，修正其地址换算）

### 2.1 流程

```
① ELF 静态分析（离线，~1 分钟，按二进制 inode 缓存）
   .rodata 找 "com.Tencent.WCDB.Config.Cipher"
   → 找 LEA rsi,[rip+锚点] 且其前 7 字节是 LEA rdi 的引用点
   → 从第二层 LEA 引用点向后扫 ≤0x500 找函数头 prologue（55 41 57）
   → 候选断点 VA（本版本实测：0x87AC370，唯一候选）
② 运行时地址换算（★ 核心坑见 2.2）
③ gdb batch 附加 + 断点（进程监护：见 2.3）
④ 用户触发：微信「退出登录」→ 手机确认重新登录（不是重启应用！）
⑤ 断点命中：读 rsi/rdx（方式1：rsi=ptr, rdx=32）或 *(rsi+8)/*(rsi+16)（方式2）→ 32 字节 passphrase
⑥ passphrase 即 db_key 语义：按各库 salt 做 PBKDF2-HMAC-SHA512(256000) 派生 + page1 HMAC 校验
```

### 2.2 ★ 最贵的坑：地址换算（wcdb-key-tool 的公式在此二进制上错了 4.5MB）

**错误公式**（原工具）：`断点 = 首个r-x映射起始 + 节区VA`

**原因**：该二进制 `.text` 的 **vaddr 从 0x44EC000 起**（前面有 ~70MB 只读段映射在 r--p），首个 r-x 映射对应的不是 vaddr 0，公式整体偏移 `0x44EC000`。**断点插进了错误但合法的代码区**——gdb 不报错、微信不崩溃、就是永远不触发。前 8 轮全败于此。

**正确算法**（程序头感知，伪代码）：
```
1. 解析 ELF PT_LOAD：[(p_offset, p_vaddr, p_memsz), ...]
   本二进制：LOAD off=0x0      vaddr=0x0       (r--)
            LOAD off=0x44EB000 vaddr=0x44EC000 (r-x)   ← 注意 vaddr≠offset，差 0x1000
            LOAD off=0xA670ED0 ...            (rw-)
2. 找包含断点 VA 的 PT_LOAD → 得 (p_offset, p_vaddr)
3. 在 /proc/<pid>/maps 里找 文件偏移 == (p_offset & ~0xFFF) 的映射行 → seg_runtime
4. 断点运行时地址 = seg_runtime + (VA - p_vaddr)
```

**适配检查清单（换版本/平台必做）**：打印 `readelf -l` 的 PT_LOAD 布局；若 r-x 段 vaddr ≠ 该段在 maps 的文件偏移对应关系，必须走上述精确换算。

### 2.3 进程生命周期实测（Linux 4.1）

| 操作 | 进程行为 | 对策 |
|------|---------|------|
| 退出登录→重新登录 | **进程不死**（同一 PID） | 最佳触发窗口，无 pid 切换风险 |
| 完全退出微信→重新打开 | 冷启动有**中间进程替换链**（先起一个进程再被替换，如 2877146→2878530），旧进程残留为**僵尸 Z** | 断点监护循环：① pid 存活判定必须把 Z 视为死（`/proc/<pid>/stat` state==Z）② 进程死→杀 gdb→等新 pid（≥30 秒窗口，用户手动启动慢）→重挂（断点偏移按 inode 缓存复用，免再做 1 分钟 ELF 分析） |
| 二进制热更新 | 运行中进程 exe 变 `(deleted)`，磁盘是新版本 | **一律通过 `/proc/<pid>/exe` 分析真实运行 inode**；maps 匹配容忍 `(deleted)` 后缀 |

### 2.4 gdb 陷阱

- gdb 内嵌 Python 里写 `%` 格式化：脚本模板若经 Python `.format()` 处理，**`%%` 不会被还原**（`.format` 只管 `{}`）——直接写单个 `%`
- `subprocess.run(capture_output)` 全量收尾读取即可；断点处理器要**计数上限自动放弃**（防迭代风暴冻死宿主）
- helper 进程名（wxocr/wxplayer/wxutility/crashpad_handler）与主进程区分：`/proc/<pid>/exe` basename 精确 == `wechat`
- ptrace 权限：`/proc/sys/kernel/yama/ptrace_scope`；=0 同 uid 直接可附加；≠0 需 root 或引导用户改（结构化报错给指引，手动输入密钥永远兜底）

## 三、数据库与消息获取经验（Linux 4.1 实测）

### 3.1 目录与账号识别

- 数据根：`$XDG_DOCUMENTS_DIR/xwechat_files/`（**读 `~/.config/user-dirs.dirs` 解析，勿硬编码 Documents**；本机=`~/文档`）
- 账号目录 = 微信号（**不一定是 wxid_ 前缀**，自定义微信号如 `lishao378_86f8`）+ 可选 `_4~6位hex` 后缀；识别只认 `db_storage/` 子目录结构特征
- 库布局与 Windows 4.x 同构：`db_storage/{contact,message,session,...}/*.db`

### 3.2 SQLCipher 参数（与 Windows 4.x 完全一致）

```
AES-256-CBC + HMAC-SHA512；PBKDF2-HMAC-SHA512 256000 轮
page=4096, salt=首16B, reserve=80(IV16+HMAC64)
单 passphrase 全库通用（31/31 库验证通过）
```
单个 passphrase 校验 ≈193ms（PBKDF2 主导）；若假设候选是**已派生 enc_key**，可 2 轮迭代推 mac_key 后校验，~15µs/候选。

### 3.3 表结构差异（相对 Windows V4 适配层）

| 项 | Windows | Linux 4.1 实测 | 影响 |
|----|---------|---------------|------|
| 消息表 | `Msg_{md5(username)}` | **一致** | 无 |
| 消息表列 | local_id/server_id/local_type/sort_seq/real_sender_id/create_time/message_content/... | **完全一致**（多 WCDB_CT_* 虚拟列，无影响） | 无 |
| 发送者映射 | `Name2Id` | `name2id`（全小写），列 user_name/is_session | **无影响**——SQLite 表名大小写不敏感，实测直接兼容 |
| contact 目录 | 仅 contact.db | **contact.db + contact_fts.db + fmessage_new.db + wa_contact_new.db** | ★ path_finder 取「目录第一个 .db」会随机拿错 → 必须精确名 `contact.db` 优先（session 同理） |
| message 目录 | message_*.db | 另含 media_*.db/biz_message_*.db/message_fts.db/weclaw.db | 多分片查询按缺表跳过，天然兼容 |
| 运行时读取 | 需复制 | **可直接 pread（rw-r--r-- 属主）**，带活跃 -wal/-shm/.material | 实时增量可行：mtime 触发 + WAL 帧合并 |

### 3.4 实测导入结果

45 秒：contacts 1459 / **messages 82,218** / conversations 730 / skipped 33,097（排除账号+类型过滤），ok:true——Windows V4 适配层（MessageDBV4/ContactDBV4 + db_decryptor_v2）在 Linux 数据上**零改动可用**（除 3.3 的库选择与大小写项）。

## 四、其它版本/平台适配检查清单

**新版本微信（Linux）适配流程**：
1. 先跑 ELF 锚点分析（`find_hook_offsets`）——锚点字符串或 LEA 链变化时按 2.1 的特征链重推；参考过的特征实现：[wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)（MIT）
2. 断点挂上后**先空跑 30 秒确认函数会被调用**（避免白耗用户重登）
3. 地址换算永远走 PT_LOAD 精确映射（2.2）
4. 触发动作 = 退出登录→重登；进程监护按 2.3

**macOS 对应**：wcdb-key-tool 有 mac 版（`wcdb_key_tool_macos.py`）；ld 附着 (lldb)、内存布局换算同理（Mach-O segment 而非 PT_LOAD）。

**Windows 对应**：本项目 wx_key hook 方案已覆盖；若 wx_key 失效（停更），本方法论可平移（x64dbg/断点 at WCDB cipher config，地址换算按 PE ImageBase+RVA）。

**密钥生命周期**：passphrase 换登录不换、换设备/重装可能换；建议存 account_settings 的 db_key 字段并在 verify_key 失败时提示重捕。

## 五、相关参考

- [TANGandXUE/wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)（方法论来源，MIT；其地址公式需按 2.2 修正）
- [sjzar/chatlog](https://github.com/sjzar/chatlog)（FAQ 明确 4.0.3.36+ 内存扫描失效的背景）
- [328336690/wechat-decrypt](https://github.com/328336690/wechat-decrypt)（Windows `x'...'` 内存模式——4.1 已失效，但其 mtime+WAL 实时监听设计可参考）
- [jev-chat 系列](https://github.com/jev-chat/jev-chat-jarvis)（截图+OCR 绕开密钥的替代路线：无历史导入能力，但实时链路不依赖任何密钥）
