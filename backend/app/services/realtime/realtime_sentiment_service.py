"""实时消息情感分析服务

基于RoBERTa-small模型和规则增强的轻量级情感分析
专门为实时聊天消息设计,独立于历史记录情感分析
"""

import os
import re
import time
import json
import pickle
from typing import Dict, Any, List, Optional
import jieba
from .sentiment_rules import (
    get_emoji_sentiment, get_slang_info, is_degree_word,
    is_negation_word, is_transition_word, contains_sarcasm,
    is_perfunctory, get_sentiment_word_score, EMOJI_SENTIMENT
)
from ...db.connection import get_db

# 配置HuggingFace镜像站
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'


class RealtimeSentimentService:
    """实时消息情感分析服务
    
    使用RoBERTa-small模型 + 规则增强
    输出格式:
    - polarity: -1 (负面), 0 (中性), 1 (正面)
    - intensity: -1.0 到 1.0 的连续值
    - confidence: 0.0 到 1.0 的置信度
    - rules_applied: 应用的规则列表
    """
    
    def __init__(self):
        self.db = get_db()
        self._model = None
        self._tokenizer = None
        self._ensure_table_exists()
        print("[实时情感分析] 服务已初始化")
    
    def _ensure_table_exists(self):
        """确保数据库表存在"""
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS realtime_sentiment_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL UNIQUE,
                    polarity INTEGER NOT NULL,
                    intensity REAL NOT NULL,
                    confidence REAL,
                    raw_score REAL,
                    rules_applied TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            
            self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_realtime_sentiment_message 
                ON realtime_sentiment_cache(message_id)
            """)
            
            self.db.commit()
            
        except Exception as e:
            print(f"[实时情感分析] 创建表失败: {e}")
    
    def _load_model(self):
        """延迟加载RoBERTa模型"""
        if self._model is None:
            try:
                from transformers import AutoTokenizer, AutoModelForSequenceClassification
                import torch
                
                print("[实时情感分析] 正在加载 RoBERTa-small 模型...")
                
                # 使用中文RoBERTa-small模型
                model_name = "hfl/chinese-roberta-wwm-ext"
                
                self._tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    model_name,
                    num_labels=3,  # 3分类:负面/中性/正面
                    ignore_mismatched_sizes=True  # 忽略分类头大小不匹配
                )
                
                # 设置为评估模式
                self._model.eval()
                
                # 检测GPU
                if torch.cuda.is_available():
                    self._model = self._model.cuda()
                    device = "cuda"
                    print(f"[实时情感分析] 使用GPU: {torch.cuda.get_device_name(0)}")
                else:
                    device = "cpu"
                    print("[实时情感分析] 使用CPU模式")
                
                print(f"[实时情感分析] 模型加载成功: {model_name} (设备: {device})")
                
            except ImportError:
                print("[实时情感分析] 警告: transformers未安装")
                print("请运行: pip install transformers")
                raise
            except Exception as e:
                print(f"[实时情感分析] 模型加载失败: {e}")
                raise
    
    # ========== 预处理 ==========
    
    def _preprocess(self, text: str) -> Dict[str, Any]:
        """预处理文本
        
        Returns:
            {
                'cleaned_text': str,  # 清洗后的文本
                'emojis': list,       # 提取的表情符号
                'slangs': list,       # 识别的网络用语
                'has_sarcasm': bool,  # 是否包含反讽
                'is_perfunctory': bool  # 是否为敷衍
            }
        """
        if not text or not text.strip():
            return {
                'cleaned_text': '',
                'emojis': [],
                'slangs': [],
                'has_sarcasm': False,
                'is_perfunctory': True
            }
        
        # 1. 提取表情符号
        emojis = []
        for emoji, info in EMOJI_SENTIMENT.items():
            if emoji in text:
                emojis.append({'emoji': emoji, 'info': info})
        
        # 2. 识别网络用语
        slangs = []
        words = jieba.lcut(text)
        for word in words:
            slang_info = get_slang_info(word)
            if slang_info:
                slangs.append({'word': word, 'info': slang_info})
        
        # 3. 检测反讽和敷衍
        has_sarcasm = contains_sarcasm(text)
        is_perfunc = is_perfunctory(text)
        
        # 4. 清洗文本(保留表情和网络用语,只去除多余空格)
        cleaned_text = re.sub(r'\s+', ' ', text).strip()
        
        return {
            'cleaned_text': cleaned_text,
            'emojis': emojis,
            'slangs': slangs,
            'has_sarcasm': has_sarcasm,
            'is_perfunctory': is_perfunc
        }
    
    # ========== 特征提取 ==========
    
    def _extract_features(self, text: str) -> Dict[str, Any]:
        """提取文本特征"""
        words = jieba.lcut(text)
        
        features = {
            # 词汇特征
            'emotion_words': [],
            'degree_words': [],
            'negation_words': [],
            
            # 句法特征
            'has_transition': False,
            'transition_position': -1,
            'is_question': False,
            
            # 统计特征
            'length': len(text),
            'word_count': len(words),
            'exclamation_count': text.count('!') + text.count('!'),
            'question_count': text.count('?') + text.count('?'),
            'ellipsis_count': text.count('...') + text.count('…'),
        }
        
        # 提取情感词
        for word in words:
            score = get_sentiment_word_score(word)
            if score != 0.0:
                features['emotion_words'].append({'word': word, 'score': score})
        
        # 提取程度词
        for word in words:
            is_degree, level = is_degree_word(word)
            if is_degree:
                features['degree_words'].append({'word': word, 'level': level})
        
        # 提取否定词
        for word in words:
            if is_negation_word(word):
                features['negation_words'].append(word)
        
        # 检测转折
        for i, word in enumerate(words):
            if is_transition_word(word):
                features['has_transition'] = True
                features['transition_position'] = i
                break
        
        # 检测疑问句
        features['is_question'] = text.endswith('?') or text.endswith('?') or '吗' in text
        
        return features
    
    # ========== 模型推理 ==========
    
    def _model_predict(self, text: str) -> Dict[str, Any]:
        """使用RoBERTa模型进行预测
        
        Returns:
            {
                'polarity': int,      # -1/0/1
                'raw_score': float,   # 原始分数
                'confidence': float,  # 置信度
                'probabilities': list # 各类别概率
            }
        """
        try:
            # 加载模型
            self._load_model()
            
            import torch
            
            # Tokenize
            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True
            )
            
            # 移动到GPU(如果可用)
            if torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}
            
            # 推理
            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits
                probabilities = torch.softmax(logits, dim=1)[0]
            
            # 转换为numpy
            probs = probabilities.cpu().numpy().tolist()
            
            # 获取预测类别(0=负面, 1=中性, 2=正面)
            predicted_class = probabilities.argmax().item()
            confidence = probabilities.max().item()
            
            # 转换为-1/0/1
            polarity_map = {0: -1, 1: 0, 2: 1}
            polarity = polarity_map[predicted_class]
            
            # 计算原始分数(-1到1)
            raw_score = probs[2] - probs[0]  # 正面概率 - 负面概率
            
            return {
                'polarity': polarity,
                'raw_score': raw_score,
                'confidence': confidence,
                'probabilities': probs
            }
            
        except Exception as e:
            print(f"[实时情感分析] 模型推理失败: {e}")
            # 失败时返回中性
            return {
                'polarity': 0,
                'raw_score': 0.0,
                'confidence': 0.0,
                'probabilities': [0.33, 0.34, 0.33]
            }
    
    # ========== 规则增强 ==========
    
    def _apply_rules(
        self,
        model_result: Dict[str, Any],
        preprocess_result: Dict[str, Any],
        features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """应用规则增强
        
        Returns:
            {
                'polarity': int,
                'intensity': float,
                'confidence': float,
                'rules_applied': list
            }
        """
        polarity = model_result['polarity']
        raw_score = model_result['raw_score']
        confidence = model_result['confidence']
        rules_applied = []
        
        # 规则1: 表情符号规则(优先级最高)
        if preprocess_result['emojis']:
            emoji_sentiments = [e['info']['sentiment'] for e in preprocess_result['emojis']]
            emoji_intensities = [e['info']['intensity'] for e in preprocess_result['emojis']]
            
            # 如果有强烈表情,优先采用
            strong_emojis = [e for e in preprocess_result['emojis'] 
                           if abs(e['info']['intensity']) > 0.8]
            
            if strong_emojis:
                avg_intensity = sum(e['info']['intensity'] for e in strong_emojis) / len(strong_emojis)
                
                if avg_intensity > 0.5:
                    polarity = 1
                    raw_score = max(raw_score, avg_intensity)
                    rules_applied.append('强烈正面表情')
                elif avg_intensity < -0.5:
                    polarity = -1
                    raw_score = min(raw_score, avg_intensity)
                    rules_applied.append('强烈负面表情')
                
                confidence = max(confidence, 0.85)
        
        # 规则2: 网络用语规则
        if preprocess_result['slangs']:
            slang_sentiments = [s['info']['sentiment'] for s in preprocess_result['slangs']]
            slang_intensities = [s['info']['intensity'] for s in preprocess_result['slangs']]
            
            avg_slang_intensity = sum(slang_intensities) / len(slang_intensities)
            
            # 网络用语增强
            if abs(avg_slang_intensity) > 0.7:
                raw_score = (raw_score + avg_slang_intensity) / 2
                rules_applied.append('网络用语增强')
        
        # 规则3: 转折规则
        if features['has_transition']:
            # 转折后的内容更重要
            rules_applied.append('转折规则')
            # 这里简化处理,实际应该分析转折后的内容
        
        # 规则4: 否定规则
        if features['negation_words']:
            # 简单的否定翻转(实际应该更精细)
            if len(features['negation_words']) % 2 == 1:  # 奇数个否定词
                polarity = -polarity
                raw_score = -raw_score
                rules_applied.append('否定翻转')
        
        # 规则5: 程度增强规则
        if features['degree_words']:
            strong_degrees = [d for d in features['degree_words'] if d['level'] == 'strong']
            if strong_degrees:
                raw_score *= 1.2  # 增强20%
                rules_applied.append('程度增强')
        
        # 规则6: 反讽检测
        if preprocess_result['has_sarcasm']:
            if polarity == 1:  # 如果模型判断为正面,但有反讽
                confidence *= 0.5  # 降低置信度
                rules_applied.append('反讽检测-降低置信度')
        
        # 规则7: 敷衍检测
        if preprocess_result['is_perfunctory']:
            polarity = 0
            raw_score = 0.0
            confidence = max(confidence, 0.7)
            rules_applied.append('敷衍回复')
        
        # 计算最终强度
        intensity = max(min(raw_score, 1.0), -1.0)
        
        # 重新确定极性(基于强度)
        if intensity > 0.3:
            polarity = 1
        elif intensity < -0.3:
            polarity = -1
        else:
            polarity = 0
        
        return {
            'polarity': polarity,
            'intensity': round(intensity, 4),
            'confidence': round(confidence, 4),
            'rules_applied': rules_applied
        }
    
    # ========== 主要API ==========
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """分析单条消息的情感
        
        Args:
            text: 待分析的文本
        
        Returns:
            {
                'polarity': -1/0/1,
                'intensity': -1.0到1.0,
                'confidence': 0.0到1.0,
                'rules_applied': [...]
            }
        """
        # 1. 预处理
        preprocess_result = self._preprocess(text)
        
        if not preprocess_result['cleaned_text']:
            return {
                'polarity': 0,
                'intensity': 0.0,
                'confidence': 0.0,
                'rules_applied': ['空文本']
            }
        
        # 2. 特征提取
        features = self._extract_features(preprocess_result['cleaned_text'])
        
        # 3. 模型预测
        model_result = self._model_predict(preprocess_result['cleaned_text'])
        
        # 4. 规则增强
        final_result = self._apply_rules(model_result, preprocess_result, features)
        
        return final_result
    
    def analyze_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """批量分析多条消息
        
        Args:
            texts: 文本列表
        
        Returns:
            结果列表
        """
        results = []
        for text in texts:
            try:
                result = self.analyze(text)
                results.append(result)
            except Exception as e:
                print(f"[实时情感分析] 批量分析失败: {e}")
                results.append({
                    'polarity': 0,
                    'intensity': 0.0,
                    'confidence': 0.0,
                    'rules_applied': ['分析失败']
                })
        return results
    
    def analyze_and_cache(self, message_id: int, text: str):
        """分析并缓存到数据库
        
        Args:
            message_id: 消息ID
            text: 消息文本
        """
        try:
            # 分析
            result = self.analyze(text)
            
            # 序列化规则列表
            rules_json = json.dumps(result['rules_applied'], ensure_ascii=False)
            
            # 保存到数据库
            self.db.execute("""
                INSERT OR REPLACE INTO realtime_sentiment_cache
                (message_id, polarity, intensity, confidence, raw_score, rules_applied, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                message_id,
                result['polarity'],
                result['intensity'],
                result['confidence'],
                result.get('raw_score', result['intensity']),
                rules_json,
                int(time.time())
            ))
            
            self.db.commit()
            
            # 格式化输出
            polarity_text = {-1: '负面', 0: '中性', 1: '正面'}[result['polarity']]
            intensity_text = f"{result['intensity']:+.2f}"  # 带符号的强度
            confidence_text = f"{result['confidence']:.0%}"  # 百分比
            
            # 构建输出信息
            output_parts = [
                f"[实时情感分析] {polarity_text}",
                f"强度={intensity_text}",
                f"置信度={confidence_text}"
            ]
            
            # 如果有应用的规则,也显示
            if result['rules_applied']:
                rules_text = ', '.join(result['rules_applied'][:2])  # 最多显示2个规则
                if len(result['rules_applied']) > 2:
                    rules_text += '...'
                output_parts.append(f"规则=[{rules_text}]")
            
            print(' | '.join(output_parts))
            
        except Exception as e:
            print(f"[实时情感分析] 缓存失败 (message_id={message_id}): {e}")
    
    def get_from_cache(self, message_id: int) -> Optional[Dict[str, Any]]:
        """从缓存读取情感分析结果
        
        Args:
            message_id: 消息ID
        
        Returns:
            结果字典或None
        """
        try:
            cursor = self.db.execute("""
                SELECT polarity, intensity, confidence, rules_applied
                FROM realtime_sentiment_cache
                WHERE message_id = ?
            """, (message_id,))
            
            row = cursor.fetchone()
            
            if not row:
                return None
            
            # 反序列化规则列表
            rules_applied = json.loads(row[3]) if row[3] else []
            
            return {
                'polarity': row[0],
                'intensity': row[1],
                'confidence': row[2],
                'rules_applied': rules_applied
            }
            
        except Exception as e:
            print(f"[实时情感分析] 缓存读取失败 (message_id={message_id}): {e}")
            return None
