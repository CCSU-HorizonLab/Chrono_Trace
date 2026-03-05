import sys
import os
from pathlib import Path

# 添加后端根目录到 sys.path，以便能够导入 app 模块
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from app.db.connection import get_db

def main():
    print("=" * 50)
    print("    Chrono Trace - 情感分析缓存清理工具    ")
    print("=" * 50)
    
    try:
        db = get_db()
        
        # 获取清空前的数量
        cursor = db.execute("SELECT COUNT(*) FROM sentiment_cache")
        count_before = cursor.fetchone()[0]
        
        print(f"[*] 找到 {count_before} 条历史情感分析缓存数据。")
        
        if count_before > 0:
            print("[*] 正在清空 sentiment_cache 表...")
            db.execute("DELETE FROM sentiment_cache")
            db.commit()
            print(f"[+] 成功清理 {count_before} 条情感缓存！")
        else:
            print("[-] 情感缓存已为空，跳过清理。")
            
        # 顺便清空亲密度总分缓存，强制所有会话重新完全分析
        cursor = db.execute("SELECT COUNT(*) FROM affinity_scores")
        affinity_count = cursor.fetchone()[0]
        if affinity_count > 0:
            print("[*] 正在清空 affinity_scores 表...")
            db.execute("DELETE FROM affinity_scores")
            db.commit()
            print(f"[+] 成功清理 {affinity_count} 条亲密度缓存！")
            
        print("\n[√] 全部清理完成！")
        print("接下来你需要：")
        print("1. [如果你开着应用] 先关闭并重启 app_dev.py")
        print("2. 在浏览器中打开亲密度分析页面")
        print("3. 选择会话后，点击【重新分析】")
        print("系统将使用精确的 RoBERTa 实时情感模型(带规则增强)重新生成所有分析报告。")
        
    except Exception as e:
        print(f"\n[X] 清理失败: {e}")

if __name__ == "__main__":
    main()
