"""实时消息情感分析 - 规则库和词典

包含:
- 表情符号映射
- 网络用语词典
- 情感词典
- 功能词典(程度词、否定词、转折词)
"""

# ========== 表情符号映射 ==========

EMOJI_SENTIMENT = {
    # 正面表情
    '😊': {'sentiment': 'positive', 'intensity': 0.8},
    '😄': {'sentiment': 'positive', 'intensity': 0.9},
    '😁': {'sentiment': 'positive', 'intensity': 0.85},
    '🙂': {'sentiment': 'positive', 'intensity': 0.7},
    '😃': {'sentiment': 'positive', 'intensity': 0.9},
    '😀': {'sentiment': 'positive', 'intensity': 0.85},
    '🤗': {'sentiment': 'positive', 'intensity': 0.8},
    '😍': {'sentiment': 'positive', 'intensity': 0.95},
    '🥰': {'sentiment': 'positive', 'intensity': 0.95},
    '😘': {'sentiment': 'positive', 'intensity': 0.9},
    '👍': {'sentiment': 'positive', 'intensity': 0.75},
    '👏': {'sentiment': 'positive', 'intensity': 0.8},
    '💪': {'sentiment': 'positive', 'intensity': 0.85},
    '❤️': {'sentiment': 'positive', 'intensity': 0.95},
    '💕': {'sentiment': 'positive', 'intensity': 0.9},
    '🎉': {'sentiment': 'positive', 'intensity': 0.9},
    '✨': {'sentiment': 'positive', 'intensity': 0.75},
    '🌟': {'sentiment': 'positive', 'intensity': 0.8},
    
    # 负面表情
    '😢': {'sentiment': 'negative', 'intensity': -0.9},
    '😭': {'sentiment': 'negative', 'intensity': -0.95},
    '😞': {'sentiment': 'negative', 'intensity': -0.8},
    '😔': {'sentiment': 'negative', 'intensity': -0.75},
    '😟': {'sentiment': 'negative', 'intensity': -0.7},
    '😕': {'sentiment': 'negative', 'intensity': -0.65},
    '😡': {'sentiment': 'negative', 'intensity': -1.0},
    '😠': {'sentiment': 'negative', 'intensity': -0.95},
    '😤': {'sentiment': 'negative', 'intensity': -0.85},
    '😒': {'sentiment': 'negative', 'intensity': -0.7},
    '🙄': {'sentiment': 'negative', 'intensity': -0.6},
    '😩': {'sentiment': 'negative', 'intensity': -0.85},
    '😫': {'sentiment': 'negative', 'intensity': -0.9},
    '😖': {'sentiment': 'negative', 'intensity': -0.8},
    '👎': {'sentiment': 'negative', 'intensity': -0.75},
    '💔': {'sentiment': 'negative', 'intensity': -0.9},
    
    # 中性表情
    '😅': {'sentiment': 'neutral', 'intensity': 0.0},
    '😂': {'sentiment': 'positive', 'intensity': 0.85},  # 笑哭,偏正面
    '🤣': {'sentiment': 'positive', 'intensity': 0.9},
    '😆': {'sentiment': 'positive', 'intensity': 0.85},
    '😏': {'sentiment': 'neutral', 'intensity': 0.0},
    '🤔': {'sentiment': 'neutral', 'intensity': 0.0},
    '😐': {'sentiment': 'neutral', 'intensity': 0.0},
    '😑': {'sentiment': 'neutral', 'intensity': -0.2},
    '🙃': {'sentiment': 'neutral', 'intensity': 0.0},
}

# ========== 网络用语词典 ==========

INTERNET_SLANG = {
    # 正面网络用语
    'yyds': {'text': '永远的神', 'sentiment': 'positive', 'intensity': 0.95},
    '绝绝子': {'text': '非常好', 'sentiment': 'positive', 'intensity': 0.9},
    '牛': {'text': '厉害', 'sentiment': 'positive', 'intensity': 0.85},
    '牛逼': {'text': '厉害', 'sentiment': 'positive', 'intensity': 0.9},
    '666': {'text': '厉害', 'sentiment': 'positive', 'intensity': 0.85},
    '6': {'text': '厉害', 'sentiment': 'positive', 'intensity': 0.75},
    '赞': {'text': '好', 'sentiment': 'positive', 'intensity': 0.8},
    '给力': {'text': '很好', 'sentiment': 'positive', 'intensity': 0.85},
    '棒': {'text': '好', 'sentiment': 'positive', 'intensity': 0.8},
    '优秀': {'text': '好', 'sentiment': 'positive', 'intensity': 0.85},
    '可以': {'text': '不错', 'sentiment': 'positive', 'intensity': 0.7},
    '奥利给': {'text': '加油', 'sentiment': 'positive', 'intensity': 0.8},
    
    # 负面网络用语
    'emo': {'text': '情绪低落', 'sentiment': 'negative', 'intensity': -0.85},
    'emo了': {'text': '情绪低落了', 'sentiment': 'negative', 'intensity': -0.9},
    '无语': {'text': '不满', 'sentiment': 'negative', 'intensity': -0.75},
    '无语了': {'text': '很不满', 'sentiment': 'negative', 'intensity': -0.8},
    '服了': {'text': '无奈', 'sentiment': 'negative', 'intensity': -0.7},
    '醉了': {'text': '无语', 'sentiment': 'negative', 'intensity': -0.7},
    '尬': {'text': '尴尬', 'sentiment': 'negative', 'intensity': -0.65},
    '尴尬': {'text': '尴尬', 'sentiment': 'negative', 'intensity': -0.65},
    '崩溃': {'text': '崩溃', 'sentiment': 'negative', 'intensity': -0.95},
    '裂开': {'text': '崩溃', 'sentiment': 'negative', 'intensity': -0.85},
    '破防': {'text': '受伤', 'sentiment': 'negative', 'intensity': -0.8},
    '麻了': {'text': '麻木', 'sentiment': 'negative', 'intensity': -0.75},
    
    # 中性/特殊
    '哈哈': {'text': '笑', 'sentiment': 'positive', 'intensity': 0.7},
    '哈哈哈': {'text': '大笑', 'sentiment': 'positive', 'intensity': 0.8},
    '嘿嘿': {'text': '笑', 'sentiment': 'positive', 'intensity': 0.6},
    '嗯': {'text': '嗯', 'sentiment': 'neutral', 'intensity': 0.0},
    '哦': {'text': '哦', 'sentiment': 'neutral', 'intensity': -0.1},
    '好吧': {'text': '好吧', 'sentiment': 'neutral', 'intensity': -0.2},
    '随便': {'text': '随便', 'sentiment': 'neutral', 'intensity': -0.3},
}

# ========== 情感词典 ==========

SENTIMENT_WORDS = {
    'positive': {
        'strong': [
            '非常好', '超级棒', '太赞了', '完美', '优秀', '杰出', '卓越',
            '精彩', '出色', '一流', '顶级', '极好', '超棒', '太好了',
            '爱了', '喜欢', '热爱', '开心', '快乐', '幸福', '满意',
            '激动', '兴奋', '高兴', '愉快', '舒服', '舒心', '美好'
        ],
        'medium': [
            '不错', '可以', '还行', '挺好', '好', '行', '可',
            '满意', '认可', '赞同', '支持', '同意', '欣赏',
            '喜欢', '有趣', '好玩', '有意思'
        ],
        'weak': [
            '还可以', '还好', '一般般', '凑合', '马马虎虎',
            '过得去', '说得过去'
        ]
    },
    'negative': {
        'strong': [
            '太差了', '糟糕透了', '无语了', '崩溃', '讨厌', '恶心',
            '垃圾', '烂', '破', '差劲', '恶劣', '糟糕', '可怕',
            '失望', '绝望', '痛苦', '难受', '伤心', '悲伤', '沮丧',
            '愤怒', '生气', '恼火', '烦躁', '厌烦', '讨厌'
        ],
        'medium': [
            '不好', '不行', '差', '不满', '不爽', '烦',
            '麻烦', '问题', '困难', '难', '累', '疲惫',
            '无聊', '乏味', '枯燥'
        ],
        'weak': [
            '不太好', '有点差', '一般', '不怎么样',
            '有点烦', '有点累', '有点无聊'
        ]
    }
}

# ========== 功能词典 ==========

# 程度副词
DEGREE_WORDS = {
    'strong': ['非常', '特别', '超级', '极其', '十分', '相当', '格外', '异常', '太', '最'],
    'medium': ['很', '挺', '比较', '较', '还', '蛮', '颇'],
    'weak': ['有点', '稍微', '略', '稍', '些许', '一点', '一些']
}

# 否定词
NEGATION_WORDS = [
    '不', '没', '无', '非', '未', '否', '别', '莫', '勿',
    '不是', '没有', '不会', '不能', '不要', '不用', '不必',
    '没什么', '没啥', '不怎么', '不太', '不够', '不行'
]

# 转折词
TRANSITION_WORDS = [
    '但是', '可是', '不过', '然而', '只是', '就是',
    '但', '却', '而', '反而', '相反', '倒是'
]

# 因果词
CAUSAL_WORDS = [
    '因为', '由于', '所以', '因此', '故', '因而',
    '既然', '既', '以至', '以致'
]

# 条件词
CONDITIONAL_WORDS = [
    '如果', '假如', '要是', '倘若', '若', '假使',
    '虽然', '尽管', '即使', '纵使', '哪怕'
]

# ========== 反讽检测模式 ==========

SARCASM_PATTERNS = [
    '呵呵',
    '好的好的',
    '行行行',
    '是是是',
    '对对对',
    '随便吧',
    '无所谓',
    '爱咋咋地',
    '你开心就好',
    '你说了算',
]

# ========== 敷衍检测 ==========

PERFUNCTORY_WORDS = [
    '嗯', '哦', '好吧', '随便', '都行', '可以',
    '嗯嗯', '哦哦', '好好', '行行'
]


def get_emoji_sentiment(emoji: str) -> dict:
    """获取表情符号的情感
    
    Returns:
        {'sentiment': 'positive'/'negative'/'neutral', 'intensity': float}
        或 None
    """
    return EMOJI_SENTIMENT.get(emoji)


def get_slang_info(word: str) -> dict:
    """获取网络用语信息
    
    Returns:
        {'text': str, 'sentiment': str, 'intensity': float}
        或 None
    """
    return INTERNET_SLANG.get(word.lower())


def is_degree_word(word: str) -> tuple:
    """判断是否为程度词
    
    Returns:
        (True/False, 'strong'/'medium'/'weak'/None)
    """
    for level, words in DEGREE_WORDS.items():
        if word in words:
            return True, level
    return False, None


def is_negation_word(word: str) -> bool:
    """判断是否为否定词"""
    return word in NEGATION_WORDS


def is_transition_word(word: str) -> bool:
    """判断是否为转折词"""
    return word in TRANSITION_WORDS


def contains_sarcasm(text: str) -> bool:
    """检测是否包含反讽模式"""
    return any(pattern in text for pattern in SARCASM_PATTERNS)


def is_perfunctory(text: str) -> bool:
    """检测是否为敷衍回复"""
    text = text.strip()
    return text in PERFUNCTORY_WORDS or len(text) <= 2


def get_sentiment_word_score(word: str) -> float:
    """获取情感词的分数
    
    Returns:
        1.0 (强正面) / 0.6 (中正面) / 0.3 (弱正面) /
        -1.0 (强负面) / -0.6 (中负面) / -0.3 (弱负面) /
        0.0 (非情感词)
    """
    # 正面词
    if word in SENTIMENT_WORDS['positive']['strong']:
        return 1.0
    if word in SENTIMENT_WORDS['positive']['medium']:
        return 0.6
    if word in SENTIMENT_WORDS['positive']['weak']:
        return 0.3
    
    # 负面词
    if word in SENTIMENT_WORDS['negative']['strong']:
        return -1.0
    if word in SENTIMENT_WORDS['negative']['medium']:
        return -0.6
    if word in SENTIMENT_WORDS['negative']['weak']:
        return -0.3
    
    return 0.0
