"""Drain an owned blocking operation before its supervisor releases a lock."""
import asyncio


async def _owned_thread(function, *args, on_cancel=None, **kwargs):
    """Do not release execution ownership while its blocking file operation lives."""
    # Resolve ownership before constructing a coroutine. During teardown there
    # may be no running loop; fail without leaving an unawaited to_thread object.
    loop = asyncio.get_running_loop()
    task = loop.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if on_cancel is not None:
            on_cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()
        raise
