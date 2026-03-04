"""
导出消息数据用于情感分析标注

功能:
1. 从数据库导出已有的文本消息
2. 生成预填充的微信聊天风格样本
3. 输出为CSV文件供用户标注

标签定义: 0=负面, 1=正面, 2=中性

使用方法:
    cd backend
    python scripts/export_for_labeling.py
"""

import csv
import os
import sqlite3
import sys

# 添加backend到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'chrono_trace.db')

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'training')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 输出文件
EXPORT_CSV = os.path.join(OUTPUT_DIR, 'exported_messages.csv')       # 从数据库导出的消息
TEMPLATE_CSV = os.path.join(OUTPUT_DIR, 'sentiment_training.csv')    # 最终标注文件(含预填充)


def export_from_database():
    """从数据库导出文本消息"""
    if not os.path.exists(DB_PATH):
        print(f"⚠️ 数据库不存在: {DB_PATH}")
        print("如果你还没有导入过微信数据,可以跳过此步骤,直接使用预填充模板。")
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    messages = []
    
    # 1. 从历史消息表导出
    try:
        cursor = conn.execute("""
            SELECT content 
            FROM messages 
            WHERE message_type = 1 
              AND content IS NOT NULL 
              AND content != ''
              AND LENGTH(content) >= 2
              AND LENGTH(content) <= 100
            ORDER BY RANDOM()
            LIMIT 300
        """)
        for row in cursor:
            content = row['content'].strip()
            # 过滤掉XML消息、系统消息等
            if content and not content.startswith('<') and not content.startswith('<?'):
                messages.append(content)
        print(f"✅ 从 messages 表导出 {len(messages)} 条")
    except Exception as e:
        print(f"⚠️ 读取 messages 表失败: {e}")
    
    # 2. 从实时消息缓存表导出
    try:
        cursor = conn.execute("""
            SELECT content 
            FROM realtime_message_buffer 
            WHERE content IS NOT NULL 
              AND content != ''
              AND sender_attr != 'system'
              AND LENGTH(content) >= 2
              AND LENGTH(content) <= 100
            ORDER BY RANDOM()
            LIMIT 200
        """)
        realtime_count = 0
        for row in cursor:
            content = row['content'].strip()
            if content and not content.startswith('<'):
                messages.append(content)
                realtime_count += 1
        print(f"✅ 从 realtime_message_buffer 表导出 {realtime_count} 条")
    except Exception as e:
        print(f"⚠️ 读取 realtime_message_buffer 表失败: {e}")
    
    conn.close()
    
    # 去重
    messages = list(set(messages))
    print(f"📊 去重后共 {len(messages)} 条唯一消息")
    
    # 保存导出的原始消息
    if messages:
        with open(EXPORT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['text', 'label'])
            for msg in messages:
                writer.writerow([msg, ''])  # label留空待标注
        print(f"💾 已保存到: {EXPORT_CSV}")
    
    return messages


def generate_prefilled_samples():
    """
    生成预填充的微信聊天风格样本
    包含正面/负面/中性三类,涵盖多种表达方式
    """
    samples = []
    
    # ===== 正面样本 (label=1) =====
    positive = [
        # 直接表达
        "太开心了！", "今天心情超好", "哈哈哈笑死我了", "好棒啊",
        "太好了！", "真的太感谢了", "爱了爱了", "幸福感满满",
        "今天运气真好", "nice!", "完美", "太赞了",
        # 带表情
        "开心😊", "哈哈哈😂", "爱你❤️", "加油💪", "太棒了🎉",
        "好可爱🥰", "真好看😍", "赞👍", "感动😭",
        # 网络用语
        "yyds", "绝绝子", "666", "给力", "奥利给",
        "太牛了", "你也太强了吧", "牛逼",
        # 社交场景
        "生日快乐🎂", "新年快乐", "恭喜恭喜", "好久不见想你了",
        "谢谢你一直陪着我", "和你在一起很开心", "你是最好的",
        "这个礼物我好喜欢", "今天约会好开心",
        # 回应类
        "好的呀", "没问题!", "当然可以", "我很愿意",
        "期待期待!", "我也是这么觉得",
    ]
    
    # ===== 负面样本 (label=0) =====
    negative = [
        # 直接表达
        "烦死了", "好烦啊", "心情很差", "不开心",
        "太难了", "受不了了", "要崩溃了", "心累",
        "好无聊", "太无语了", "讨厌", "恶心",
        # 极端负面
        "去死吧", "滚", "傻逼", "垃圾", "废物",
        "操", "妈的", "我恨你", "永远别联系我了",
        # 带表情
        "难受😢", "生气😡", "心碎💔", "无语😒", "崩溃😫",
        "想哭😭", "受伤了😞",
        # 网络用语
        "emo了", "破防了", "裂开了", "麻了", "服了",
        "无语子", "心态崩了",
        # 社交场景
        "你为什么不回我消息", "你是不是不在乎我了",
        "失望透了", "太让人寒心了", "我们分手吧",
        "你走吧别来找我了", "你变了",
        "每次都是我先找你", "算了你忙吧",
        # 抱怨
        "工作压力好大", "又加班了", "同事好烦",
        "今天被骂了", "什么破天气", "堵车堵疯了",
    ]
    
    # ===== 中性样本 (label=2) =====
    neutral = [
        # 日常对话
        "嗯", "哦", "好的", "知道了", "收到",
        "嗯嗯", "好吧", "行", "可以", "了解",
        # 信息交流
        "你在干嘛", "几点了", "今天天气怎么样",
        "明天有空吗", "你吃了吗", "在忙什么",
        "到了吗", "还要多久", "几点到",
        "你在哪", "地址发一下", "我到了",
        # 通知类
        "会议改到下午三点了", "我出门了", "马上到",
        "等一下", "稍等", "我去看看",
        "转账收到了", "文件发你了", "链接在这里",
        # 描述类
        "今天吃了火锅", "刚下班", "在回家路上",
        "下雨了", "周末在家", "刚起床",
        # 敷衍类(偏中性)
        "随便", "都行", "无所谓", "看你吧", "你定",
        "还行吧", "一般般", "还可以吧", "马马虎虎",
        "不好说", "看情况", "再说吧",
        # 询问类
        "这个怎么用", "你觉得呢", "有什么推荐吗",
    ]
    
    for text in positive:
        samples.append((text, 1))
    for text in negative:
        samples.append((text, 0))
    for text in neutral:
        samples.append((text, 2))
    
    return samples


def create_training_csv(db_messages, prefilled_samples):
    """合并数据库消息和预填充样本,生成最终标注文件"""
    
    with open(TEMPLATE_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['text', 'label'])
        
        # 1. 写入预填充样本(已标注)
        for text, label in prefilled_samples:
            writer.writerow([text, label])
        
        # 2. 写入数据库消息(待标注)
        # 排除已在预填充中出现的文本
        prefilled_texts = {s[0] for s in prefilled_samples}
        unlabeled_count = 0
        for msg in db_messages:
            if msg not in prefilled_texts:
                writer.writerow([msg, ''])  # label留空
                unlabeled_count += 1
    
    total = len(prefilled_samples) + unlabeled_count
    print(f"\n📄 最终标注文件: {TEMPLATE_CSV}")
    print(f"   已标注(预填充): {len(prefilled_samples)} 条")
    print(f"   待标注(你的数据): {unlabeled_count} 条")
    print(f"   总计: {total} 条")


def main():
    print("=" * 60)
    print("情感分析训练数据准备工具")
    print("=" * 60)
    
    # 1. 从数据库导出
    print("\n📦 步骤1: 从数据库导出消息...")
    db_messages = export_from_database()
    
    # 2. 生成预填充样本
    print("\n📝 步骤2: 生成预填充样本...")
    prefilled = generate_prefilled_samples()
    print(f"   正面: {sum(1 for _,l in prefilled if l==1)} 条")
    print(f"   负面: {sum(1 for _,l in prefilled if l==0)} 条")
    print(f"   中性: {sum(1 for _,l in prefilled if l==2)} 条")
    
    # 3. 合并生成最终文件
    print("\n📊 步骤3: 生成最终标注文件...")
    create_training_csv(db_messages, prefilled)
    
    # 4. 提示
    print("\n" + "=" * 60)
    print("✅ 数据准备完成!")
    print("=" * 60)
    print()
    print("📋 下一步操作:")
    print(f"   1. 打开文件: {TEMPLATE_CSV}")
    print("   2. 用Excel或文本编辑器打开")
    print("   3. 检查预填充样本的标签是否合理,不合理的请修改")
    print("   4. 给label为空的行标注标签:")
    print("      0 = 负面 (生气/难过/烦躁/攻击)")
    print("      1 = 正面 (开心/感谢/喜爱/鼓励)")
    print("      2 = 中性 (日常对话/信息交流/不带情感)")
    print("   5. 标注完成后保存文件")
    print("   6. 告诉我标注完成,我将进行微调训练")
    print()
    print("💡 提示:")
    print("   - 不确定的样本标为中性(2)")
    print("   - 不用标注全部,至少标注50条你自己的数据即可")
    print("   - 预填充的样本已经标好了,你只需要检查一下")


if __name__ == '__main__':
    main()
