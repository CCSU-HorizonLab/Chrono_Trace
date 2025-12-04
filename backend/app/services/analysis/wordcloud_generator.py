"""中文词云生成器（基于jieba分词）"""
from typing import List, Dict, Any
from collections import Counter


class WordCloudGenerator:
    """中文词云生成器"""
    
    def __init__(self):
        self.stopwords = self._load_stopwords()
    
    def _load_stopwords(self) -> set:
        """加载停用词表"""
        return {
            # 助词
            '的', '了', '吗', '呢', '吧', '啊', '呀', '嘛', '哦', '哈', '呵',
            # 代词
            '我', '你', '他', '她', '它', '这', '那', '哪', '谁', '什么', '怎么',
            # 连词/介词
            '在', '和', '跟', '与', '及', '以', '为', '对', '把', '被', '从', '向',
            # 常见无意义词
            '就', '都', '要', '会', '能', '可以', '没有', '不是', '还是', '如果',
            '但是', '因为', '所以', '然后', '而且', '或者', '虽然', '不过',
            # 标点
            '，', '。', '！', '？', '、', '；', '：', '"', '"', ''', ''', '（', '）',
            ',', '.', '!', '?', ';', ':', '"', "'", '(', ')', '[', ']', '{', '}',
            # 单字常用词
            '是', '有', '到', '去', '来', '说', '做', '看', '让', '给', '把', '被',
            '着', '过', '得', '地', '吧', '啦', '啊', '呀', '哦', '嗯', '哼', '嘿',
            # 表情文字
            'emoji', 'Emoji', 'EMOJI',
            # 其他
            '一个', '这个', '那个', '什么', '怎么', '这样', '那样', '哪里',
            '好的', '知道', '明白', '清楚', '谢谢', '不用', '没事',
            # 口语化词汇
            '有点', '一下', '一点', '一些', '稍微', '比较', '感觉', '觉得',
            '应该', '可能', '好像', '似乎', '大概', '差不多', '左右', '或者',
            # 程度副词
            '非常', '特别', '很', '挺', '蛮', '超级', '极其', '十分', '相当',
            '太', '更', '最', '更加', '越来越', '有些', '稍微',
            # 时间词
            '现在', '刚才', '马上', '立刻', '然后', '接着', '后来', '以前',
            '之前', '之后', '当时', '今天', '明天', '昨天', '刚刚', '等会',
            # 语气词和笑声
            '哈哈', '哈哈哈', '哈哈哈哈', '呵呵', '嘿嘿', '嘻嘻', '嘿嘿嘿',
            '哎呀', '哎哟', '唉', '诶', '嗨', '喂', '嗷', '啧', '嘶',
            # 常见短语
            '不知道', '怎么样', '没关系', '没问题', '不要紧', '没事儿',
            '是不是', '对不对', '行不行', '好不好', '可不可以', '能不能',
            '不太', '不太好', '有没有', '要不要', '用不用', '需不需要',
            # 疑问词
            '为什么', '怎么办', '怎么了', '干嘛', '干什么', '做什么',
            '哪个', '哪些', '多少', '几个', '什么样', '怎样',
            # 确认词
            '对', '嗯嗯', '嗯哼', '好吧', '行吧', '可以啊', '没错',
            '是的', '是啊', '对啊', '对的', '没错', '确实', '的确'
        }
    
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
            print("[ERROR] jieba未安装，请执行: pip install jieba")
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
