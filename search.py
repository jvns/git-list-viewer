from emailindex import EmailIndex
from datetime import datetime

def search(db_path, repo_path, search_query):
    with EmailIndex(db_path, repo_path) as index:
        return _search(index, search_query)

def _search(index, search_query):
    # Get all unique message IDs that have been indexed
    # Build search condition
    search_condition = ""
    search_params = []
    if search_query:
        search_condition = """
            AND (subject LIKE ? OR from_name LIKE ? OR from_addr LIKE ?)
        """
        search_like = f"%{search_query}%"
        search_params = [search_like, search_like, search_like]

    cursor = index.conn.execute(f"""
        WITH filtered_messages AS (
            SELECT message_id, subject, from_name, from_addr, date_sent, root_message_id
            FROM messages
            WHERE (subject NOT LIKE 'Re:%' AND subject NOT LIKE 'RE:%')
              AND (subject NOT LIKE '% v2 %' AND subject NOT LIKE '% v3 %'
                   AND subject NOT LIKE '% v4 %' AND subject NOT LIKE '% v5 %'
                   AND subject NOT LIKE '% v6 %' AND subject NOT LIKE '% v7 %'
                   AND subject NOT LIKE '% v8 %' AND subject NOT LIKE '% v9 %')
              {search_condition}
        ),
        ranked_messages AS (
            SELECT message_id, subject, from_name, from_addr, date_sent, root_message_id,
                   ROW_NUMBER() OVER (PARTITION BY root_message_id ORDER BY date_sent ASC) as rn
            FROM filtered_messages
        ),
        thread_counts AS (
            SELECT root_message_id, COUNT(*) as thread_count
            FROM messages
            GROUP BY root_message_id
        )
        SELECT r.message_id, r.subject, r.from_name, r.from_addr, r.date_sent, t.thread_count
        FROM ranked_messages r
        JOIN thread_counts t ON r.root_message_id = t.root_message_id
        WHERE r.rn = 1
        ORDER BY r.date_sent DESC
        LIMIT 100
    """, search_params)

    threads = []
    for row in cursor.fetchall():
        threads.append({
            'message_id': row['message_id'],
            'subject': row['subject'],
            'from': f"{row['from_name']} <{row['from_addr']}>",
            'date': datetime.fromtimestamp(row['date_sent']).strftime('%Y-%m-%d'),
            'message_count': row['thread_count']
        })

    return threads
