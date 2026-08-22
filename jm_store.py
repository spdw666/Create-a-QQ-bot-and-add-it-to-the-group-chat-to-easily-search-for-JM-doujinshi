# -*- coding: utf-8 -*-
"""JM娘的持久化任务记录。

只保存机器人调度所需的元数据，不保存 QQ 消息正文、图片或任何凭据。
每次操作使用独立连接，避免 asyncio 工作线程与主线程共享 sqlite 连接。
"""
import os
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


def get_job_by_recent_index(group_id, user_id, index):
    """获取“我的下载”显示的第 index 条记录（1-based）。"""
    if index < 1:
        return None
    jobs = list_jobs(group_id, user_id, limit=index)
    return jobs[index - 1] if len(jobs) >= index else None
