"""嵌入向量持久缓存（embedding_cache）维护工具。

用法：
    python clear_embedding_cache.py            # 容量报告（只读）
    python clear_embedding_cache.py --clear    # 全部清空
    python clear_embedding_cache.py --clear --model <repo_id>  # 只清指定模型
"""
import argparse
import sys
from pathlib import Path

# 添加后端根目录到 sys.path，以便能够导入 app 模块
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from app.db.connection import get_db
from app.services.analysis.embedding_cache_store import EmbeddingCacheStore


def main():
    parser = argparse.ArgumentParser(description="embedding_cache 维护工具")
    parser.add_argument("--clear", action="store_true", help="执行清理（缺省只出容量报告）")
    parser.add_argument("--model", default=None, help="只清理指定模型的向量（缺省全部）")
    args = parser.parse_args()

    print("=" * 50)
    print("    Chrono Trace - 嵌入缓存（L2）维护工具    ")
    print("=" * 50)

    try:
        stats = EmbeddingCacheStore.stats()
        print(f"[*] 当前共 {stats['rows']} 行，占用 {stats['bytes'] / 1024 / 1024:.1f} MB")
        for item in stats["by_model"]:
            print(f"    - {item['model']} @ {item['device']}: {item['rows']} 行")

        if not args.clear:
            print("[-] 只读模式。加 --clear 执行清理。")
            return

        db = get_db()
        # 触发一次连接确保 get_db 可用（stats 已保证）；实际删除走 purge
        deleted = EmbeddingCacheStore.purge(model=args.model)
        print(f"[+] 成功清理 {deleted} 行嵌入缓存！")

        # 清理后真空回收空间
        db.execute("VACUUM")
        print("[+] VACUUM 完成，磁盘空间已回收。")
    except Exception as exc:
        print(f"[!] 操作失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
