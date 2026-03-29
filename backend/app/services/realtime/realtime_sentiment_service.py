"""Realtime sentiment analysis service."""

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import jieba
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from ...db.connection import get_db
from ..analysis.feature_extraction_config import (
    ANALYSIS_DEVICE_MODE_AUTO,
    ANALYSIS_DEVICE_MODE_CPU,
    ANALYSIS_DEVICE_MODE_GPU,
    FeatureExtractionConfig,
    normalize_analysis_device_mode,
)
from ..model_manager import ModelManager
from .sentiment_rules import (
    EMOJI_SENTIMENT,
    contains_sarcasm,
    get_sentiment_word_score,
    get_slang_info,
    is_degree_word,
    is_negation_word,
    is_perfunctory,
    is_transition_word,
)


def _safe_disable_dynamo(fn):
    """Best-effort guard against PyTorch dynamo issues."""
    try:
        import torch._dynamo

        if hasattr(torch._dynamo, "disable"):
            return torch._dynamo.disable(fn)
    except Exception:
        pass
    return fn


def singleton(cls):
    instances = {}
    lock = threading.Lock()

    def get_instance(*args, **kwargs):
        with lock:
            if cls not in instances:
                instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


logger = logging.getLogger(__name__)


@singleton
class RealtimeSentimentService:
    """Realtime sentiment classification with rule enhancement."""

    def __init__(self, skip_db_init: bool = False):
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        self._device_mode = FeatureExtractionConfig.from_settings().analysis_device_mode
        self._lock = threading.Lock()

        local_model_dir = Path(__file__).parent.parent.parent.parent / "data" / "models" / "sentiment_3class"
        self._model_manager = ModelManager(
            model_dir=str(local_model_dir),
            repo_id="tingting11/chrono-trace-sentiment",
        )

        if not skip_db_init:
            self._ensure_table_exists()

        self._model_manager.check_and_update_async()
        logger.debug("[实时情感分析] 服务初始化完成")

    def configure_device_mode(self, device_mode: Optional[str]) -> str:
        """Change target device mode and rebuild model lazily if needed."""
        normalized_mode = normalize_analysis_device_mode(device_mode)
        if normalized_mode == self._device_mode:
            return self._device_mode

        self._device_mode = normalized_mode
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        logger.info(f"[实时情感分析] 切换分析设备模式: {normalized_mode}")
        return self._device_mode

    def _resolve_runtime_device(self) -> str:
        if self._device_mode == ANALYSIS_DEVICE_MODE_CPU:
            return "cpu"
        if self._device_mode == ANALYSIS_DEVICE_MODE_GPU:
            if torch.cuda.is_available():
                return "cuda"
            logger.warning("[实时情感分析] 已选择 GPU 模式，但当前 CUDA 不可用，回退到 CPU")
            return "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _ensure_table_exists(self):
        """Ensure the realtime sentiment cache table exists."""
        try:
            get_db().execute(
                """
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
                """
            )
            get_db().execute(
                """
                CREATE INDEX IF NOT EXISTS idx_realtime_sentiment_message
                ON realtime_sentiment_cache(message_id)
                """
            )
            get_db().commit()
        except Exception as exc:
            logger.error(f"[实时情感分析] 创建表失败: {exc}")

    def is_ready(self) -> bool:
        return self._model is not None

    def _load_model(self):
        """Load the local classifier on the configured device."""
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            try:
                logger.debug("[实时情感分析] 正在加载情感分析模型...")
                if not self._model_manager.ensure_model_exists():
                    raise FileNotFoundError(
                        f"本地模型不存在: {self._model_manager.model_dir}"
                    )

                model_path = str(self._model_manager.model_dir)
                self._tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    model_path,
                    low_cpu_mem_usage=False,
                )

                target_device = self._resolve_runtime_device()
                if target_device == "cuda":
                    try:
                        gpu_name = torch.cuda.get_device_name(0)
                        self._model = self._model.to("cuda")
                        self._device = "cuda"
                        logger.info(f"[实时情感分析] 模型已迁移到 GPU: {gpu_name}")
                    except Exception as exc:
                        self._device = "cpu"
                        logger.warning(f"[实时情感分析] GPU 迁移失败，回退到 CPU: {exc}")
                else:
                    self._device = "cpu"

                self._model.eval()
                device_display = self._device.upper()
                if self._device == "cuda":
                    device_display = f"CUDA:0 ({torch.cuda.get_device_name(0)})"
                logger.info(
                    f"[实时情感分析] 模型加载成功 | 分类数: {self._model.config.num_labels} | 设备: {device_display}"
                )
            except ImportError:
                logger.warning("[实时情感分析] transformers 未安装")
                raise
            except Exception as exc:
                logger.error(f"[实时情感分析] 模型加载失败: {exc}")
                raise

    def _preprocess(self, text: str) -> Dict[str, Any]:
        """Extract rule-related metadata from raw text."""
        if not text or not text.strip():
            return {
                "cleaned_text": "",
                "emojis": [],
                "slangs": [],
                "has_sarcasm": False,
                "is_perfunctory": True,
            }

        emojis = []
        for emoji, info in EMOJI_SENTIMENT.items():
            if emoji in text:
                emojis.append({"emoji": emoji, "info": info})

        slangs = []
        for word in jieba.lcut(text):
            slang_info = get_slang_info(word)
            if slang_info:
                slangs.append({"word": word, "info": slang_info})

        return {
            "cleaned_text": re.sub(r"\s+", " ", text).strip(),
            "emojis": emojis,
            "slangs": slangs,
            "has_sarcasm": contains_sarcasm(text),
            "is_perfunctory": is_perfunctory(text),
        }

    def _extract_features(self, text: str) -> Dict[str, Any]:
        """Extract lexical features for rule enhancement."""
        words = jieba.lcut(text)
        features = {
            "emotion_words": [],
            "degree_words": [],
            "negation_words": [],
            "has_transition": False,
            "transition_position": -1,
            "is_question": False,
            "length": len(text),
            "word_count": len(words),
            "exclamation_count": text.count("!") + text.count("！"),
            "question_count": text.count("?") + text.count("？"),
            "ellipsis_count": text.count("...") + text.count("…"),
        }

        for word in words:
            score = get_sentiment_word_score(word)
            if score != 0.0:
                features["emotion_words"].append({"word": word, "score": score})

            is_degree, level = is_degree_word(word)
            if is_degree:
                features["degree_words"].append({"word": word, "level": level})

            if is_negation_word(word):
                features["negation_words"].append(word)

        for index, word in enumerate(words):
            if is_transition_word(word):
                features["has_transition"] = True
                features["transition_position"] = index
                break

        features["is_question"] = text.endswith("?") or text.endswith("？") or "吗" in text
        return features

    @_safe_disable_dynamo
    def _model_predict(self, text: str) -> Dict[str, Any]:
        """Run one forward pass for one text."""
        try:
            self._load_model()

            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            if self._device != "cpu":
                inputs = {key: value.to(self._device) for key, value in inputs.items()}

            with torch.no_grad():
                with self._lock:
                    outputs = self._model(**inputs)
                    probabilities = torch.softmax(outputs.logits, dim=1)[0]

            probs = probabilities.cpu().numpy().tolist()
            predicted_class = probabilities.argmax().item()
            confidence = float(probabilities.max().item())
            polarity = {0: -1, 1: 1, 2: 0}.get(predicted_class, 0)
            raw_score = probs[1] - probs[0] if len(probs) >= 3 else 0.0
            probs_3class = [
                probs[0],
                probs[2] if len(probs) >= 3 else 0.0,
                probs[1] if len(probs) >= 2 else 0.0,
            ]

            return {
                "polarity": polarity,
                "raw_score": raw_score,
                "confidence": confidence,
                "probabilities": probs_3class,
            }
        except Exception as exc:
            logger.error(f"[实时情感分析] 模型推理失败: {exc}")
            return {
                "polarity": 0,
                "raw_score": 0.0,
                "confidence": 0.0,
                "probabilities": [0.33, 0.34, 0.33],
            }

    @_safe_disable_dynamo
    def _model_predict_batch(self, texts: List[str], batch_size: int = 32) -> List[Dict[str, Any]]:
        """Run true batched inference for multiple texts."""
        try:
            self._load_model()
            all_results: List[Dict[str, Any]] = []

            for start in range(0, len(texts), batch_size):
                batch_texts = texts[start:start + batch_size]
                inputs = self._tokenizer(
                    batch_texts,
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                    padding=True,
                )

                if self._device != "cpu":
                    inputs = {key: value.to(self._device) for key, value in inputs.items()}

                with torch.no_grad():
                    with self._lock:
                        outputs = self._model(**inputs)
                        probabilities = torch.softmax(outputs.logits, dim=1)

                probs_batch = probabilities.cpu().numpy()
                for row in probs_batch:
                    probs = row.tolist()
                    predicted_class = int(row.argmax())
                    confidence = float(row.max())
                    polarity = {0: -1, 1: 1, 2: 0}.get(predicted_class, 0)
                    raw_score = probs[1] - probs[0] if len(probs) >= 3 else 0.0
                    probs_3class = [
                        probs[0],
                        probs[2] if len(probs) >= 3 else 0.0,
                        probs[1] if len(probs) >= 2 else 0.0,
                    ]
                    all_results.append({
                        "polarity": polarity,
                        "raw_score": raw_score,
                        "confidence": confidence,
                        "probabilities": probs_3class,
                    })

            return all_results
        except Exception as exc:
            logger.error(f"[实时情感分析] 批量模型推理失败: {exc}")
            return [
                {
                    "polarity": 0,
                    "raw_score": 0.0,
                    "confidence": 0.0,
                    "probabilities": [0.33, 0.34, 0.33],
                }
                for _ in texts
            ]

    def _apply_rules(
        self,
        model_result: Dict[str, Any],
        preprocess_result: Dict[str, Any],
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply heuristic rules on top of the classifier output."""
        polarity = model_result["polarity"]
        raw_score = model_result["raw_score"]
        confidence = model_result["confidence"]
        rules_applied = []

        if preprocess_result["emojis"]:
            strong_emojis = [
                item for item in preprocess_result["emojis"]
                if abs(item["info"]["intensity"]) > 0.8
            ]
            if strong_emojis:
                avg_intensity = sum(item["info"]["intensity"] for item in strong_emojis) / len(strong_emojis)
                if avg_intensity > 0.5:
                    polarity = 1
                    raw_score = max(raw_score, avg_intensity)
                    rules_applied.append("强烈正面表情")
                elif avg_intensity < -0.5:
                    polarity = -1
                    raw_score = min(raw_score, avg_intensity)
                    rules_applied.append("强烈负面表情")
                confidence = max(confidence, 0.85)

        if preprocess_result["slangs"]:
            slang_intensities = [item["info"]["intensity"] for item in preprocess_result["slangs"]]
            avg_slang_intensity = sum(slang_intensities) / len(slang_intensities)
            if abs(avg_slang_intensity) > 0.7:
                raw_score = (raw_score + avg_slang_intensity) / 2
                rules_applied.append("网络用语增强")

        if features["has_transition"]:
            rules_applied.append("转折规则")

        if features["negation_words"] and len(features["negation_words"]) % 2 == 1:
            polarity = -polarity
            raw_score = -raw_score
            rules_applied.append("否定翻转")

        if features["degree_words"]:
            strong_degrees = [item for item in features["degree_words"] if item["level"] == "strong"]
            if strong_degrees:
                raw_score *= 1.2
                rules_applied.append("程度增强")

        if preprocess_result["has_sarcasm"] and polarity == 1:
            confidence *= 0.5
            rules_applied.append("反讽检测")

        if preprocess_result["is_perfunctory"]:
            polarity = 0
            raw_score = 0.0
            confidence = max(confidence, 0.7)
            rules_applied.append("敷衍回复")

        intensity = max(min(raw_score, 1.0), -1.0)
        if intensity > 0.3:
            polarity = 1
        elif intensity < -0.3:
            polarity = -1
        else:
            polarity = 0

        return {
            "polarity": polarity,
            "intensity": round(intensity, 4),
            "confidence": round(confidence, 4),
            "rules_applied": rules_applied,
        }

    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyze one chat message."""
        preprocess_result = self._preprocess(text)
        if not preprocess_result["cleaned_text"]:
            return {
                "polarity": 0,
                "intensity": 0.0,
                "confidence": 0.0,
                "rules_applied": ["空文本"],
            }

        features = self._extract_features(preprocess_result["cleaned_text"])
        model_result = self._model_predict(preprocess_result["cleaned_text"])
        return self._apply_rules(model_result, preprocess_result, features)

    def analyze_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """Analyze many chat messages using batched model inference."""
        if not texts:
            return []

        empty_result = {
            "polarity": 0,
            "intensity": 0.0,
            "confidence": 0.0,
            "rules_applied": ["空文本"],
        }

        preprocess_results: List[Dict[str, Any]] = []
        features_list: List[Optional[Dict[str, Any]]] = []
        valid_indices: List[int] = []
        valid_texts: List[str] = []

        for index, text in enumerate(texts):
            try:
                preprocess_result = self._preprocess(text)
                preprocess_results.append(preprocess_result)
                if preprocess_result["cleaned_text"]:
                    features_list.append(self._extract_features(preprocess_result["cleaned_text"]))
                    valid_indices.append(index)
                    valid_texts.append(preprocess_result["cleaned_text"])
                else:
                    features_list.append(None)
            except Exception as exc:
                logger.error(f"[实时情感分析] 批量预处理失败: {exc}")
                preprocess_results.append({
                    "cleaned_text": "",
                    "emojis": [],
                    "slangs": [],
                    "has_sarcasm": False,
                    "is_perfunctory": True,
                })
                features_list.append(None)

        model_results_map: Dict[int, Dict[str, Any]] = {}
        if valid_texts:
            batch_model_results = self._model_predict_batch(valid_texts)
            for local_index, original_index in enumerate(valid_indices):
                if local_index < len(batch_model_results):
                    model_results_map[original_index] = batch_model_results[local_index]

        results: List[Dict[str, Any]] = []
        for index in range(len(texts)):
            model_result = model_results_map.get(index)
            feature_result = features_list[index] if index < len(features_list) else None
            preprocess_result = preprocess_results[index] if index < len(preprocess_results) else None

            if not model_result or not preprocess_result or feature_result is None:
                results.append(empty_result.copy())
                continue

            try:
                results.append(self._apply_rules(model_result, preprocess_result, feature_result))
            except Exception as exc:
                logger.error(f"[实时情感分析] 批量规则增强失败: {exc}")
                results.append(empty_result.copy())

        return results

    def analyze_and_cache(self, message_id: int, text: str):
        """Analyze one message and cache the result."""
        try:
            result = self.analyze(text)
            rules_json = json.dumps(result["rules_applied"], ensure_ascii=False)
            get_db().execute(
                """
                INSERT OR REPLACE INTO realtime_sentiment_cache
                (message_id, polarity, intensity, confidence, raw_score, rules_applied, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    result["polarity"],
                    result["intensity"],
                    result["confidence"],
                    result["intensity"],
                    rules_json,
                    int(time.time()),
                ),
            )
            get_db().commit()
        except Exception as exc:
            logger.error(f"[实时情感分析] 缓存失败 (message_id={message_id}): {exc}")

    def get_from_cache(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Read one cached realtime sentiment result."""
        try:
            cursor = get_db().execute(
                """
                SELECT polarity, intensity, confidence, rules_applied
                FROM realtime_sentiment_cache
                WHERE message_id = ?
                """,
                (message_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "polarity": row[0],
                "intensity": row[1],
                "confidence": row[2],
                "rules_applied": json.loads(row[3]) if row[3] else [],
            }
        except Exception as exc:
            logger.error(f"[实时情感分析] 缓存读取失败 (message_id={message_id}): {exc}")
            return None
