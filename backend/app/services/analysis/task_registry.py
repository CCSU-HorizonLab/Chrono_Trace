"""后台任务状态口径单源。

好感度分析与情感补算各自维护任务注册表（存储形态不同：dataclass 与 dict），
但**终态集合必须单源**——两侧互斥守卫都据它判断对侧是否仍在运行，
口径漂移会导致守卫误判（例如新增终态在旧集合里仍算"运行中"，
分析被永久拒绝启动）。
"""

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def is_running(status) -> bool:
    return status not in TERMINAL_STATUSES
