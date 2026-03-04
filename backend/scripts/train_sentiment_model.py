"""
中文情感分析模型微调训练脚本

基座模型: hfl/chinese-roberta-wwm-ext
目标: 3分类 (0=负面, 1=正面, 2=中性)

训练逻辑说明:
===========

整体流程:
  标注CSV → 加载数据 → 划分训练集/验证集 → 加载预训练模型 → 微调训练 → 评估 → 保存

详细步骤:
  1. 读取标注好的CSV文件,过滤掉label为空的行
  2. 将数据按 85/15 比例随机划分为训练集和验证集
  3. 加载hfl/chinese-roberta-wwm-ext预训练模型(已经学会了中文语义理解)
  4. 在模型顶部添加一个3分类头(一个线性层,将768维特征映射到3个类别)
  5. 用训练集数据反复训练:
     - 每条文本 → tokenizer编码 → 模型前向传播 → 计算损失 → 反向传播更新权重
     - 分类头的权重从随机初始化开始,通过训练学习正确的分类
     - 预训练模型的权重也会被微调,让它更适应聊天文本
  6. 每个epoch结束后在验证集上评估准确率
  7. 训练完成后保存整个模型到本地目录

使用方法:
    cd backend
    python scripts/train_sentiment_model.py
"""

import csv
import os
import sys
import time
import random
from pathlib import Path

# 配置
TRAINING_CSV = os.path.join(os.path.dirname(__file__), '..', 'data', 'training', 'sentiment_training.csv')
MODEL_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'models', 'sentiment_3class')
BASE_MODEL = 'hfl/chinese-roberta-wwm-ext'

# 训练超参数
EPOCHS = 5              # 训练轮数(数据量少时5轮足够)
BATCH_SIZE = 16         # 每批处理16条数据
LEARNING_RATE = 2e-5    # 学习率(微调推荐2e-5)
MAX_LENGTH = 128        # 最大文本长度(聊天消息一般很短)
WARMUP_RATIO = 0.1      # 预热比例(前10%的步骤逐渐提高学习率)
WEIGHT_DECAY = 0.01     # 权重衰减(防止过拟合)
SEED = 42               # 随机种子(保证可复现)

# 配置HuggingFace镜像站
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'


def load_data(csv_path):
    """
    读取标注CSV,返回 (texts, labels) 列表
    自动过滤掉label为空的行
    """
    texts = []
    labels = []
    skipped = 0
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = row.get('text', '').strip()
            label_str = row.get('label', '').strip()
            
            # 跳过空行
            if not text or not label_str:
                skipped += 1
                continue
            
            try:
                label = int(label_str)
                if label not in (0, 1, 2):
                    print(f"⚠️ 无效标签 '{label_str}',跳过: {text[:30]}")
                    skipped += 1
                    continue
                texts.append(text)
                labels.append(label)
            except ValueError:
                print(f"⚠️ 标签解析失败 '{label_str}',跳过: {text[:30]}")
                skipped += 1
    
    print(f"✅ 读取 {len(texts)} 条有效数据 (跳过 {skipped} 条)")
    
    # 统计各类别
    from collections import Counter
    counts = Counter(labels)
    print(f"   负面(0): {counts.get(0, 0)} 条")
    print(f"   正面(1): {counts.get(1, 0)} 条")
    print(f"   中性(2): {counts.get(2, 0)} 条")
    
    return texts, labels


def split_data(texts, labels, test_ratio=0.15):
    """
    随机划分训练集和验证集
    保证各类别比例一致(分层划分)
    """
    random.seed(SEED)
    
    # 按类别分组
    class_indices = {}
    for i, label in enumerate(labels):
        if label not in class_indices:
            class_indices[label] = []
        class_indices[label].append(i)
    
    train_indices = []
    val_indices = []
    
    # 每个类别分别划分
    for label, indices in class_indices.items():
        random.shuffle(indices)
        split_point = max(1, int(len(indices) * (1 - test_ratio)))
        train_indices.extend(indices[:split_point])
        val_indices.extend(indices[split_point:])
    
    # 打乱顺序
    random.shuffle(train_indices)
    random.shuffle(val_indices)
    
    train_texts = [texts[i] for i in train_indices]
    train_labels = [labels[i] for i in train_indices]
    val_texts = [texts[i] for i in val_indices]
    val_labels = [labels[i] for i in val_indices]
    
    print(f"   训练集: {len(train_texts)} 条")
    print(f"   验证集: {len(val_texts)} 条")
    
    return train_texts, train_labels, val_texts, val_labels


class SentimentDataset:
    """将文本和标签封装为PyTorch Dataset"""
    
    def __init__(self, texts, labels, tokenizer, max_length):
        self.encodings = tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=max_length,
            return_tensors='pt'
        )
        self.labels = labels
    
    def __len__(self):
        return len(self.labels)
    
    def __getitem__(self, idx):
        import torch
        item = {key: val[idx] for key, val in self.encodings.items()}
        item['labels'] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item


def compute_metrics(predictions, labels):
    """计算准确率、各类别精确率和召回率"""
    import numpy as np
    
    preds = np.argmax(predictions, axis=1)
    accuracy = (preds == labels).mean()
    
    # 各类别准确率
    label_names = {0: '负面', 1: '正面', 2: '中性'}
    for label_id, name in label_names.items():
        mask = labels == label_id
        if mask.sum() > 0:
            class_acc = (preds[mask] == labels[mask]).mean()
            print(f"      {name}: {class_acc:.1%} ({mask.sum()}条)")
    
    return accuracy


def train():
    """主训练流程"""
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    from torch.utils.data import DataLoader
    from torch.optim import AdamW
    from transformers import get_linear_schedule_with_warmup
    import numpy as np
    
    print("=" * 60)
    print("中文情感分析模型微调训练")
    print("=" * 60)
    
    # ======== 第1步: 加载数据 ========
    print(f"\n📦 步骤1: 加载标注数据...")
    if not os.path.exists(TRAINING_CSV):
        print(f"❌ 找不到训练数据: {TRAINING_CSV}")
        return
    
    texts, labels = load_data(TRAINING_CSV)
    if len(texts) < 20:
        print("❌ 有效数据太少(至少需要20条),请补充标注")
        return
    
    # ======== 第2步: 划分数据集 ========
    print(f"\n📊 步骤2: 划分训练集/验证集...")
    train_texts, train_labels, val_texts, val_labels = split_data(texts, labels)
    
    # ======== 第3步: 加载预训练模型 ========
    print(f"\n🤖 步骤3: 加载基座模型 {BASE_MODEL}...")
    print("   (首次运行需要下载约400MB,后续从缓存加载)")
    
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    
    # num_labels=3: 告诉模型输出3个类别的概率
    # 这会在预训练模型顶部添加一个线性分类层: 768维 → 3维
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=3
    )
    
    device = 'cpu'
    model.to(device)
    print(f"   设备: {device}")
    print(f"   模型参数量: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")
    
    # ======== 第4步: 准备数据加载器 ========
    print(f"\n📐 步骤4: 编码文本数据...")
    train_dataset = SentimentDataset(train_texts, train_labels, tokenizer, MAX_LENGTH)
    val_dataset = SentimentDataset(val_texts, val_labels, tokenizer, MAX_LENGTH)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE)
    
    # ======== 第5步: 配置优化器 ========
    total_steps = len(train_loader) * EPOCHS
    warmup_steps = int(total_steps * WARMUP_RATIO)
    
    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)
    
    print(f"   总训练步数: {total_steps}")
    print(f"   预热步数: {warmup_steps}")
    
    # ======== 第6步: 训练循环 ========
    print(f"\n🏋️ 步骤5: 开始训练 ({EPOCHS} 轮)...")
    print("-" * 60)
    
    best_accuracy = 0
    best_epoch = 0
    
    for epoch in range(EPOCHS):
        # --- 训练阶段 ---
        model.train()
        total_loss = 0
        step_count = 0
        
        for batch in train_loader:
            # 将数据移到设备
            batch = {k: v.to(device) for k, v in batch.items()}
            
            # 前向传播: 输入文本 → 模型 → 损失值
            outputs = model(**batch)
            loss = outputs.loss
            
            # 反向传播: 计算梯度
            loss.backward()
            
            # 梯度裁剪(防止梯度爆炸)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            
            # 更新权重
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            
            total_loss += loss.item()
            step_count += 1
        
        avg_loss = total_loss / step_count
        
        # --- 验证阶段 ---
        model.eval()
        all_preds = []
        all_labels = []
        
        with torch.no_grad():
            for batch in val_loader:
                batch_on_device = {k: v.to(device) for k, v in batch.items()}
                outputs = model(**batch_on_device)
                preds = outputs.logits.cpu().numpy()
                label_ids = batch['labels'].numpy()
                all_preds.append(preds)
                all_labels.append(label_ids)
        
        all_preds = np.concatenate(all_preds)
        all_labels = np.concatenate(all_labels)
        
        accuracy = compute_metrics(all_preds, all_labels)
        
        # 记录最佳
        marker = ""
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_epoch = epoch + 1
            marker = " ← 最佳"
        
        print(f"   Epoch {epoch+1}/{EPOCHS} | 损失: {avg_loss:.4f} | 验证准确率: {accuracy:.1%}{marker}")
    
    print("-" * 60)
    print(f"   最佳准确率: {best_accuracy:.1%} (第{best_epoch}轮)")
    
    # ======== 第7步: 保存模型 ========
    print(f"\n💾 步骤6: 保存微调后的模型...")
    os.makedirs(MODEL_OUTPUT_DIR, exist_ok=True)
    
    model.save_pretrained(MODEL_OUTPUT_DIR)
    tokenizer.save_pretrained(MODEL_OUTPUT_DIR)
    
    # 保存标签映射
    import json
    label_map = {"0": "negative", "1": "positive", "2": "neutral"}
    with open(os.path.join(MODEL_OUTPUT_DIR, 'label_map.json'), 'w', encoding='utf-8') as f:
        json.dump(label_map, f, ensure_ascii=False, indent=2)
    
    print(f"   模型已保存到: {MODEL_OUTPUT_DIR}")
    
    # ======== 第8步: 快速验证 ========
    print(f"\n🧪 步骤7: 快速验证...")
    test_texts = [
        "今天心情超好😊",
        "去死吧",
        "嗯知道了",
        "太开心了",
        "烦死了",
        "你在干嘛",
        "那你好棒棒噢",
        "emo了",
        "还可以吧",
        "谢谢你一直陪着我",
    ]
    
    model.eval()
    label_names = {0: '负面', 1: '正面', 2: '中性'}
    
    for text in test_texts:
        inputs = tokenizer(text, return_tensors='pt', truncation=True, max_length=MAX_LENGTH, padding=True)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1)[0]
            pred = probs.argmax().item()
            confidence = probs.max().item()
        
        print(f"   '{text}' → {label_names[pred]} (置信度:{confidence:.0%})")
    
    # 完成
    print(f"\n{'=' * 60}")
    print("✅ 训练完成!")
    print("=" * 60)
    print(f"\n📋 下一步:")
    print(f"   告诉我训练结果,我将把模型集成到项目中")
    print(f"   模型路径: {MODEL_OUTPUT_DIR}")


if __name__ == '__main__':
    start_time = time.time()
    train()
    elapsed = time.time() - start_time
    print(f"\n⏱️ 总耗时: {elapsed:.1f}秒")
