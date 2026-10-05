"""Suggestion generation pipeline.

Extracted from monitor_service.py (step 4D). Trigger event handling,
full-auto suggestion, listen-start suggestion, feedback checking.
Dependencies injected via session_state dict + self attributes.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)
import sys

def _print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(arg) for arg in args) + end
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe_text)
        if kwargs.get("flush", False):
            sys.stdout.flush()


class SuggestionPipelineMixin:
    """Suggestion generation pipeline."""

    def _log_runtime_event(self, event_type: str, payload: dict):
        """
        记录运行时事件到数据库
        
        Args:
            event_type: 事件类型
            payload: 事件数据
        """
        try:
            import json
            from ...db.connection import get_db
            
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO runtime_events (event_type, payload_json, created_at)
                VALUES (?, ?, ?)
            ''', (event_type, json.dumps(payload, ensure_ascii=False), int(time.time())))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 记录运行时事件失败: {e}")

    def _handle_trigger_events(self, triggers, session_state: dict | None = None):
        """
        处理触发事件：根据触发模式决定是否生成建议并存入数据库
        
        Args:
            triggers: TriggerEvent 列表
        """
        session_state = session_state or self._build_session_state(self._monitor_session_token)
        if not self._session_is_current(session_state):
            return

        mode = self._suggestion_config.get('trigger_mode', 'semi_auto')
        
        if mode == 'manual':
            # 纯手动模式不自动生成建议，只打印日志
            for trigger in triggers:
                _print(f"📊 [手动模式] 检测到触发: {trigger.trigger_type} (已忽略)")
            return
        
        intent = self._suggestion_config.get('intent', 'maintain')
        batch_id = session_state.get('batch_id')
        display_name = session_state.get('display_name')
        account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
        
        for trigger in triggers:
            try:
                if not self._session_is_current(session_state):
                    return
                # 开场建议后的冷却窗:silence 触发通常源于监听启动前的旧静默
                # 基线,与开场建议内容重复,直接跳过。
                if (
                    trigger.trigger_type == 'silence'
                    and time.time() - getattr(self, '_listen_start_suggestion_at', 0) < 60
                ):
                    _print("🔕 [开场冷却] 跳过与开场建议重复的 silence 触发")
                    continue
                _print(f"🔔 触发事件: {trigger.trigger_type} (severity={trigger.severity})")
                
                # 构建完整的 context (融合 trigger.context 和 画外特征)
                # G1:所有入口统一走 assemble_generation_context,绑定稳定联系人范围。
                ctx = trigger.context.copy() if trigger.context else {}

                try:
                    from .generation_context import assemble_generation_context
                    assemble_generation_context(
                        ctx,
                        entrypoint='semi_auto_trigger',
                        account_wxid=account_wxid,
                        display_name=str(display_name or ''),
                        username=str(session_state.get('talker_username') or ''),
                        batch_id=str(batch_id or ''),
                        emotion_summary=(
                            self.emotion_tracker.get_emotion_summary() if self.emotion_tracker else None
                        ),
                        recent_limit=50,
                        renew_stale_profiles=_renew_profiles_in_background,
                    )
                except Exception as assemble_e:
                    _print(f"⚠️ 统一上下文装配失败,退回最小上下文: {assemble_e}")
                    ctx['display_name'] = display_name
                    ctx['account_wxid'] = account_wxid

                # 生成建议
                from .suggestion_engine import SuggestionEngineFactory
                engine_type = self._suggestion_config.get('engine_type', 'llm')
                engine = SuggestionEngineFactory.create(engine_type)
                result = engine.generate(
                    trigger.trigger_type, intent, ctx
                )
                if not self._session_is_current(session_state):
                    _print("[RealtimeMonitorService] 已忽略过期会话的建议结果")
                    return
                
                # 存入数据库
                self._save_suggestion_to_db(trigger, result, session_state=session_state)
                _print(f"💡 建议已生成: {result.summary}")
                
            except Exception as e:
                _print(f"⚠️ 生成建议失败: {e}")

    def _select_full_auto_trigger(self, runtime_triggers=None):
        """为 full_auto 模式选择一个合适的触发类型。"""
        from .trigger_resolver import resolve_suggestion_trigger

        resolved = resolve_suggestion_trigger(
            mode='full_auto',
            runtime_triggers=runtime_triggers,
            emotion_tracker=self.emotion_tracker,
        )
        return resolved.trigger_type, resolved.trigger_context

    def _handle_full_auto_suggestion(self, sentiment_result, runtime_triggers=None, session_state: dict | None = None):
        """
        全自动模式：每条对方消息都生成建议（受频率限制）
        """
        session_state = session_state or self._build_session_state(self._monitor_session_token)
        if not self._session_is_current(session_state):
            return

        now = time.time()
        rate_limit = self._suggestion_config.get('auto_rate_limit', 10)
        
        if now - self._last_auto_suggestion_time < rate_limit:
            return  # 频率限制内，跳过
        
        try:
            intent = self._suggestion_config.get('intent', 'maintain')
            account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))

            trigger_type, trigger_context = self._select_full_auto_trigger(runtime_triggers)
            if not trigger_type:
                _print("📭 [全自动] 当前消息未命中触发，且趋势不足以支撑建议，已跳过")
                return

            self._last_auto_suggestion_time = now
            
            from .suggestion_engine import SuggestionEngineFactory
            from .emotion_state_tracker import TriggerEvent
            engine = SuggestionEngineFactory.create(
                self._suggestion_config.get('engine_type', 'llm')
            )
            
            ctx = self._build_llm_suggestion_context(
                session_state, mode='full_auto', trigger_context=trigger_context,
            )

            result = engine.generate(trigger_type, intent, ctx)
            if not self._session_is_current(session_state):
                _print("[RealtimeMonitorService] 已忽略过期会话的全自动建议结果")
                return
            
            trigger = TriggerEvent(
                trigger_type=trigger_type,
                timestamp=now,
                severity='low',
                context=ctx.get('trigger_context', {'mode': 'full_auto'})
            )
            self._save_suggestion_to_db(trigger, result, session_state=session_state)
            _print(f"💡 [全自动] 建议已生成: {result.summary}")
            
        except Exception as e:
            _print(f"⚠️ [全自动] 生成建议失败: {e}")

    def _build_llm_suggestion_context(self, session_state, mode, trigger_context=None,
                                       recent_limit=50) -> dict:
        """构建建议生成上下文（最近消息/双方画像/历史增强/RAG 记忆）——全自动与开场建议共用。"""
        account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
        ctx = {'mode': mode}
        if trigger_context:
            ctx['trigger_context'] = {**trigger_context, 'mode': mode}
        # G1:统一装配函数,绑定稳定联系人范围;范围缺失时安全降级。
        try:
            from .generation_context import assemble_generation_context
            assemble_generation_context(
                ctx,
                entrypoint=str(mode or 'auto'),
                account_wxid=account_wxid,
                display_name=str(session_state.get('display_name') or ''),
                username=str(session_state.get('talker_username') or ''),
                batch_id=str(session_state.get('batch_id') or ''),
                emotion_summary=(
                    self.emotion_tracker.get_emotion_summary() if self.emotion_tracker else None
                ),
                recent_limit=recent_limit,
                renew_stale_profiles=_renew_profiles_in_background,
            )
        except Exception as assemble_e:
            _print(f"⚠️ 统一上下文装配失败,退回最小上下文: {assemble_e}")
            if session_state.get('display_name'):
                ctx['display_name'] = session_state['display_name']
                ctx['account_wxid'] = account_wxid
        return ctx

    def _generate_listen_start_suggestion(self, session_state: dict | None = None) -> None:
        """开场建议：监听就绪后基于窗口内最近消息立即生成一次（此前面板空到首条新消息）。"""
        session_state = session_state or self._build_session_state(self._monitor_session_token)
        if not self._session_is_current(session_state):
            return
        if self._suggestion_config.get('trigger_mode', 'semi_auto') == 'manual':
            return  # 纯手动模式：用户已选择不自动生成
        try:
            ctx = self._build_llm_suggestion_context(
                session_state, mode='listen_start', recent_limit=12,
                trigger_context={'source': 'listen_start', 'note': '基于最近对话生成的开场建议'},
            )
            if len(ctx.get('recent_messages') or []) < 4:
                # 基线消息不落 buffer——回退到基线暂存的窗口尾部
                tail = session_state.get('baseline_tail') or []
                if len(tail) >= 4:
                    ctx['recent_messages'] = tail
                else:
                    _print("💭 最近消息不足 4 条，跳过开场建议")
                    return
            intent = self._suggestion_config.get('intent', 'maintain')
            from .emotion_state_tracker import TriggerEvent
            from .suggestion_engine import SuggestionEngineFactory
            engine = SuggestionEngineFactory.create(
                self._suggestion_config.get('engine_type', 'llm')
            )
            result = engine.generate('manual_request', intent, ctx)
            if not self._session_is_current(session_state):
                _print("[RealtimeMonitorService] 已忽略过期会话的开场建议结果")
                return
            trigger = TriggerEvent(
                trigger_type='manual_request',
                timestamp=time.time(),
                severity='low',
                context=ctx.get('trigger_context', {'source': 'listen_start'}),
            )
            self._save_suggestion_to_db(trigger, result, session_state=session_state)
            # 开场建议已覆盖"当前该说什么";短时间内跳过 silence 类自动触发,
            # 避免监听刚启动就同时弹出"开场建议+体面降温"两条重复卡片。
            self._listen_start_suggestion_at = time.time()
            _print("💡 [开场] 基于最近对话的建议已生成(60s 内抑制 silence 自动触发)")
        except Exception as e:
            _print(f"⚠️ [开场] 生成建议失败: {e}")

    def _save_suggestion_to_db(self, trigger, result, session_state: dict | None = None):
        """
        将建议存入 realtime_suggestions 表
        """
        try:
            session_state = session_state or self._build_session_state(self._monitor_session_token)
            batch_id = session_state.get('batch_id')
            if not batch_id:
                return

            from ...db.connection import get_db
            
            conn = get_db()
            
            # 确保表存在
            conn.execute('''
                CREATE TABLE IF NOT EXISTS realtime_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_wxid TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    severity TEXT DEFAULT 'medium',
                    summary TEXT NOT NULL,
                    speeches TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'pending',
                    engine_type TEXT DEFAULT 'llm',
                    trigger_context TEXT,
                    created_at INTEGER NOT NULL,
                    read_at INTEGER,
                    dismissed_at INTEGER,
                    reply TEXT,
                    thought_process TEXT
                )
            ''')
            try:
                conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN reply TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN thought_process TEXT")
            except:
                pass
            
            cursor = conn.cursor()
            account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
            cursor.execute('''
                INSERT INTO realtime_suggestions
                (account_wxid, batch_id, trigger_type, intent, severity, summary, speeches,
                 confidence, status, engine_type, trigger_context, created_at, reply, thought_process)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account_wxid,
                batch_id,
                result.trigger_type,
                result.intent,
                result.severity,
                result.summary,
                json.dumps(result.speeches, ensure_ascii=False),
                result.confidence,
                'attribution_window',
                self._suggestion_config.get('engine_type', 'llm'),
                json.dumps(trigger.context, ensure_ascii=False) if trigger.context else None,
                int(time.time()),
                getattr(result, 'reply', None),
                getattr(result, 'thought_process', None)
            ))
            suggestion_id = cursor.lastrowid
            try:
                rag_log_id = getattr(result, 'rag_log_id', None)
                if rag_log_id:
                    from .rag.context_builder import RagContextBuilder

                    RagContextBuilder().attach_log_to_suggestion(rag_log_id, suggestion_id)
            except Exception as rag_log_e:
                _print(f"⚠️ RAG 检索日志关联建议失败: {rag_log_e}")
            try:
                from .feedback_attribution import SuggestionFeedbackAttributor
                from ...db.connection import get_db as _get_db

                SuggestionFeedbackAttributor.schedule_check(_get_db, suggestion_id)
            except Exception as attr_schedule_e:
                _print(f"⚠️ 反馈归因窗口调度失败: {attr_schedule_e}")
            try:
                from .suggestion_observer import EVENT_SHOWN, record_observation

                record_observation(
                    conn,
                    suggestion_id=suggestion_id,
                    account_wxid=account_wxid,
                    event_type=EVENT_SHOWN,
                    batch_id=batch_id,
                    display_name=session_state.get('display_name'),
                    trigger_type=result.trigger_type,
                )
            except Exception as obs_e:
                _print(f"⚠️ 建议观察记录失败: {obs_e}")
            conn.commit()
            
        except Exception as e:
            _print(f"⚠️ 保存建议到数据库失败: {e}")

    def _check_feedback(
        self,
        user_message: str,
        session_state: dict | None = None,
        user_message_type: int | str | None = None,
    ):
        """
        隐式反馈：将用户实际发送的消息与最近的 AI 建议进行对比，
        提取调教规则。
        """
        try:
            session_state = session_state or self._build_session_state(self._monitor_session_token)
            if not self._session_is_current(session_state):
                return

            batch_id = session_state.get('batch_id')
            display_name = session_state.get('display_name') or ''
            account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
            if not batch_id:
                return

            from ...db.connection import get_db
            conn = get_db()

            # 查询归因窗口内尚未完成反馈的建议。不能把下一条消息直接当作最终反馈。
            cutoff = int(time.time()) - 600
            cursor = conn.execute('''
                SELECT id, speeches FROM realtime_suggestions
                WHERE account_wxid = ? AND batch_id = ?
                  AND status IN ('pending', 'displayed', 'attribution_window')
                  AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
            ''', (account_wxid, batch_id, cutoff))

            row = cursor.fetchone()
            if not row:
                return  # 没有待处理建议，跳过

            suggestion_id = row['id']
            speeches = json.loads(row['speeches'])
            reserve = conn.execute(
                '''
                UPDATE realtime_suggestions
                SET status = 'feedback_processing'
                WHERE account_wxid = ? AND id = ?
                  AND status IN ('pending', 'displayed', 'attribution_window')
                ''',
                (account_wxid, suggestion_id)
            )
            conn.commit()
            if reserve.rowcount != 1:
                return

            _print(f"\ud83d\udd0d [反馈归因] 检测到用户发消息，进入归因窗口 (id={suggestion_id})")

            # 调用规则提取器
            from .feedback_rule_extractor import FeedbackRuleExtractor
            extractor = FeedbackRuleExtractor()
            captured_user_message = str(user_message or '')
            captured_display_name = str(display_name or '')

            # 在后台线程中执行（避免阻塞消息轮询）
            import threading
            def do_extract():
                try:
                    from .feedback_attribution import SuggestionFeedbackAttributor

                    try:
                        attr = SuggestionFeedbackAttributor(get_db()).attribute(
                            suggestion_id=suggestion_id,
                            allow_pending=True,
                        )
                    except Exception as attr_e:
                        _print(f"⚠️ [反馈归因] 窗口归因不可用，使用旧兼容路径: {attr_e}")
                        attr = {
                            "pending": False,
                            "attribution_type": "accepted",
                            "confidence": 0.0,
                            "final_message": captured_user_message,
                            "selected_speech": None,
                        }
                    if attr.get("pending"):
                        conn2 = get_db()
                        conn2.execute(
                            "UPDATE realtime_suggestions SET status = 'attribution_window' WHERE account_wxid = ? AND id = ?",
                            (account_wxid, suggestion_id),
                        )
                        conn2.commit()
                        return

                    attribution_type = attr.get("attribution_type")
                    if attribution_type not in {"accepted", "rewritten", "preface_then_reply"}:
                        conn2 = get_db()
                        conn2.execute(
                            "UPDATE realtime_suggestions SET status = 'feedback_collected' WHERE account_wxid = ? AND id = ?",
                            (account_wxid, suggestion_id),
                        )
                        conn2.commit()
                        return

                    feedback_analysis = extractor.analyze_feedback(
                        ai_speeches=speeches,
                        user_actual_message=attr.get("final_message") or captured_user_message,
                        display_name=captured_display_name,
                        suggestion_id=suggestion_id,
                        user_message_type=user_message_type,
                        account_wxid=str(session_state.get('account_wxid') or self.current_account_wxid or ''),
                    )
                    try:
                        from .suggestion_observer import (
                            EVENT_ADOPTED,
                            EVENT_REWRITTEN,
                            record_observation,
                        )

                        outcome = feedback_analysis.get('outcome')
                        if attribution_type in {'accepted', 'preface_then_reply'}:
                            outcome = 'adopted'
                        elif attribution_type == 'rewritten':
                            outcome = 'rewritten'
                        if outcome in {'adopted', 'rewritten'}:
                            record_observation(
                                conn2 := get_db(),
                                suggestion_id=suggestion_id,
                                account_wxid=account_wxid,
                                event_type=EVENT_ADOPTED if outcome == 'adopted' else EVENT_REWRITTEN,
                                similarity=feedback_analysis.get('max_similarity'),
                                selected_speech=attr.get('selected_speech') or feedback_analysis.get('selected_speech'),
                                actual_message=attr.get("final_message") or captured_user_message,
                                actual_message_type=user_message_type,
                                metadata={
                                    'attribution_type': attribution_type,
                                    'attribution_confidence': attr.get('confidence'),
                                    'rule_source': feedback_analysis.get('rule_source'),
                                    'rule_count': len(feedback_analysis.get('rules') or []),
                                },
                            )
                            conn2.commit()
                    except Exception as obs_e:
                        _print(f"⚠️ [隐式反馈] 记录观察事件失败: {obs_e}")

                    extracted_rules = feedback_analysis.get('rules') or []
                    if extracted_rules:
                        _print(
                            "\ud83d\udcdd [隐式反馈] 提取到新规则: "
                            + " / ".join(
                                str(item.get('rule', '')).strip()
                                for item in extracted_rules
                                if str(item.get('rule', '')).strip()
                            )
                        )

                    # 标记建议为已反馈。即使这次没有提取到新规则，也不能卡在 feedback_processing。
                    conn2 = get_db()
                    conn2.execute(
                        "UPDATE realtime_suggestions SET status = 'feedback_collected' WHERE account_wxid = ? AND id = ?",
                        (account_wxid, suggestion_id)
                    )
                    conn2.commit()
                except Exception as e:
                    try:
                        conn2 = get_db()
                        conn2.execute(
                            "UPDATE realtime_suggestions SET status = 'feedback_failed' WHERE account_wxid = ? AND id = ?",
                            (account_wxid, suggestion_id)
                        )
                        conn2.commit()
                    except Exception:
                        pass
                    _print(f"⚠️ [隐式反馈] 提取失败: {e}")

            t = threading.Thread(target=do_extract, daemon=True)
            t.start()

        except Exception as e:
            _print(f"⚠️ [隐式反馈] 检查失败: {e}")

