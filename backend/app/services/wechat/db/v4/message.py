"""微信 V4 版本 - 消息数据库"""

import sqlite3
import hashlib
import re
import logging
from typing import List, Optional, Tuple, Dict, Set
from ..base import WeChatDBBase
from ...contact_filters import is_excluded_contact_username
from ...content_codec import decode_message_content




logger = logging.getLogger(__name__)
class MessageDBV4(WeChatDBBase):
    """微信 V4 消息数据库访问类
    
    数据库路径: WeChat Files/wxid_xxx/message/message_*.db
    主表: Msg_{MD5(username)}
    辅助表: Name2Id (username <-> rowid 映射)
    """
    
    def __init__(self, db_paths: List[str], db_key: str = None, my_wxid: str = None,
                 raw_keys: dict = None):
        """
        初始化消息数据库(可能有多个分片)

        Args:
            db_paths: message_*.db 文件路径列表
            db_key: 数据库密钥(如果需要解密)
            my_wxid: 当前用户wxid(用于判断is_sender)
            raw_keys: Windows 只读扫描产物 {salt_hex: enc_key_hex}（可选）
        """
        self.db_paths = db_paths if isinstance(db_paths, list) else [db_paths]
        self.db_key = db_key
        self.raw_keys = raw_keys
        self.my_wxid = my_wxid
        self._my_wxid_candidates = self._build_my_wxid_candidates(my_wxid)
        self.connections = []
        self._table_columns_cache: Dict[str, Set[str]] = {}
        # 分片级读取缺口收集（密钥验证失败/页面解密失败/Name2Id 读取失败）。
        # 此类失败不抛异常打断整段导入，但必须让上层（ingest 水位护栏）
        # 感知：缺口会话的消息未落库，水位推进越过即永久丢失（W4）
        self.read_errors: List[str] = []
        self._connect_all()
        self._shard_msg_tables = self._load_shard_msg_tables()

    def _load_shard_msg_tables(self) -> List[Optional[Set[str]]]:
        """每分片的 Msg_ 表名集合（表定位预映射）。

        此前 get_messages 对每个 username 逐分片试查、表不存在抛
        OperationalError 才跳下一个——两千会话 × 十几分片产生数万次
        失败查询。连接后一次 sqlite_master 扫描建立映射，消息查询
        只落表所在分片；单分片扫描失败置 None 回退逐分片试查语义。
        """
        shard_tables: List[Optional[Set[str]]] = []
        for conn in self.connections:
            try:
                shard_tables.append({
                    row["name"] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                    )
                })
            except Exception as exc:
                logger.warning("[消息读取] 分片表清单扫描失败，回退逐分片试查: %s", exc)
                shard_tables.append(None)
        return shard_tables

    
    def _build_my_wxid_candidates(self, wxid: Optional[str]) -> List[str]:
        """生成 my_wxid 可能的别名列表，处理目录名带后缀的情况"""
        candidates: List[str] = []
        if not wxid:
            return candidates
        candidates.append(wxid)
        # 兼容目录名带后缀：wxid_xxx_9cc7 或自定义微信号_86f8——后缀是本地
        # 多开消歧用的，name2id 里存的是无后缀真名（Linux 实测确认）
        m = re.match(r"^(.+)_([0-9a-zA-Z]{4,6})$", wxid)
        if m and len(m.group(1)) >= 2:
            base = m.group(1)
            if base not in candidates:
                candidates.append(base)
        return candidates

    def _connect_all(self):


        """连接所有数据库分片"""
        import os
        import tempfile

        self.temp_db_paths = []  # 存储临时文件路径
        # 回退全量解密的明文库目录：mkdtemp 0700——此前 tempfile.mktemp
        # 落在共享 /tmp 且文件 0644，导入期间任意本地用户可读全部明文
        # 聊天记录（进程崩溃时永久残留），mktemp 本身还有 TOCTOU 竞态
        self._temp_dir: str | None = None

        try:
            for idx, db_path in enumerate(self.db_paths):
                logger.debug(f"[DEBUG MessageDB] 连接数据库 {idx+1}/{len(self.db_paths)}: {db_path}")

                if self.db_key:
                    # 优先走共享增量快照（首次全量≈原路径，后续增量秒级）
                    snapshot_ok = False
                    try:
                        from ...snapshot_manager import get_snapshot_manager
                        decrypted = get_snapshot_manager().get_decrypted_path(
                            db_path, self.db_key, raw_keys=self.raw_keys
                        )
                        if decrypted and decrypted.exists():
                            conn = sqlite3.connect(str(decrypted))
                            conn.row_factory = sqlite3.Row
                            self.temp_db_paths.append(None)  # 占位：共享快照不归本实例清理
                            snapshot_ok = True
                            logger.info("[DEBUG MessageDB] ✅ 使用共享增量快照: %s", decrypted)
                    except Exception as snap_e:
                        logger.warning("[DEBUG MessageDB] 共享快照不可用，回退全量: %s", snap_e)
                    if snapshot_ok:
                        self.connections.append(conn)
                        continue

                    # 原路径：全量解密到临时文件（首次或快照失败时的兜底）
                    # 使用新的纯Python解密器
                    from ...db_decryptor_v2 import WeChatDBDecryptorV2
                    decryptor = WeChatDBDecryptorV2()
                    if self.raw_keys:
                        decryptor.set_raw_key_map(self.raw_keys)

                    # 验证密钥
                    if not decryptor.verify_key_from_file(db_path, self.db_key):
                        logger.error(f"[WARN] 跳过: 密钥验证失败 {db_path}")
                        # 整分片缺席必须留痕（W4）：就地 continue 上层无感知，
                        # 该分片全部会话静默缺失而水位照样推进
                        self.read_errors.append(f"分片#{idx} 密钥验证失败: {db_path}")
                        continue

                    logger.info("[DEBUG MessageDB] ✅ 密钥验证成功")

                    # 解密到临时文件（私有 0700 目录内，见 __init__ 注释）
                    if self._temp_dir is None:
                        self._temp_dir = tempfile.mkdtemp(prefix="chrono-msg-")
                    temp_path = os.path.join(self._temp_dir, f"message_{idx}.db")
                    self.temp_db_paths.append(temp_path)

                    logger.debug(f"[DEBUG MessageDB] 解密到: {temp_path}")
                    decryptor.decrypt_database(db_path, temp_path, self.db_key)
                    logger.info("[DEBUG MessageDB] ✅ 解密完成")

                    # 连接解密后的数据库
                    conn = sqlite3.connect(temp_path)
                    conn.row_factory = sqlite3.Row
                else:
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row

                self.connections.append(conn)
        except Exception:
            # 构造中途失败也必须清理已解密的明文临时库，避免全量聊天记录
            # 残留在 %TEMP%（W2：close() 可达性）
            self.close()
            raise
    
    def _get_table_columns(self, conn: sqlite3.Connection, table_name: str) -> Set[str]:
        """获取指定表的列名集合（缓存）"""
        cache_key = f"{id(conn)}::{table_name}"
        if cache_key in self._table_columns_cache:
            return self._table_columns_cache[cache_key]

        cols: Set[str] = set()
        try:
            cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
            for row in cursor:
                # row[1] 是列名
                cols.add(str(row[1]).lower())
        except Exception as e:
            logger.error(f"[MessageDB Warning] 获取表结构失败 {table_name}: {e}")

        self._table_columns_cache[cache_key] = cols
        return cols
    
    def get_table_name(self, username: str) -> str:

        """
        生成消息表名
        
        规则: Msg_{MD5(username)}
        
        Args:
            username: 对话对象的 wxid
            
        Returns:
            str: 表名 (如 Msg_5d41402abc4b2a76b9719d911017c592)
            
        示例:
            username = "wxid_abc123"
            -> MD5 = "5d41402abc4b2a76b9719d911017c592"
            -> table_name = "Msg_5d41402abc4b2a76b9719d911017c592"
        """
        md5_hash = hashlib.md5(username.encode('utf-8')).hexdigest()
        return f"Msg_{md5_hash}"
    
    def get_messages(
        self,
        username: str,
        time_range: Optional[Tuple[int, int]] = None,
        limit: Optional[int] = None
    ) -> List[dict]:
        """
        获取指定用户的消息记录
        
        Args:
            username: 对话对象username
            time_range: 时间范围 (start_timestamp, end_timestamp)
            limit: 限制数量
            
        Returns:
            List[dict]: 消息列表
        """
        table_name = self.get_table_name(username)
        messages = []

        # 在所有数据库分片中查找（预映射命中才查，映射缺失的分片回退试查）
        for shard_idx, conn in enumerate(self.connections):
            shard_tables = self._shard_msg_tables[shard_idx]
            if shard_tables is not None and table_name not in shard_tables:
                continue
            try:
                msgs = self._query_messages_from_db(
                    conn, table_name, username, time_range, limit
                )
                messages.extend(msgs)
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    # 表不存在（预映射缺失的分片回退试查），尝试下一个数据库
                    continue
                # 其余运行时错误（锁/磁盘满/I/O）：与 DatabaseError 同道记录
                # 缺口——此前一律按表不存在吞掉，ingest 无感知推进水位，
                # 缺口消息被增量永久跳过（绕过 W4 护栏）
                logger.error(
                    "[消息读取] 分片 #%d 读取 %s 失败: %s",
                    shard_idx, table_name, e,
                )
                self.read_errors.append(
                    f"分片#{shard_idx} 读取 {username} 失败: {e}"
                )
                continue
            except sqlite3.DatabaseError as e:
                # 分片含无法解密的页面（解密时已重试并告警）：记录后继续其余分片，
                # 不再让整段会话被上层静默跳过（W3）；缺口同时进 read_errors，
                # ingest 据此冻结水位（W4）——否则缺口消息被后续增量永久跳过
                logger.error(
                    "[消息读取] 分片 #%d 读取 %s 失败（页面解密缺口？）: %s",
                    shard_idx, table_name, e,
                )
                self.read_errors.append(
                    f"分片#{shard_idx} 读取 {username} 失败: {e}"
                )
                continue
        
        # 按时间排序
        messages.sort(key=lambda m: m['timestamp'])
        
        # 应用限制
        if limit and len(messages) > limit:
            messages = messages[:limit]
        
        return messages
    
    def _query_messages_from_db(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        username: str,
        time_range: Optional[Tuple[int, int]],
        limit: Optional[int]
    ) -> List[dict]:
        """
        从单个数据库查询消息
        
        核心SQL逻辑:
        - 优先使用微信原始表 isSend/is_sender 字段判定本人发送
        - 回退 Name2Id 表获取发送者 username 判定
        - 通过 create_time 过滤时间范围
        - 按 sort_seq 排序
        """
        # 检查可用列
        cols = self._get_table_columns(conn, table_name)
        has = lambda name: name.lower() in cols

        # 选择可用的 isSend 字段（支持多别名，使用 COALESCE 统一）
        candidate_cols = []
        for name in [
            "isSend",
            "is_send",
            "is_sender",
            "is_sender_",
            "is_send_",
            "computed_is_send",
            "issender",
        ]:
            if has(name):
                candidate_cols.append(name)

        is_send_select = "NULL AS is_send_flag"
        if candidate_cols:
            joined = ", ".join([f"msg.{col}" for col in candidate_cols])
            is_send_select = f"COALESCE({joined}) AS is_send_flag"


        # 解析 my_wxid 在当前库的 rowid（支持别名）
        my_rowid: Optional[int] = None
        if self._my_wxid_candidates:
            placeholders = ",".join(["?"] * len(self._my_wxid_candidates))
            try:
                cur = conn.execute(
                    f"SELECT rowid FROM Name2Id WHERE user_name IN ({placeholders}) LIMIT 1",
                    self._my_wxid_candidates,
                )
                row = cur.fetchone()
                if row and 'rowid' in row.keys():
                    my_rowid = row['rowid']
            except Exception:
                my_rowid = None

        # 构建SQL（加入 computed_is_send 以回退 Name2Id rowid 比对）
        sql = f"""
            SELECT
                msg.local_id,
                msg.server_id,
                msg.local_type,
                msg.sort_seq,
                msg.real_sender_id,
                msg.create_time,
                msg.message_content,
                msg.compress_content,
                {is_send_select},
                CASE
                    WHEN ? IS NOT NULL THEN (
                        CASE WHEN msg.real_sender_id = ? THEN 1 ELSE 0 END
                    )
                    ELSE NULL
                END AS computed_is_send,
                Name2Id.user_name AS sender_username
            FROM {table_name} AS msg
            LEFT JOIN Name2Id ON msg.real_sender_id = Name2Id.rowid
        """
        
        # 添加时间过滤
        conditions = []
        params = []
        
        # computed_is_send 依赖 my_rowid，占用前两个参数
        params.extend([my_rowid, my_rowid])

        
        if time_range:
            start_ts, end_ts = time_range
            conditions.append("msg.create_time >= ?")
            conditions.append("msg.create_time <= ?")
            params.extend([start_ts, end_ts])
        
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY msg.sort_seq ASC"
        
        if limit:
            sql += f" LIMIT {limit}"

        
        # 执行查询
        cursor = conn.execute(sql, params)
        messages = []
        
        for row in cursor:
            sender_username = row['sender_username'] or ''
            raw_flag = row['is_send_flag']
            computed_raw = row['computed_is_send']

            def _normalize_flag(value: Optional[object]) -> Optional[int]:
                if value is None:
                    return None
                if isinstance(value, bool):
                    return 1 if value else 0
                try:
                    return int(value)
                except Exception:
                    return None

            is_send_flag: Optional[int] = _normalize_flag(raw_flag)
            computed_flag: Optional[int] = _normalize_flag(computed_raw)

            # 判定本人发送优先级：isSend 标记 > computed_is_send (real_sender_id 对比) > Name2Id username 比对 > 简单回退
            if is_send_flag is not None:
                is_sender = is_send_flag != 0
            elif computed_flag is not None:
                is_sender = computed_flag != 0
            elif sender_username:
                if self._my_wxid_candidates:
                    is_sender = sender_username in self._my_wxid_candidates
                elif self.my_wxid:
                    is_sender = (sender_username == self.my_wxid)
                else:
                    # 无 my_wxid 时，若发送者不是对话对象，推断为本人
                    is_sender = (sender_username != username)
            else:
                # 无法判定，保守为接收
                is_sender = False


            # 调试：仅记录第一条消息的判断信息
            if len(messages) == 0:
                logger.debug(
                    f"[MessageDB] 首条消息: real_sender_id={row['real_sender_id']}, "
                    f"sender_username='{sender_username}', is_send_flag={raw_flag}, "
                    f"computed_is_send={computed_raw}, my_wxid='{self.my_wxid}', is_sender={is_sender}"
                )



            # 提取内容：BLOB/zstd 压缩与乱码统一走 content_codec 归一（占位符），
            # 不再 str(bytes) 产出 b'(\xb5...' 式 repr 乱码入库
            message_type = int(row['local_type'] or 1) & 0xFFFFFFFF  # 去 flag 高位
            content = decode_message_content(
                row['message_content'] or row['compress_content'], message_type
            )

            message = {
                'local_id': row['local_id'],
                'talker': username,
                'sender': sender_username,
                'is_sender': 1 if is_sender else 0,
                'message_type': message_type,
                'content': content,
                'timestamp': row['create_time'],
                'media_path': None
            }

            messages.append(message)

        return messages

    def get_all_conversation_usernames(self, include_chatroom: bool = False) -> List[str]:
        """
        获取所有对话的username列表（include_chatroom=True 放行群聊，导入链路用）
        
        Returns:
            List[str]: username列表(不包括群聊和公众号)
        """
        usernames = set()
        
        for shard_idx, conn in enumerate(self.connections):
            try:
                cursor = conn.execute("SELECT user_name FROM Name2Id")
                for row in cursor:
                    username = row['user_name']
                    if username and not is_excluded_contact_username(
                        username, exclude_chatroom=not include_chatroom
                    ):
                        usernames.add(username)
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    # 无 Name2Id 表的结构变体分片：与 get_messages 同款良性
                    # 豁免——记缺口会触发 ingest 水位冻结，每次「增量」导入
                    # 都从陈旧水位全窗重扫
                    continue
                logger.error(
                    "[消息读取] 分片 #%d 读取 Name2Id 失败: %s", shard_idx, e
                )
                self.read_errors.append(
                    f"分片#{shard_idx} 读取会话清单失败: {e}"
                )
                continue
            except sqlite3.DatabaseError as e:
                # 分片会话清单读失败：该分片全部会话缺席，必须留痕（W4）
                logger.error(
                    "[消息读取] 分片 #%d 读取 Name2Id 失败: %s", shard_idx, e
                )
                self.read_errors.append(
                    f"分片#{shard_idx} 读取会话清单失败: {e}"
                )
                continue
        
        return list(usernames)
    
    def get_all_message_tables(self) -> List[str]:
        """
        获取所有消息表名
        
        Returns:
            List[str]: 表名列表 (如 ['Msg_xxx', 'Msg_yyy'])
        """
        tables = set()
        
        for conn in self.connections:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            )
            for row in cursor:
                tables.add(row['name'])
        
        return list(tables)
    
    def get_contacts(self) -> List[dict]:
        """
        消息数据库不存储联系人信息
        此方法保留以符合基类接口
        """
        return []
    
    def get_contact_by_username(self, username: str) -> Optional[dict]:
        """
        消息数据库不存储联系人信息
        此方法保留以符合基类接口
        """
        return None
    
    def close(self):
        """关闭所有数据库连接"""
        for conn in self.connections:
            if conn:
                conn.close()
        self.connections = []
        
        # 清理临时文件
        if hasattr(self, 'temp_db_paths'):
            import os
            for temp_path in self.temp_db_paths:
                if temp_path is None:
                    continue  # 共享快照不归本实例清理
                try:
                    os.remove(temp_path)
                    logger.debug(f"[DEBUG MessageDB] 已删除临时文件: {temp_path}")
                except Exception as e:
                    logger.error(f"[DEBUG MessageDB] 删除临时文件失败: {e}")
            # 私有目录收尾：文件已删则 rmdir 空目录；非空（残留）保留待重启清理
            temp_dir = getattr(self, "_temp_dir", None)
            if temp_dir:
                try:
                    os.rmdir(temp_dir)
                except OSError:
                    pass
                self._temp_dir = None
