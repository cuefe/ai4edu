from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """连通性检查。业务任务按模块放在这里，例如资料解析：content.parse_resource。"""
    return "pong"
