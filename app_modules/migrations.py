"""结构迁移的登记表：谁拥有哪张表、当前结构是第几版。

为什么要单独一个模块（方案 C05）：以前 server.py 在 import 时就悄悄把列加上、
把表建好，后台仓库那边也各自 CREATE TABLE 自己需要的表。于是有两个没人答得出的问题：
"这个字段是谁加的"、"后台能不能先于主应用上线"。这里把答案写成一处：

  * 业务表（users/profiles/社区/私信……）的唯一所有者是主应用，只有 server.py 会改它们；
  * ops_* 前缀的表所有者是后台运维 API，主应用不碰；
  * 每次动结构都要在 MIGRATIONS 追加一条并把 SCHEMA_VERSION 往上加，
    后台靠 /health/ready 里的 schema_version 判断"主服务够不够新"。

先兼容扩展、后清理旧列：加列时旧代码不看新列就行，删列要等确认没人用了再单独一版。
"""
import os
import sqlite3

# 生产库当前应该处在的结构版本。加一条 MIGRATIONS 就 +1。
SCHEMA_VERSION = 15

# (版本, 名称, 所有者, 说明)。名称要和 server.py 里那段动作对得上，
# 不然半年后没人知道第 7 版到底改了什么。
MIGRATIONS = (
    (1, "users.安全列", "app", "pw_salt / share_secret：口令加盐与公开链接密钥"),
    (2, "users.封号列", "app", "banned_at / ban_reason：后台封号要有落点"),
    (3, "profiles.每日语义列", "app", "day_mode / cycle_started_at / 邮箱 / 头像 / 属地"),
    (4, "email_codes+user_cities", "app", "邮箱验证码只存哈希；去过的城市增量维护"),
    (5, "checklist_state+ai_memory+kb_entries+cheers", "app", "采购清单、AI 记忆、检索缓存、访客打气"),
    (6, "sessions", "app", "会话从 users.token_hash 搬进独立表，支持多设备与单独撤销"),
    (7, "private_ai_answers+daily_modes+request_receipts", "app", "私聊问答、当日模式、写请求幂等回执"),
    (8, "daily_metrics+record_changes", "app", "每日指标快照与记录修改前像"),
    (9, "社区与私信全套", "app", "_community_schema：帖子/评论/点赞/@/通知/私信/反馈/举报"),
    (10, "users.临时口令恢复列", "app", "reset_expires_at / reset_consumed：后台重置口令改为限时单次"),
    (11, "记录发生时间列", "app", "food_logs/workout_logs 的 occurred_at / timezone_offset_minutes"),
    (12, "schema_version", "app", "结构版本登记表本身"),
    (13, "私信编辑与个人可见性", "app", "messages.edited_at/edit_version；message_preferences 删除和转写可见状态"),
    (14, "训练手账", "app", "training_sessions/training_sets/training_templates；个人模板、日历与逐组训练"),
    (15, "显式事务迁移与查询索引", "app", "统一扩展表迁移；稳定轻塑号；周期照片、会话参与者与训练列表索引"),
)

# 后台仓库自己拥有的表：主应用既不建也不改，只在此登记，避免出现"两张表谁都在写"。
ADMIN_OWNED_TABLES = ("ops_sessions", "ops_media_cleanup")

TABLE = "CREATE TABLE IF NOT EXISTS schema_version (" \
        "id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL, updated_at TEXT NOT NULL)"


def execute_schema(conn, script):
    """逐条执行DDL，不像executescript那样提前提交调用方事务。"""
    pending = ''
    for character in script:
        pending += character
        if character == ';' and sqlite3.complete_statement(pending):
            conn.execute(pending)
            pending = ''
    if pending.strip():
        conn.execute(pending)


def migration_allowed() -> bool:
    """import 期要不要真的动结构。

    部署时先显式跑一次迁移（scripts/migrate.py），再把 QINGSU_SKIP_MIGRATE=1 交给服务进程：
    这样"启动一个只读进程"不会顺手改生产表，而迁移失败会停在部署步骤里而不是藏在日志中。
    """
    return os.environ.get("QINGSU_SKIP_MIGRATE") != "1"


def read(conn: sqlite3.Connection):
    try:
        row = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def record(conn: sqlite3.Connection, when: str) -> int:
    """把当前结构版本写进登记表。表不存在时先建——第 12 版干的就是这件事。"""
    conn.execute(TABLE)
    conn.execute("INSERT INTO schema_version(id,version,updated_at) VALUES (1,?,?)"
                 " ON CONFLICT(id) DO UPDATE SET version=excluded.version, updated_at=excluded.updated_at",
                 (SCHEMA_VERSION, when))
    return SCHEMA_VERSION


def owners() -> dict:
    """{表名前缀: 所有者}，给文档和判据用：答得出"这张表归谁"。"""
    return {"app": "主应用 server.py（migrate_db）",
            "admin": "后台运维 API（ops/admin_api.py 的 ensure_ops_schema）",
            "admin_tables": list(ADMIN_OWNED_TABLES)}
