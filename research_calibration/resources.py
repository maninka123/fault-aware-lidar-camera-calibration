"""Lightweight Windows memory checks; no drivers, services or system settings changed."""
import ctypes
import os


def memory_status(process_id=None):
    if os.name != 'nt':
        return dict(available_mb=None,process_mb=None)
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
            ('total_physical','available_physical','total_page','available_page','total_virtual','available_virtual','extended')]
    class Process(ctypes.Structure):
        _fields_=[('size',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
            ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','page','peak_page','private')]
    memory=Memory(); memory.length=ctypes.sizeof(memory)
    process=Process(); process.size=ctypes.sizeof(process)
    available=None; used=None
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        available=memory.available_physical/2**20
    kernel=ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x0400|0x0010,False,process_id) if process_id else kernel.GetCurrentProcess()
    if handle:
        try:
            if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle),ctypes.byref(process),process.size):
                used=max(process.private,process.working)/2**20
        finally:
            if process_id: kernel.CloseHandle(ctypes.c_void_p(handle))
    return dict(available_mb=available,process_mb=used)


def check_resources():
    state=memory_status()
    if state['available_mb'] is not None and state['available_mb']<4096:
        raise MemoryError('Research run stopped: less than 4 GiB system memory available')
    if state['process_mb'] is not None and state['process_mb']>2048:
        raise MemoryError('Research run stopped: Python memory exceeded the 2 GiB soft budget')
    return state
