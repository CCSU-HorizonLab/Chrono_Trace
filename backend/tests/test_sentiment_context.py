"""情感分类 ctx 口径（v2 学生）的单元测试。

口径单一来源 realtime/sentiment_context：上文拼接/截断/退化行为与
训练脚本 build_samples 同形（改口径要同步改训练并重训）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.sentiment_context import (
    CTX_CHARS,
    CTX_N,
    build_contexts,
    compose_input,
    context_string,
)


class TestContextString:
    def test_join_with_separator(self):
        assert context_string(["早", "吃了吗", "在吗"]) == "早 / 吃了吗 / 在吗"

    def test_takes_last_n_only(self):
        parts = [f"第{i}条" for i in range(6)]
        assert context_string(parts) == " / ".join(parts[-CTX_N:])

    def test_single_newline_flattened(self):
        assert context_string(["第一行\n第二行"]) == "第一行 第二行"

    def test_per_message_truncation(self):
        long = "长" * (CTX_CHARS + 10)
        assert context_string([long]) == "长" * CTX_CHARS

    def test_empty_list_gives_empty_string(self):
        assert context_string([]) == ""


class TestBuildContexts:
    def test_prefix_progression(self):
        ctxs = build_contexts(["a", "b", "c", "d"])
        assert ctxs == ["", "a", "a / b", "a / b / c"]

    def test_aligned_length(self):
        assert len(build_contexts(["x", "y"])) == 2


class TestComposeInput:
    def test_with_context(self):
        assert compose_input("上文", "消息") == "上文 [SEP] 消息"

    def test_empty_context_falls_back_to_plain_text(self):
        assert compose_input("", "消息") == "消息"


class TestModelInputPassthrough:
    """_model_predict_batch 的 ctx 拼接对位（stub 引擎捕获实际输入）。"""

    def _run_batch(self, texts, contexts):
        from threading import Lock

        from app.services.realtime.realtime_sentiment_service import (
            RealtimeSentimentService,
        )

        # @singleton 工厂下模块名不是类本体——经单例实例取真实类，
        # 再以 stub self 直调未绑定方法（绕过重型 __init__）
        cls = type(RealtimeSentimentService())

        class _Engine:
            def __init__(self):
                self.seen = []

            def predict_logits(self, inputs, batch_size=32):
                self.seen.extend(inputs)
                # 任意 3 类 logits
                return [[0.0, 1.0, 0.0]] * len(inputs)

        class _Stub:
            _model = _Engine()
            _lock = Lock()

            @staticmethod
            def _load_model():
                pass

        stub = _Stub()
        cls._model_predict_batch(stub, texts, contexts=contexts)
        return stub._model.seen

    def test_contexts_composed_in_order(self):
        seen = self._run_batch(
            ["好消息", "坏消息"], ["早 / 吃了吗", ""]
        )
        assert seen == ["早 / 吃了吗 [SEP] 好消息", "坏消息"]

    def test_none_contexts_pass_texts_through(self):
        seen = self._run_batch(["纯文本"], None)
        assert seen == ["纯文本"]

    def test_shorter_contexts_pad_with_none(self):
        seen = self._run_batch(["一", "二"], ["上文"])
        assert seen == ["上文 [SEP] 一", "二"]
