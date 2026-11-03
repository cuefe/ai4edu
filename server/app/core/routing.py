"""接口路由：同步接口执行完马上结束数据库事务、归还连接。

FastAPI 的同步接口分几段在线程池里执行：先是依赖（get_current_user 查账号），再是接口本身，
返回后还要再排一次线程池做响应校验，最后才执行 get_db 的收尾。每两段之间请求都要重新排队等线程，
排队时如果事务没结束，数据库连接就一直占着。并发一高，排队的请求占满连接池，正在执行的线程拿不到连接，
互相卡住直到连接池超时（压测实测：300 名学生同时在线时请求全部超时）。

所以：get_current_user 查完账号就结束事务；接口在自己的线程里返回后马上提交（get_db 收尾时本来也是提交，
只是提前了）。连接只在线程真正执行时占用，数量不超过线程数（main._check_pool 保证线程数小于连接池上限）。
"""

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastapi.routing import APIRoute
from sqlalchemy.orm import Session


def _release_after(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(endpoint)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = endpoint(*args, **kwargs)
        for value in kwargs.values():
            if isinstance(value, Session) and value.in_transaction():
                value.commit()
        return result

    return wrapper


class DbRoute(APIRoute):
    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        if not inspect.iscoroutinefunction(endpoint):
            endpoint = _release_after(endpoint)
        super().__init__(path, endpoint, **kwargs)
