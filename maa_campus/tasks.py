"""MaaFramework 任务投递与等待。"""

from __future__ import annotations


def post_and_wait(tasker, entry: str, override: dict | None = None):
    """投递 pipeline 任务并等待完成，返回 TaskJob。"""
    job = tasker.post_task(entry, override or {})
    job.wait()
    return job
