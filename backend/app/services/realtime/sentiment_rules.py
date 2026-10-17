"""实时消息情感分析 - 规则库和词典

包含:
- 表情符号映射
- 网络用语词典
- 情感词典
- 功能词典(程度词、否定词、转折词)
"""

# ========== 表情符号映射 ==========

EMOJI_SENTIMENT = {
    # ---- 正面：喜爱与亲昵 ----
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
    '☺️': {'sentiment': 'positive', 'intensity': 0.75},
    '😋': {'sentiment': 'positive', 'intensity': 0.6},
    '🤭': {'sentiment': 'positive', 'intensity': 0.6},
    '😜': {'sentiment': 'positive', 'intensity': 0.6},
    '🤪': {'sentiment': 'positive', 'intensity': 0.4},
    '😎': {'sentiment': 'positive', 'intensity': 0.55},
    '🤩': {'sentiment': 'positive', 'intensity': 0.85},
    '🥳': {'sentiment': 'positive', 'intensity': 0.9},
    '😌': {'sentiment': 'positive', 'intensity': 0.6},
    '😻': {'sentiment': 'positive', 'intensity': 0.9},
    '😽': {'sentiment': 'positive', 'intensity': 0.85},
    '🫶': {'sentiment': 'positive', 'intensity': 0.9},
    '💋': {'sentiment': 'positive', 'intensity': 0.8},
    '🥺': {'sentiment': 'positive', 'intensity': 0.4},   # 撒娇卖萌，弱正面
    '🙈': {'sentiment': 'positive', 'intensity': 0.4},   # 害羞捂脸，弱正面
    '🥲': {'sentiment': 'positive', 'intensity': 0.35},  # 感动带泪，弱正面

    # ---- 正面：夸赞与支持 ----
    '👍': {'sentiment': 'positive', 'intensity': 0.75},
    '👏': {'sentiment': 'positive', 'intensity': 0.8},
    '💪': {'sentiment': 'positive', 'intensity': 0.85},
    '👊': {'sentiment': 'positive', 'intensity': 0.6},
    '🤝': {'sentiment': 'positive', 'intensity': 0.65},
    '👌': {'sentiment': 'positive', 'intensity': 0.6},
    '🤙': {'sentiment': 'positive', 'intensity': 0.55},
    '🫡': {'sentiment': 'positive', 'intensity': 0.6},
    '✌': {'sentiment': 'positive', 'intensity': 0.5},
    '✌️': {'sentiment': 'positive', 'intensity': 0.5},
    '🤞': {'sentiment': 'positive', 'intensity': 0.5},
    '🙏': {'sentiment': 'positive', 'intensity': 0.35},  # 求助/感谢兼有，弱正面
    '💯': {'sentiment': 'positive', 'intensity': 0.8},
    '🔥': {'sentiment': 'positive', 'intensity': 0.7},

    # ---- 正面：爱心与庆祝 ----
    '❤️': {'sentiment': 'positive', 'intensity': 0.95},
    '❤': {'sentiment': 'positive', 'intensity': 0.95},  # 无变体选择符的同码位
    '💕': {'sentiment': 'positive', 'intensity': 0.9},
    '💖': {'sentiment': 'positive', 'intensity': 0.92},
    '💗': {'sentiment': 'positive', 'intensity': 0.88},
    '💓': {'sentiment': 'positive', 'intensity': 0.88},
    '💘': {'sentiment': 'positive', 'intensity': 0.9},
    '💝': {'sentiment': 'positive', 'intensity': 0.9},
    '💞': {'sentiment': 'positive', 'intensity': 0.88},
    '💙': {'sentiment': 'positive', 'intensity': 0.85},
    '💚': {'sentiment': 'positive', 'intensity': 0.85},
    '💛': {'sentiment': 'positive', 'intensity': 0.85},
    '🧡': {'sentiment': 'positive', 'intensity': 0.85},
    '💜': {'sentiment': 'positive', 'intensity': 0.85},
    '🖤': {'sentiment': 'positive', 'intensity': 0.5},   # 暗黑爱心在亲密语境常用
    '❣️': {'sentiment': 'positive', 'intensity': 0.85},
    '✨': {'sentiment': 'positive', 'intensity': 0.75},
    '🌟': {'sentiment': 'positive', 'intensity': 0.8},
    '🎉': {'sentiment': 'positive', 'intensity': 0.9},
    '🎊': {'sentiment': 'positive', 'intensity': 0.85},
    '🎁': {'sentiment': 'positive', 'intensity': 0.75},
    '🌹': {'sentiment': 'positive', 'intensity': 0.6},
    '🌸': {'sentiment': 'positive', 'intensity': 0.55},

    # ---- 笑 ----
    '😂': {'sentiment': 'positive', 'intensity': 0.85},
    '🤣': {'sentiment': 'positive', 'intensity': 0.9},
    '😆': {'sentiment': 'positive', 'intensity': 0.85},
    '😅': {'sentiment': 'neutral', 'intensity': 0.0},

    # ---- 负面：悲伤 ----
    '😢': {'sentiment': 'negative', 'intensity': -0.9},
    '😭': {'sentiment': 'negative', 'intensity': -0.95},
    '😞': {'sentiment': 'negative', 'intensity': -0.8},
    '😔': {'sentiment': 'negative', 'intensity': -0.75},
    '😟': {'sentiment': 'negative', 'intensity': -0.7},
    '😕': {'sentiment': 'negative', 'intensity': -0.65},
    '😰': {'sentiment': 'negative', 'intensity': -0.75},
    '😨': {'sentiment': 'negative', 'intensity': -0.8},
    '😱': {'sentiment': 'negative', 'intensity': -0.9},
    '😥': {'sentiment': 'negative', 'intensity': -0.65},
    '🫥': {'sentiment': 'negative', 'intensity': -0.5},
    '😶': {'sentiment': 'negative', 'intensity': -0.35},
    '🫠': {'sentiment': 'negative', 'intensity': -0.45},
    '💔': {'sentiment': 'negative', 'intensity': -0.9},
    '🥀': {'sentiment': 'negative', 'intensity': -0.7},

    # ---- 负面：愤怒与厌恶 ----
    '😡': {'sentiment': 'negative', 'intensity': -1.0},
    '😠': {'sentiment': 'negative', 'intensity': -0.95},
    '😤': {'sentiment': 'negative', 'intensity': -0.85},
    '😒': {'sentiment': 'negative', 'intensity': -0.7},
    '🙄': {'sentiment': 'negative', 'intensity': -0.6},
    '😩': {'sentiment': 'negative', 'intensity': -0.85},
    '😫': {'sentiment': 'negative', 'intensity': -0.9},
    '😖': {'sentiment': 'negative', 'intensity': -0.8},
    '👎': {'sentiment': 'negative', 'intensity': -0.75},
    '🤬': {'sentiment': 'negative', 'intensity': -1.0},
    '🤢': {'sentiment': 'negative', 'intensity': -0.85},
    '🤮': {'sentiment': 'negative', 'intensity': -0.9},
    '🤧': {'sentiment': 'negative', 'intensity': -0.5},
    '👿': {'sentiment': 'negative', 'intensity': -0.8},
    '🤡': {'sentiment': 'negative', 'intensity': -0.5},  # 小丑嘲讽/自嘲
    '☠️': {'sentiment': 'negative', 'intensity': -0.7},
    '💢': {'sentiment': 'negative', 'intensity': -0.6},
    '🤦': {'sentiment': 'negative', 'intensity': -0.6},
    '🤷': {'sentiment': 'negative', 'intensity': -0.25},  # 无奈摊手

    # ---- 负面：疲惫与尴尬 ----
    '🥱': {'sentiment': 'negative', 'intensity': -0.4},
    '😵': {'sentiment': 'negative', 'intensity': -0.6},
    '🤯': {'sentiment': 'negative', 'intensity': -0.55},
    '😬': {'sentiment': 'negative', 'intensity': -0.5},
    '😳': {'sentiment': 'negative', 'intensity': -0.15},
    '🥵': {'sentiment': 'negative', 'intensity': -0.5},
    '🥶': {'sentiment': 'negative', 'intensity': -0.5},
    '🤨': {'sentiment': 'negative', 'intensity': -0.2},
    '🧐': {'sentiment': 'negative', 'intensity': -0.15},

    # ---- 中性/歧义 ----
    '😏': {'sentiment': 'neutral', 'intensity': 0.0},
    '🤔': {'sentiment': 'neutral', 'intensity': 0.0},
    '😐': {'sentiment': 'neutral', 'intensity': 0.0},
    '😑': {'sentiment': 'neutral', 'intensity': -0.2},
    '🙃': {'sentiment': 'neutral', 'intensity': 0.0},
    '😴': {'sentiment': 'neutral', 'intensity': 0.0},
    '💤': {'sentiment': 'neutral', 'intensity': 0.0},
    '😈': {'sentiment': 'neutral', 'intensity': 0.0},  # 调皮而非恶意
    '💀': {'sentiment': 'neutral', 'intensity': 0.0},  # 歧义大：网络语境常表「笑死」
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
    '破大防': {'text': '很受伤', 'sentiment': 'negative', 'intensity': -0.85},
    '麻了': {'text': '麻木', 'sentiment': 'negative', 'intensity': -0.75},

    # 关系语境（本应用核心域）
    '心动': {'text': '动了心', 'sentiment': 'positive', 'intensity': 0.8},
    '暧昧': {'text': '关系暧昧', 'sentiment': 'positive', 'intensity': 0.2},
    '官宣': {'text': '公开恋情', 'sentiment': 'positive', 'intensity': 0.85},
    '双向奔赴': {'text': '互相喜欢', 'sentiment': 'positive', 'intensity': 0.9},
    '处对象': {'text': '谈恋爱', 'sentiment': 'positive', 'intensity': 0.5},
    '上头': {'text': '着迷', 'sentiment': 'positive', 'intensity': 0.7},
    '下头': {'text': '瞬间无感', 'sentiment': 'negative', 'intensity': -0.7},
    '海王': {'text': '广撒网者', 'sentiment': 'negative', 'intensity': -0.7},
    '舔狗': {'text': '无底线讨好', 'sentiment': 'negative', 'intensity': -0.6},
    '画饼': {'text': '空头承诺', 'sentiment': 'negative', 'intensity': -0.6},
    'pua': {'text': '精神操控', 'sentiment': 'negative', 'intensity': -0.85},
    '渣男': {'text': '感情不专一', 'sentiment': 'negative', 'intensity': -0.8},
    '渣女': {'text': '感情不专一', 'sentiment': 'negative', 'intensity': -0.8},
    '已读不回': {'text': '看了不回', 'sentiment': 'negative', 'intensity': -0.5},
    '已读乱回': {'text': '敷衍乱回', 'sentiment': 'negative', 'intensity': -0.4},
    '鸽了': {'text': '爽约', 'sentiment': 'negative', 'intensity': -0.45},
    '放鸽子': {'text': '爽约', 'sentiment': 'negative', 'intensity': -0.5},
    '咕咕': {'text': '拖约定', 'sentiment': 'negative', 'intensity': -0.25},

    # 情绪与评价（近年仍在用，过气词勿再回填）
    '绝了': {'text': '太厉害', 'sentiment': 'positive', 'intensity': 0.6},
    '拿捏': {'text': '稳稳掌握', 'sentiment': 'positive', 'intensity': 0.7},
    '嘴替': {'text': '说出心声', 'sentiment': 'positive', 'intensity': 0.75},
    '听劝': {'text': '肯接受意见', 'sentiment': 'positive', 'intensity': 0.4},
    '整活': {'text': '玩出新花样', 'sentiment': 'positive', 'intensity': 0.5},
    '显眼包': {'text': '活跃搞笑的人', 'sentiment': 'positive', 'intensity': 0.4},
    '乐子': {'text': '有趣的事', 'sentiment': 'positive', 'intensity': 0.3},
    '吃瓜': {'text': '围观八卦', 'sentiment': 'neutral', 'intensity': 0.0},
    '抽象': {'text': '难以理解的好笑', 'sentiment': 'neutral', 'intensity': 0.0},
    '那咋了': {'text': '无所谓的松弛', 'sentiment': 'neutral', 'intensity': 0.0},
    '塌房': {'text': '人设崩塌', 'sentiment': 'negative', 'intensity': -0.6},
    '翻车': {'text': '搞砸了', 'sentiment': 'negative', 'intensity': -0.5},
    '汗流浃背': {'text': '尴尬紧张', 'sentiment': 'negative', 'intensity': -0.3},
    '蚌埠住了': {'text': '绷不住（多为笑）', 'sentiment': 'positive', 'intensity': 0.4},
    'xswl': {'text': '笑死我了', 'sentiment': 'positive', 'intensity': 0.6},
    'awsl': {'text': '啊我死了（可爱到）', 'sentiment': 'positive', 'intensity': 0.7},
    '磕到了': {'text': '为甜到的东西满足', 'sentiment': 'positive', 'intensity': 0.7},
    '尊嘟假嘟': {'text': '真的假的', 'sentiment': 'positive', 'intensity': 0.3},
    '包的': {'text': '肯定的', 'sentiment': 'positive', 'intensity': 0.7},
    '寄': {'text': '完蛋了', 'sentiment': 'negative', 'intensity': -0.6},
    '急了': {'text': '他被戳破了', 'sentiment': 'negative', 'intensity': -0.3},
    '乐': {'text': '嘲讽性地笑', 'sentiment': 'negative', 'intensity': -0.2},
    '典': {'text': '太典型了（讥）', 'sentiment': 'negative', 'intensity': -0.25},
    'yygq': {'text': '阴阳怪气', 'sentiment': 'negative', 'intensity': -0.4},
    '拴q': {'text': '无奈的谢谢', 'sentiment': 'negative', 'intensity': -0.3},

    # 生活状态
    '摆烂': {'text': '放弃努力', 'sentiment': 'negative', 'intensity': -0.6},
    '躺平': {'text': '不再内卷', 'sentiment': 'negative', 'intensity': -0.4},
    '内卷': {'text': '过度竞争', 'sentiment': 'negative', 'intensity': -0.5},
    '内耗': {'text': '自我消耗', 'sentiment': 'negative', 'intensity': -0.6},
    '精神内耗': {'text': '心理自我消耗', 'sentiment': 'negative', 'intensity': -0.7},
    '摸鱼': {'text': '偷闲', 'sentiment': 'neutral', 'intensity': 0.0},
    '干饭': {'text': '吃饭', 'sentiment': 'positive', 'intensity': 0.4},
    '上岸': {'text': '考编/考研成功', 'sentiment': 'positive', 'intensity': 0.8},
    '社死': {'text': '社会性死亡', 'sentiment': 'negative', 'intensity': -0.65},
    '尬聊': {'text': '尴尬地聊天', 'sentiment': 'negative', 'intensity': -0.5},
    '搭子': {'text': '固定同伴', 'sentiment': 'positive', 'intensity': 0.3},

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

# 显式敷衍词：叠字应付、放任句式、回避性短答。
# 3 字以上的条目必须显式列出——长度兜底只覆盖 ≤2 字。
PERFUNCTORY_WORDS = [
    '嗯', '哦', '好吧', '随便', '都行',
    '好好', '行行',
    # 三连应付（placating/不耐烦）——注意与「嗯嗯」类软化叠字相反：
    # 公开共识是嗯嗯/哦哦显热情，好好好/行行行/是是是是敷衍式顺从
    '好好好', '行行行', '是是是', '对对对', '呵呵呵',
    # 放任/回避句式
    '随便你', '随便吧', '无所谓', '好吧好吧', '不知道', '不清楚', '你决定',
    '都可以', '没意见', '看着办', 'okay',
]

# 高投入短回复白名单：短 ≠ 敷衍。笑声是对玩笑的正确回应、感谢与
# 情感表达自带情绪投入、状态告知是信息而非应付。此前 len<=2 一刀切
# 把它们全判成敷衍，直接抬高敷衍回复率（情感共鸣维）与单向投入风险。
ENGAGED_SHORT_REPLIES = frozenset({
    # 笑声
    '哈哈', '嘿嘿', '嘻嘻',
    # 感谢与情感表达
    '谢谢', '多谢', '辛苦', '爱你', '想你', '抱抱', '亲亲',
    # 状态告知（信息性回复）
    '来了', '走了', '睡了', '起了', '在的', '在呢',
    # 暖性应答（区别于「好吧」类冷应答）
    '好呀', '好哒', '好嘞', '好滴', '好耶', '嗯呐', '嗯呢',
    # 应答性同意：单独「可以」多数是对待决问题的回答（明天见？→可以），
    # 或评价性「不错」（与 INTERNET_SLANG 的可以=+0.7 一致），不判敷衍
    '可以',
    # 软化叠字：公开共识「嗯嗯/哦哦 ≠ 嗯/哦」——叠字显热情、是礼貌收到
    '嗯嗯', '哦哦',
    # 夸赞短句
    '666', '999', '233', '牛', '强', '稳', '顶', '冲', '绝',
    '帅', '美', '棒', '赞',
})


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
    """检测是否为敷衍回复。

    判定顺序：空串不算回复 → 高投入短回复白名单先排除 →
    显式敷衍词表 → 长度兜底（≤2 字）。
    """
    text = text.strip()
    if not text:
        return False
    if text in ENGAGED_SHORT_REPLIES:
        return False
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
