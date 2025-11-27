"""测试新的解密器"""
import sys
sys.path.insert(0, 'backend')

from app.services.wechat.db_decryptor_v2 import WeChatDBDecryptorV2
from app.services.wechat.path_finder import WeChatPathFinder

def main():
    print("=== 测试微信V4解密器 ===\n")
    
    # 1. 查找数据库
    print("[步骤1] 查找数据库...")
    paths = WeChatPathFinder.find_all_wechat_dbs()
    
    if not paths:
        print("❌ 未找到微信数据库")
        return
    
    print(f"✅ 找到数据库")
    print(f"  路径: {paths['wechat_dir']}")
    print(f"  用户: {paths['current_user']}")
    print(f"  联系人: {paths['databases']['contact']}")
    print(f"  消息库: {len(paths['databases']['message'])} 个")
    
    # 2. 获取密钥
    print("\n[步骤2] 输入密钥")
    key = input("请输入32字节密钥(64位hex): ").strip()
    
    if len(key) != 64:
        print(f"❌ 密钥长度错误: {len(key)} (应为64)")
        return
    
    # 3. 验证密钥
    print("\n[步骤3] 验证密钥...")
    decryptor = WeChatDBDecryptorV2()
    
    # 先测试联系人库
    contact_db = paths['databases']['contact']
    if contact_db:
        print(f"  测试: {contact_db}")
        is_valid = decryptor.verify_key_from_file(contact_db, key)
        
        if is_valid:
            print("  ✅ 联系人库密钥正确")
        else:
            print("  ❌ 联系人库密钥错误")
            return
    
    # 测试消息库
    if paths['databases']['message']:
        msg_db = paths['databases']['message'][0]
        print(f"  测试: {msg_db}")
        is_valid = decryptor.verify_key_from_file(msg_db, key)
        
        if is_valid:
            print("  ✅ 消息库密钥正确")
        else:
            print("  ❌ 消息库密钥错误")
            return
    
    # 4. 测试解密
    print("\n[步骤4] 测试解密到临时文件...")
    import tempfile
    
    temp_file = tempfile.mktemp(suffix='.db')
    print(f"  输出: {temp_file}")
    
    try:
        decryptor.decrypt_database(contact_db, temp_file, key)
        print("  ✅ 解密成功!")
        
        # 验证解密后的数据库
        import sqlite3
        conn = sqlite3.connect(temp_file)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor]
        print(f"  表数量: {len(tables)}")
        print(f"  表列表: {tables[:5]}...")
        
        # 读取联系人数量
        if 'contact' in tables:
            cursor = conn.execute("SELECT COUNT(*) FROM contact")
            count = cursor.fetchone()[0]
            print(f"  联系人数量: {count}")
        
        conn.close()
        
        # 清理
        import os
        os.remove(temp_file)
        print("  ✅ 测试完成")
        
    except Exception as e:
        print(f"  ❌ 解密失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
