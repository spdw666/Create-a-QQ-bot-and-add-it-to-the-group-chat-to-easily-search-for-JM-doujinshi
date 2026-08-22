# -*- coding: utf-8 -*-
"""JM娘的持久化任务记录。

只保存机器人调度所需的元数据，不保存 QQ 消息正文、图片或任何凭据。
每次操作使用独立连接，避免 asyncio 工作线程与主线程共享 sqlite 连接。
"""
import os
import json
import sqlite3
import time
import uuid


DEFAULT_DB_PATH = os.environ.get(
    'JM_DB_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'jmniang.sqlite3'),
)
_db_path = DEFAULT_DB_PATH


def set_db_path(path):
    """测试或运维迁移时显式指定数据库文件路径。"""
    global _db_path
    _db_path = path


def _connect():
    parent = os.path.dirname(os.path.abspath(_db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def _init(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS download_jobs (
            job_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            album_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'id',
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            finished_at INTEGER,
            total_pages INTEGER NOT NULL DEFAULT 0,
            zip_path TEXT NOT NULL DEFAULT '',
            upload_status TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT ''
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_download_jobs_owner_created
        ON download_jobs(group_id, user_id, created_at DESC)
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            subscription_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            target TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            cadence TEXT NOT NULL DEFAULT 'weekly',
            created_at INTEGER NOT NULL,
            last_checked_at INTEGER,
            last_digest_at INTEGER,
            seen_json TEXT NOT NULL DEFAULT '[]',
            pending_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(group_id, user_id, kind, target)
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_subscriptions_owner_created
        ON subscriptions(group_id, user_id, created_at DESC)
    ''')


def create_job(group_id, user_id, album_id, source='id'):
    """创建一个排队任务并返回其不可猜测的任务 ID。"""
    job_id = uuid.uuid4().hex
    now = int(time.time())
    with _connect() as conn:
        _init(conn)
        conn.execute(
            '''INSERT INTO download_jobs
               (job_id, group_id, user_id, album_id, source, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'queued', ?)''',
            (job_id, str(group_id), str(user_id), str(album_id), source, now),
        )
    return job_id


def update_job(job_id, *, status=None, title=None, total_pages=None,
               zip_path=None, upload_status=None, error=None, started=False,
               finished=False):
    """仅更新传入字段；状态变更由下载流程负责。"""
    fields, values = [], []
    if status is not None:
        fields.append('status = ?')
        values.append(status)
    if title is not None:
        fields.append('title = ?')
        values.append(str(title))
    if total_pages is not None:
        fields.append('total_pages = ?')
        values.append(int(total_pages or 0))
    if zip_path is not None:
        fields.append('zip_path = ?')
        values.append(str(zip_path))
    if upload_status is not None:
        fields.append('upload_status = ?')
        values.append(str(upload_status))
    if error is not None:
        fields.append('error = ?')
        values.append(str(error)[:500])
    now = int(time.time())
    if started:
        fields.append('started_at = ?')
        values.append(now)
    if finished:
        fields.append('finished_at = ?')
        values.append(now)
    if not fields:
        return
    values.append(job_id)
    with _connect() as conn:
        _init(conn)
        conn.execute('UPDATE download_jobs SET ' + ', '.join(fields) + ' WHERE job_id = ?', values)


def list_jobs(group_id, user_id, limit=10):
    """按最新优先读取当前群内该用户的任务/下载历史。"""
    with _connect() as conn:
        _init(conn)
        rows = conn.execute(
            '''SELECT job_id, album_id, title, source, status, created_at, started_at,
                      finished_at, total_pages, zip_path, upload_status, error
               FROM download_jobs
               WHERE group_id = ? AND user_id = ?
               ORDER BY created_at DESC LIMIT ?''',
            (str(group_id), str(user_id), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def count_active_jobs(group_id, user_id):
    """返回该用户处于排队或执行中的任务数。"""
    with _connect() as conn:
        _init(conn)
        row = conn.execute(
            '''SELECT COUNT(*) AS count FROM download_jobs
               WHERE group_id = ? AND user_id = ? AND status IN ('queued', 'running')''',
            (str(group_id), str(user_id)),
        ).fetchone()
    return int(row['count'])


def get_job(job_id):
    """按内部任务 ID 读取任务；不存在时返回 None。"""
    with _connect() as conn:
        _init(conn)
        row = conn.execute('SELECT * FROM download_jobs WHERE job_id = ?', (job_id,)).fetchone()
    return dict(row) if row else None


def cancel_latest_active_job(group_id, user_id):
    """取消该用户最新的排队/执行任务，并返回取消前的记录。"""
    now = int(time.time())
    with _connect() as conn:
        _init(conn)
        row = conn.execute(
            '''SELECT * FROM download_jobs
               WHERE group_id = ? AND user_id = ? AND status IN ('queued', 'running')
               ORDER BY created_at DESC LIMIT 1''',
            (str(group_id), str(user_id)),
        ).fetchone()
        if not row:
            return None
        job = dict(row)
        conn.execute(
            "UPDATE download_jobs SET status = 'cancelled', error = '用户取消', finished_at = ? WHERE job_id = ?",
            (now, job['job_id']),
        )
    return job


def add_subscription(group_id, user_id, kind, target, label='', cadence='weekly'):
    """保存作品/作者/标签订阅；重复订阅返回 False。"""
    subscription_id = uuid.uuid4().hex
    now = int(time.time())
    with _connect() as conn:
        _init(conn)
        try:
            conn.execute(
                '''INSERT INTO subscriptions
                   (subscription_id, group_id, user_id, kind, target, label, cadence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (subscription_id, str(group_id), str(user_id), kind, str(target), str(label), cadence, now),
            )
        except sqlite3.IntegrityError:
            return None
    return subscription_id


def list_subscriptions(group_id, user_id, limit=20):
    with _connect() as conn:
        _init(conn)
        rows = conn.execute(
            '''SELECT * FROM subscriptions WHERE group_id = ? AND user_id = ?
               ORDER BY created_at DESC LIMIT ?''',
            (str(group_id), str(user_id), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def list_all_subscriptions():
    """供后台聚合检查读取；不包含任何聊天正文。"""
    with _connect() as conn:
        _init(conn)
        rows = conn.execute('SELECT * FROM subscriptions ORDER BY created_at ASC').fetchall()
    return [dict(row) for row in rows]


def remove_subscription_by_recent_index(group_id, user_id, index):
    if index < 1:
        return None
    subscriptions = list_subscriptions(group_id, user_id, limit=index)
    if len(subscriptions) < index:
        return None
    subscription = subscriptions[index - 1]
    with _connect() as conn:
        _init(conn)
        conn.execute('DELETE FROM subscriptions WHERE subscription_id = ?', (subscription['subscription_id'],))
    return subscription


def set_subscription_cadence(group_id, user_id, cadence):
    with _connect() as conn:
        _init(conn)
        cur = conn.execute(
            'UPDATE subscriptions SET cadence = ? WHERE group_id = ? AND user_id = ?',
            (cadence, str(group_id), str(user_id)),
        )
    return cur.rowcount


def update_subscription_state(subscription_id, *, seen=None, pending=None,
                              checked=False, digested=False):
    fields, values = [], []
    if seen is not None:
        fields.append('seen_json = ?')
        values.append(json.dumps(seen, ensure_ascii=False)[:8000])
    if pending is not None:
        fields.append('pending_json = ?')
        values.append(json.dumps(pending, ensure_ascii=False)[:8000])
    now = int(time.time())
    if checked:
        fields.append('last_checked_at = ?')
        values.append(now)
    if digested:
        fields.append('last_digest_at = ?')
        values.append(now)
    if not fields:
        return
    values.append(subscription_id)
    with _connect() as conn:
        _init(conn)
        conn.execute('UPDATE subscriptions SET ' + ', '.join(fields) + ' WHERE subscription_id = ?', values)


def decode_subscription_json(value):
    try:
        decoded = json.loads(value or '[]')
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def list_active_jobs_all(limit=30):
    with _connect() as conn:
        _init(conn)
        rows = conn.execute(
            '''SELECT job_id, group_id, user_id, album_id, title, source, status, created_at
               FROM download_jobs WHERE status IN ('queued', 'running')
               ORDER BY created_at ASC LIMIT ?''', (int(limit),)
        ).fetchall()
    return [dict(row) for row in rows]


def cancel_job_by_prefix(job_prefix):
    """管理员按至少 6 位内部任务 ID 前缀取消排队/执行任务。"""
    prefix = str(job_prefix or '').strip().lower()
    if len(prefix) < 6:
        return None
    with _connect() as conn:
        _init(conn)
        rows = conn.execute(
            "SELECT * FROM download_jobs WHERE job_id LIKE ? AND status IN ('queued', 'running') LIMIT 2",
            (prefix + '%',),
        ).fetchall()
        if len(rows) != 1:
            return None
        job = dict(rows[0])
        conn.execute(
            "UPDATE download_jobs SET status = 'cancelled', error = '管理员取消', finished_at = ? WHERE job_id = ?",
            (int(time.time()), job['job_id']),
        )
    return job


def get_store_stats():
    with _connect() as conn:
        _init(conn)
        job_rows = conn.execute('SELECT status, COUNT(*) AS count FROM download_jobs GROUP BY status').fetchall()
        subscription_count = conn.execute('SELECT COUNT(*) AS count FROM subscriptions').fetchone()['count']
    return {'jobs': {row['status']: row['count'] for row in job_rows}, 'subscriptions': subscription_count}


def get_job_by_recent_index(group_id, user_id, index):
    """获取“我的下载”显示的第 index 条记录（1-based）。"""
    if index < 1:
        return None
    jobs = list_jobs(group_id, user_id, limit=index)
    return jobs[index - 1] if len(jobs) >= index else None
