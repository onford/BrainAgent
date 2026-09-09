"""Host resource measurements and explicit resource failures, separate from recipes."""

import ctypes
import os
from pathlib import Path
import shutil

from .schemas import ResourceBudget

MIB = 1024**2


class ResourceError(ValueError):
    """Changing scientific parameters cannot resolve host resource availability."""


def available_memory():
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ResourceError("无法读取系统可用内存")
        return status.available
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for row in meminfo.read_text().splitlines():
            if row.startswith("MemAvailable:"):
                return int(row.split()[1]) * 1024
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        raise ResourceError(
            "无法读取系统可用内存，请在支持资源探测的主机运行"
        ) from None


def budget(root, request):
    disk = shutil.disk_usage(root).free
    memory = available_memory()
    # Keep headroom for the OS, browser, model client and filesystem metadata.
    disk_limit, memory_limit = disk * 85 // 100, memory * 70 // 100
    if request.max_disk_mb is not None:
        disk_limit = min(disk_limit, request.max_disk_mb * MIB)
    if request.max_memory_mb is not None:
        memory_limit = min(memory_limit, request.max_memory_mb * MIB)
    return ResourceBudget(
        disk_available_bytes=disk,
        memory_available_bytes=memory,
        disk_limit_bytes=disk_limit,
        memory_limit_bytes=memory_limit,
        disk_policy="explicit_cap"
        if request.max_disk_mb is not None
        else "available_disk_85_percent",
        memory_policy="explicit_cap"
        if request.max_memory_mb is not None
        else "available_memory_70_percent",
    )


def require_capacity(kind, required, limit):
    if required > limit:
        label = "磁盘" if kind == "disk" else "内存"
        raise ResourceError(
            f"{label}资源不足：预计需要 {required / MIB:.0f} MiB，当前预算 {limit / MIB:.0f} MiB；"
            "请释放资源或调整明确配置的资源上限，预处理方案已保留。"
        )
