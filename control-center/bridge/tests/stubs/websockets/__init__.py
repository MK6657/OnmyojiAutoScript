"""沙箱用的 websockets 替身：Bridge 只在真正连接 Core 时才会用到它。"""


class NotAvailable(RuntimeError):
    pass


def connect(*args, **kwargs):  # pragma: no cover
    raise NotAvailable('sandbox stub: websockets.connect is unavailable')
