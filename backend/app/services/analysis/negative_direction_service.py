"""负面情绪方向判定服务

判定负面情绪的目标对象:
- to_me: 对我表达不满（减好感度）
- to_others: 对他人/事物的负面情绪，向我倾诉（不减甚至加好感度）
- ambiguous: 无法判定（保守处理，半权重扣分）

判定流程:
1. 人称代词检测 - 检查指向对象
2. 负面意图模式匹配 - 匹配典型表达模式
3. 上下文信号检测 - 检测倾诉/对抗信号
4. 综合评分 → 输出方向 + 置信度
"""

import re
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class NegativeDirectionResult:
    """负面方向判定结果"""
    direction: str = "ambiguous"  # to_me / to_others / ambiguous
    confidence: float = 0.0      # 0.0 - 1.0
    reason: str = ""             # 判定依据


class NegativeDirectionService:
    """负面情绪方向判定服务"""

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """编译所有正则表达式模式"""

        # ===== 步骤1: 人称代词 =====

        # 指向"我方"（对方在消息里对"你"表达不满 → 对我的负面）
        self._you_pronouns = re.compile(
            r'你们?|您|你的|你们的',
            re.IGNORECASE
        )

        # 指向"第三方"（对方提到第三人 → 对他人的负面）
        self._third_person_pronouns = re.compile(
            r'他们?|她们?|它们?|那个人|那些人|那家伙|'
            r'老板|领导|同事|老师|客户|室友|邻居|'
            r'前任|前男友|前女友|'
            r'我妈|我爸|我爸妈|爸妈|父母|公婆|婆婆|丈母娘',
            re.IGNORECASE
        )

        # ===== 步骤2: 负面意图模式 =====

        # "对我"的负面模式 - 指责、质问、命令、嫌弃
        self._to_me_patterns = [
            re.compile(p) for p in [
                r'你怎么(这么|那么|总是|又|还)',
                r'你(能不能|可不可以|会不会)',
                r'你(总是|老是|一直|每次|从来)',
                r'(受不了|烦死|讨厌|厌烦|真烦)你',
                r'你(烦不烦|有完没完|够了没)',
                r'(都|全)怪你',
                r'你(就不能|就不会|难道不)',
                r'跟你(说了|讲了).*(次|遍)',
                r'你(滚|走开|别.{0,4}了|闭嘴)',
                r'你(真的|太).{0,4}(烦|差|笨|蠢|傻|懒|慢)',
                r'不想(理你|跟你|和你|搭理你)',
                r'(生你的气|对你失望)',
            ]
        ]

        # "对他人"的负面模式 - 吐槽、抱怨第三方
        self._to_others_patterns = [
            re.compile(p) for p in [
                r'(他|她|他们|她们)(居然|竟然|真的|太)',
                r'(老板|领导|同事|老师|客户).{0,6}(烦|气|过分|讨厌|恶心)',
                r'被.{0,6}(骂|批评|说|怼|欺负|坑|骗)',
                r'(气死|烦死|累死|吓死|恶心死)(我|人)了',
                r'(今天|刚才|昨天|上午|下午).{0,10}(烦|气|郁闷|生气|倒霉|委屈)',
                r'(真是|真的|太).{0,4}(过分|恶心|离谱|无语|奇葩|变态)',
                r'(受不了|忍不了|看不惯).{0,6}(他|她|他们|她们|那)',
                r'什么(人|东西|玩意|破)',
            ]
        ]

        # ===== 步骤3: 上下文信号 =====

        # "倾诉/分享型"信号 → 倾向于对他人
        self._sharing_signals = re.compile(
            r'跟你说个?|你知道吗|我跟你讲|我跟你说|'
            r'我跟你吐槽|你猜怎么着|你听我说|'
            r'告诉你一?件?事|太离谱了你听|'
            r'我今天|我刚才|好烦啊(?!你)|'
            r'郁闷|心累|无语了|崩溃了|emo了|破防了'
        )

        # "质问/对抗型"信号 → 倾向于对我
        self._confrontation_signals = re.compile(
            r'你说你?|你给我|我告诉你|'
            r'你自己.{0,4}(看|想|说)|'
            r'你凭什么|你有什么资格|'
            r'你到底|你究竟|你怎么回事'
        )

    def classify(self, content: str) -> NegativeDirectionResult:
        """
        判定负面消息的情绪方向

        该方法仅应在消息已被判定为负面(polarity == -1)时调用。

        Args:
            content: 消息文本内容

        Returns:
            NegativeDirectionResult: 方向判定结果
        """
        if not content or not content.strip():
            return NegativeDirectionResult(direction="ambiguous", confidence=0.0)

        # 收集各阶段的证据分数
        # 正分 → 倾向"对我"  负分 → 倾向"对他人"
        evidence_score = 0.0
        reasons = []

        # ===== 步骤1: 人称代词检测 =====
        you_count = len(self._you_pronouns.findall(content))
        third_count = len(self._third_person_pronouns.findall(content))

        if you_count > 0 and third_count == 0:
            evidence_score += 2.0
            reasons.append(f"含{you_count}个对你指向词")
        elif third_count > 0 and you_count == 0:
            evidence_score -= 2.0
            reasons.append(f"含{third_count}个第三方指向词")
        elif you_count > 0 and third_count > 0:
            # 两者都有，看比例
            if you_count > third_count:
                evidence_score += 0.5
                reasons.append("混合指向，偏向对你")
            else:
                evidence_score -= 0.5
                reasons.append("混合指向，偏向第三方")

        # ===== 步骤2: 负面意图模式匹配 =====
        to_me_hits = sum(1 for p in self._to_me_patterns if p.search(content))
        to_others_hits = sum(1 for p in self._to_others_patterns if p.search(content))

        if to_me_hits > 0:
            evidence_score += to_me_hits * 1.5
            reasons.append(f"命中{to_me_hits}个对你负面模式")
        if to_others_hits > 0:
            evidence_score -= to_others_hits * 1.5
            reasons.append(f"命中{to_others_hits}个对他人负面模式")

        # ===== 步骤3: 上下文信号检测 =====
        if self._sharing_signals.search(content):
            evidence_score -= 1.5
            reasons.append("包含倾诉/分享信号")
        if self._confrontation_signals.search(content):
            evidence_score += 1.5
            reasons.append("包含质问/对抗信号")

        # ===== 步骤4: 综合判定 =====
        return self._aggregate(evidence_score, reasons)

    def classify_batch(self, contents: List[str]) -> List[NegativeDirectionResult]:
        """
        批量判定负面消息方向

        Args:
            contents: 消息文本列表

        Returns:
            判定结果列表
        """
        return [self.classify(c) for c in contents]

    def _aggregate(
        self,
        evidence_score: float,
        reasons: List[str]
    ) -> NegativeDirectionResult:
        """
        将证据分数聚合为最终判定

        Args:
            evidence_score: 证据分数（正=对我，负=对他人）
            reasons: 判定依据列表

        Returns:
            NegativeDirectionResult
        """
        # 判定阈值
        THRESHOLD = 1.5

        if evidence_score >= THRESHOLD:
            direction = "to_me"
            # 置信度: 分数越高越确定，上限5分映射到1.0
            confidence = min(1.0, evidence_score / 5.0)
        elif evidence_score <= -THRESHOLD:
            direction = "to_others"
            confidence = min(1.0, abs(evidence_score) / 5.0)
        else:
            direction = "ambiguous"
            # 模糊区域的置信度较低
            confidence = max(0.0, 1.0 - abs(evidence_score) / THRESHOLD)

        reason_text = "; ".join(reasons) if reasons else "无明确信号"

        return NegativeDirectionResult(
            direction=direction,
            confidence=round(confidence, 2),
            reason=reason_text,
        )

    @staticmethod
    def get_score_multiplier(direction: str) -> float:
        """
        获取负面分数的乘数

        Args:
            direction: 方向判定结果

        Returns:
            乘数 (0.0 - 1.0)
        """
        multipliers = {
            "to_me": 1.0,       # 对我 → 正常扣分
            "to_others": 0.0,   # 对他人 → 不扣分
            "ambiguous": 0.5,   # 模糊 → 半权重扣分
        }
        return multipliers.get(direction, 0.5)

    @staticmethod
    def get_trust_bonus(direction: str) -> float:
        """
        获取信任倾诉加分

        Args:
            direction: 方向判定结果

        Returns:
            加分值 (0.0 或正数)
        """
        if direction == "to_others":
            return 1.0  # 对他人的负面倾诉 → 加分（信任信号）
        return 0.0
