import sqlite3
import json

conn = sqlite3.connect('backend/data/chrono_trace.db')
cursor = conn.cursor()
cursor.execute('SELECT id, summary, suggestions_snapshot FROM session_threads ORDER BY id DESC LIMIT 5')

with open('db_check_result.txt', 'w', encoding='utf-8') as f:
    for row in cursor.fetchall():
        f.write(f"ID: {row[0]}\nSummary: {row[1]}\nSuggestions:\n")
        try:
            if row[2]:
                suggs = json.loads(row[2])
                f.write(json.dumps(suggs, indent=2, ensure_ascii=False) + "\n\n")
            else:
                f.write("None\n\n")
        except Exception as e:
            f.write(f"Error parsing json: {e}\n\n")

conn.close()
print("Success. Written to db_check_result.txt")
