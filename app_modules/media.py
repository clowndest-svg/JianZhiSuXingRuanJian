"""Bound uploaded bytes and image work without blocking the async event loop."""
import threading
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

_SLOTS = threading.BoundedSemaphore(2)

async def read_upload(file, limit, detail):
    data = bytearray()
    while True:
        chunk = await file.read(min(65536, limit + 1 - len(data)))
        if not chunk:return bytes(data)
        data.extend(chunk)
        if len(data) > limit:raise HTTPException(413, detail)

async def process(function, *args):
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(503, '媒体处理正忙，请稍后重试')
    try:
        return await run_in_threadpool(function, *args)
    finally:
        _SLOTS.release()
