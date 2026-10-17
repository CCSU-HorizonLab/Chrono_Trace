"""中文词云生成器（基于jieba分词）"""
from .stopwords import CHAT_STOP_WORDS
from typing import List, Dict, Any
from collections import Counter
import logging


logger = logging.getLogger(__name__)
class WordCloudGenerator:
    """中文词云生成器"""
    
    def __init__(self):
        self.stopwords = self._load_stopwords()
    
    def _load_stopwords(self) -> set:
        """加载停用词表（单一来源 stopwords.CHAT_STOP_WORDS）"""
        return set(CHAT_STOP_WORDS)
    
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
            import jieba
        except ImportError:
            logger.error("[ERROR] jieba未安装，请执行: pip install jieba")
            return []
        
        if not texts:
            return []
        
        # 1. 转换bytes为str、过滤emoji并合并所有文本
        import re
        
        text_list = []
        for t in texts:
            # 转换bytes为str
            if isinstance(t, bytes):
                try:
                    t = t.decode('utf-8')
                except Exception:
                    continue
            elif not isinstance(t, str):
                continue
            
            # 过滤 [emoji] 格式，如 [旺柴]、[笑脸] 等
            t = re.sub(r'\[.*?\]', ' ', t)
            
            # 过滤多个空格
            t = re.sub(r'\s+', ' ', t).strip()
            
            if t:
                text_list.append(t)
        
        if not text_list:
            return []
        
        all_text = ' '.join(text_list)
        
        # 2. jieba分词
        words = jieba.cut(all_text)
        
        # 3. 过滤
        filtered_words = []
        for w in words:
            w = w.strip()
            # 至少2个字符
            if len(w) < 2:
                continue
            # 不在停用词表
            if w in self.stopwords:
                continue
            # 不是纯数字
            if w.isdigit():
                continue
            # 不是纯标点
            if self._is_punctuation(w):
                continue
            # 不是纯空白
            if not w or w.isspace():
                continue
            # 过滤重复字符（如"哈哈哈"、"嘿嘿嘿"）
            if self._is_repeated_char(w):
                continue
            
            filtered_words.append(w)
        
        # 4. 统计词频
        word_freq = Counter(filtered_words)
        
        # 5. 取Top N
        top_words = word_freq.most_common(top_n)
        
        if not top_words:
            return []
        
        # 6. 归一化权重到 1-100
        max_freq = top_words[0][1]
        min_freq = top_words[-1][1]
        freq_range = max_freq - min_freq if max_freq != min_freq else 1
        
        result = []
        for word, freq in top_words:
            # 归一化到 1-100
            weight = int(((freq - min_freq) / freq_range) * 99 + 1)
            result.append({"word": word, "weight": weight})
        
        return result
    
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
