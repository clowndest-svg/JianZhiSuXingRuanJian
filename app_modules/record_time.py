"""Resolve a record's occurrence day independently of its upload time."""
from datetime import date, datetime, timedelta, timezone
from fastapi import HTTPException


def record_day(req, user):
    stamp = getattr(req, "occurred_at", None)
    offset = getattr(req, "timezone_offset_minutes", None)
    selected = getattr(req, "log_date", None)
    if stamp is None and selected is None:
        return date.today().isoformat()
    if stamp is not None:
        if stamp.tzinfo is None or offset is None:
            raise HTTPException(400, '记录时间需要时区信息')
        if stamp > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(400, '记录发生时间不能在未来')
        local_day = (stamp.astimezone(timezone.utc) - timedelta(minutes=offset)).date()
        if selected is not None and local_day != selected:
            raise HTTPException(400, '记录日期与发生时间不一致')
    else:
        local_day = selected or date.today()
    today = ((datetime.now(timezone.utc) - timedelta(minutes=offset)).date()
             if offset is not None else date.today())
    # Existing account timestamps use the server's local timezone. Convert that
    # timestamp to the occurrence timezone before comparing calendar dates.
    created = datetime.fromisoformat(user['created_at']).astimezone(timezone.utc)
    earliest = ((created - timedelta(minutes=offset)).date()
                if offset is not None else date.fromisoformat(user['created_at'][:10]))
    if local_day > today or local_day < earliest:
        raise HTTPException(400, '记录日期须在注册日至今天之间')
    return local_day.isoformat()
