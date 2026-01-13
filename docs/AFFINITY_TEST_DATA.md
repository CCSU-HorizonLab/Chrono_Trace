# 好感度分析测试数据说明

**功能**: 002-affinity-analysis
**文档类型**: 测试数据说明
**最后更新**: 2026-01-13

---

## 概述

本文档说明好感度分析功能所需的测试数据文件及其使用方法。

## 数据文件列表

### 1. conversation_medium.json
- **路径**: `backend/tests/fixtures/conversation_medium.json`
- **描述**: 真实微信对话记录(仅文本消息)
- **来源**: 数据库对话ID 1773
- **消息总数**: 5,232条
- **文本消息**: 4,320条
- **生成时间**: 2026-01-11

**数据格式**:
```json
{
  "meta": {
    "conversation_id": 1773,
    "display_name": "wxid_anon_contact_b",
    "total_messages": 5232,
    "text_messages": 4320
  },
  "messages": [
    {
      "id": 1,
      "conversation_id": 1773,
      "sender": "user",
      "is_sender": 1,
      "content": "消息内容",
      "timestamp": 1234567890,
      "message_type": 1
    }
  ]
}
```

### 2. conversation_labeled.json
- **路径**: `backend/tests/fixtures/conversation_labeled.json`
- **描述**: 已标注的情感数据
- **消息数量**: 100条
- **用途**: 验证SnowNLP情感分析准确率

**数据格式**:
```json
{
  "meta": {
    "source_conversation_id": 1773,
    "total_annotated": 100,
    "annotator": "ting",
    "annotated_at": "2026-01-11",
    "purpose": "验证SnowNLP情感分析准确率"
  },
  "annotated_messages": [
    {
      "id": 1,
      "content": "消息内容",
      "is_sender": 1,
      "timestamp": 0,
      "annotation": {
        "expected_polarity": 1,
        "expected_intensity": 0.6,
        "reason": "积极回应波浪号表示友好",
        "notes": ""
      }
    }
  ]
}
```

### 3. conversation_annotation_template.csv
- **路径**: `backend/tests/fixtures/conversation_annotation_template.csv`
- **描述**: 情感标注模板(Excel格式,扩展名为.csv)
- **消息数量**: 100条
- **用途**: 手工标注情感极性和强度

**字段说明**:
| 字段 | 说明 | 取值范围 |
|------|------|---------|
| id | 消息ID | 数字 |
| content | 消息内容 | 文本 |
| is_sender | 发送者 | 0=对方, 1=用户 |
| expected_polarity | 期望极性 | -1=负面, 0=中性, 1=正面 |
| expected_intensity | 期望强度 | -1.0到1.0 |
| reason | 标注理由 | 文本说明 |
| notes | 备注 | 可选 |

**标注示例**:
```csv
id,content,is_sender,expected_polarity,expected_intensity,reason,notes
1,"好的~",1,1,0.6,积极回应波浪号表示友好,
2,"什么意思",0,0,0.0,中性询问无情感倾向,
3,"我也很困",0,-0.3,-0.3,表达疲惫轻微负面,
```

## 情感标注指南

### 极性判断 (expected_polarity)

- **正面(1)**: 开心、谢谢、喜欢、幸福、哈哈等
- **中性(0)**: 询问、陈述、事实、普通问候等
- **负面(-1)**: 讨厌、生气、难过、痛苦、烦躁等

### 强度判断 (expected_intensity)

**正面强度**:
- **1.0**: 最强烈正面(狂喜、深爱)
- **0.5-0.7**: 明显正面(开心、感谢)
- **0.1-0.3**: 轻微正面(礼貌回应、友好语气)
- **0.0**: 完全中性

**负面强度**:
- **-0.1到-0.3**: 轻微负面(疲惫、轻微不满)
- **-0.5到-0.7**: 明显负面(生气、难过)
- **-1.0**: 最强烈负面(愤怒、绝望)

### 标注注意事项

1. **轻微正面/负面**: 如果能看出有轻微的情感倾向,极性就标注为1或-1,但强度设置较低(0.1-0.3或-0.1到-0.3)
2. **礼貌用语**: "好的"、"嗯嗯"、"~"等通常视为轻微正面(极性1,强度0.2-0.4)
3. **疑问句**: 询问类通常为中性,除非有明显的情感倾向
4. **表情符号**: 如果有emoji,需要结合上下文判断

## 数据来源

- **对话ID**: 1773
- **导出时间**: 2026-01-11
- **数据库**: `backend/data/chrono_trace.db`

## 隐私保护

⚠️ **重要提示**:
- 所有数据均从真实微信对话导出
- 请勿在公开场合分享包含个人隐私信息的内容
- 测试数据仅供开发和验证使用

## 相关文档

- [Ting任务清单](../docs/TING_TASKS.md)
- [好感度分析完整任务](../specs/002-affinity-analysis/tasks.md)
- [开发指南](../docs/DEVELOPMENT.md)
