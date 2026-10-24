"""中文词云生成器（jieba.posseg 分词 + 词性白名单）"""
from .stopwords import CHAT_STOP_WORDS, CONTENT_POS_TAGS
from typing import List, Dict, Any, Tuple
from collections import Counter
import logging
import re


logger = logging.getLogger(__name__)

# 方括号表情占位过滤（[旺柴]、[笑脸] 等）——与消息清洗口径无耦合，
# 词云层独立兜底 raw 口径文本
_EMOJI_PLACEHOLDER = re.compile(r'\[.*?\]')
_MULTI_SPACE = re.compile(r'\s+')


class WordCloudGenerator:
    """中文词云生成器"""

    def __init__(self):
        self.stopwords = self._load_stopwords()

    def _load_stopwords(self) -> set:
        """加载停用词表（单一来源 stopwords.CHAT_STOP_WORDS）"""
        return set(CHAT_STOP_WORDS)

    @staticmethod
    def _prepare_text(t: Any) -> str:
        """bytes→str、过滤方括号表情、规范空白；不可用文本返回空串。"""
        if isinstance(t, bytes):
            try:
                t = t.decode('utf-8')
            except Exception:
                return ""
        elif not isinstance(t, str):
            return ""
        t = _EMOJI_PLACEHOLDER.sub(' ', t)
        t = _MULTI_SPACE.sub(' ', t).strip()
        return t

    def _accept_word(self, pair) -> str:
        """词性白名单 + 长度/停用词/数字/标点/重复字符过滤，通过返回词否则空串。"""
        w = pair.word.strip()
        # 词性白名单（stopwords.CONTENT_POS_TAGS 单一来源）
        if pair.flag not in CONTENT_POS_TAGS:
            return ""
        # 至少2个字符
        if len(w) < 2:
            return ""
        # 不在停用词表
        if w in self.stopwords:
            return ""
        # 不是纯数字
        if w.isdigit():
            return ""
        # 不是纯标点
        if self._is_punctuation(w):
            return ""
        # 过滤重复字符（如"哈哈哈"、"嘿嘿嘿"）
        if self._is_repeated_char(w):
            return ""
        return w

    def _finalize(self, word_freq: Counter, top_n: int) -> List[Dict[str, Any]]:
        """词频 → 底噪裁剪 + Top N + 权重归一（1-100）。"""
        # 底噪裁剪：语料充足时频次 <3 的尾巴词不入榜（min-max 归一会把
        # 它们压成 weight=1，零区分度还挤占 top 位）；小语料（<300 词）
        # 不裁——短对话本来低频
        min_count = 3 if sum(word_freq.values()) >= 300 else 1
        candidates = [(w, c) for w, c in word_freq.most_common() if c >= min_count]
        top_words = candidates[:top_n]

        if not top_words:
            return []

        max_freq = top_words[0][1]
        min_freq = top_words[-1][1]
        freq_range = max_freq - min_freq if max_freq != min_freq else 1

        return [
            {"word": word, "weight": int(((freq - min_freq) / freq_range) * 99 + 1)}
            for word, freq in top_words
        ]

    def generate(self, texts: List[str], top_n: int = 50) -> List[Dict[str, Any]]:
        """
        生成词云数据

        Args:
            texts: 消息文本列表
            top_n: 返回前N个高频词

        Returns:
            [{"word": "开心", "weight": 25}, ...]
        """
        try:
            import jieba.posseg as pseg
        except ImportError:
            logger.error("[ERROR] jieba未安装，请执行: pip install jieba")
            return []

        text_list = [t for t in (self._prepare_text(t) for t in texts) if t]
        if not text_list:
            return []

        all_text = ' '.join(text_list)

        # jieba 词性分词：白名单只留实词（代词/时间词/副词整类出局）
        word_freq = Counter(
            w for w in (self._accept_word(pair) for pair in pseg.cut(all_text)) if w
        )
        return self._finalize(word_freq, top_n)

    def generate_by_side(
        self,
        pairs: List[Tuple[Any, bool]],
        top_n: int = 30,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """单遍分词同时产出 all/me/other 三口径词云。

        每条文本只切一次，词频按来源侧分别累加——all 恒等于 me+other
        的词频之和（此前三路各拼各的整段语料重切 3 遍，且拼接切词在
        消息边界可能组合出假词，all 与 me+other 也不保证相等）。
        pairs 为 (content, is_me) 列表。
        """
        try:
            import jieba.posseg as pseg
        except ImportError:
            logger.error("[ERROR] jieba未安装，请执行: pip install jieba")
            return {"all": [], "me": [], "other": []}

        counters = {"all": Counter(), "me": Counter(), "other": Counter()}
        for raw, is_me in pairs:
            text = self._prepare_text(raw)
            if not text:
                continue
            side = "me" if is_me else "other"
            for pair in pseg.cut(text):
                w = self._accept_word(pair)
                if not w:
                    continue
                counters["all"][w] += 1
                counters[side][w] += 1

        return {key: self._finalize(counter, top_n) for key, counter in counters.items()}

    def _is_punctuation(self, text: str) -> bool:
        """判断是否为标点符号"""
        import string
        punctuation = string.punctuation + '，。！？、；：""''（）【】《》…—·'
        return all(c in punctuation for c in text)

    def _is_repeated_char(self, text: str) -> bool:
        """判断是否为重复字符（如"哈哈哈"、"嘿嘿嘿"）"""
        if len(text) < 2:
            return False

        # 检查是否所有字符都相同
        if len(set(text)) == 1:
            return True

        # 检查是否为2个字符的重复（如"哈哈"重复成"哈哈哈哈"）
        if len(text) >= 4 and len(text) % 2 == 0:
            half = len(text) // 2
            if text[:half] == text[half:]:
                return True

        return False
