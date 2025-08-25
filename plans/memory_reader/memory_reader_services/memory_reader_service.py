import ctypes
import ctypes.wintypes
from typing import Optional, List, Dict, Any

import win32api
import win32con
import win32process

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger

# 定义Windows API需要的常量
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

# 数据类型映射 (类型, 字节数)
DATA_TYPES = {
    'int': (ctypes.c_int32, 4),
    'uint': (ctypes.c_uint32, 4),
    'float': (ctypes.c_float, 4),
    'double': (ctypes.c_double, 8),
    'byte': (ctypes.c_byte, 1),
    'short': (ctypes.c_short, 2),
    'long': (ctypes.c_longlong, 8),  # 64位指针
}


@register_service(alias="memory_reader", public=True)
class MemoryReaderService:
    """
    封装了Windows内存读取功能的服务。
    """

    def __init__(self):
        self.attached_processes: Dict[int, int] = {}  # {pid: handle}

    def __del__(self):
        # 自动清理：关闭所有已打开的进程句柄，防止资源泄露
        for handle in self.attached_processes.values():
            try:
                win32api.CloseHandle(handle)
            except win32api.error:
                pass  # 句柄可能已失效
        self.attached_processes.clear()

    def find_process_id(self, process_name: str) -> Optional[int]:
        """根据进程可执行文件名查找其PID。"""
        try:
            pids = win32process.EnumProcesses()
            for pid in pids:
                if pid == 0: continue
                try:
                    # 需要查询权限才能获取模块名
                    handle = win32api.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                    if handle:
                        proc_name = win32process.GetModuleFileNameEx(handle, 0)
                        if proc_name.lower().endswith(process_name.lower()):
                            win32api.CloseHandle(handle)
                            logger.debug(f"找到进程 '{process_name}'，PID: {pid}")
                            return pid
                        win32api.CloseHandle(handle)
                except win32api.error:
                    # 忽略无权访问的进程
                    continue
            logger.warning(f"未找到名为 '{process_name}' 的进程。")
            return None
        except Exception as e:
            logger.error(f"查找进程时出错: {e}", exc_info=True)
            return None

    def attach_to_process(self, pid: int) -> Optional[int]:
        """附加到指定PID的进程，获取并缓存其句柄。"""
        if pid in self.attached_processes:
            return self.attached_processes[pid]

        try:
            # 请求读取内存的权限
            handle = win32api.OpenProcess(PROCESS_VM_READ, False, pid)
            if handle:
                self.attached_processes[pid] = handle
                logger.info(f"成功附加到进程 {pid}。")
                return handle
            else:
                logger.error(f"附加到进程 {pid} 失败，可能权限不足。请尝试以管理员身份运行。")
                return None
        except Exception as e:
            logger.error(f"附加到进程 {pid} 时出错: {e}", exc_info=True)
            return None

    def detach_from_process(self, pid: int):
        """从进程分离，关闭句柄并从缓存中移除。"""
        if pid in self.attached_processes:
            handle = self.attached_processes.pop(pid)
            win32api.CloseHandle(handle)
            logger.info(f"已从进程 {pid} 分离。")

    def get_module_base_address(self, pid: int, module_name: str) -> Optional[int]:
        """获取进程中某个模块的基地址 (例如 'game.exe' 或 'engine.dll')。"""
        if pid not in self.attached_processes:
            logger.error("获取模块基址失败：未附加到进程。")
            return None

        handle = self.attached_processes[pid]
        try:
            # EnumProcessModules需要不同的权限，所以临时开一个
            h_proc_all_access = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
            modules = win32process.EnumProcessModules(h_proc_all_access)
            win32api.CloseHandle(h_proc_all_access)

            for h_module in modules:
                mod_name = win32process.GetModuleFileNameEx(handle, h_module)
                if mod_name.lower().endswith(module_name.lower()):
                    logger.debug(f"找到模块 '{module_name}' 的基地址: {hex(h_module)}")
                    return h_module
            logger.warning(f"在进程 {pid} 中未找到模块 '{module_name}'。")
            return None
        except Exception as e:
            logger.error(f"获取模块基地址时出错: {e}", exc_info=True)
            return None

    def read_memory(self, pid: int, address: int, data_type: str = 'int', buffer_size: int = 256) -> Optional[Any]:
        """从指定内存地址读取特定类型的数据。"""
        if pid not in self.attached_processes:
            return None

        handle = self.attached_processes[pid]

        if data_type == 'string':
            buffer = ctypes.create_string_buffer(buffer_size)
            bytes_read = ctypes.c_size_t(0)
            if ctypes.windll.kernel32.ReadProcessMemory(handle, address, buffer, buffer_size, ctypes.byref(bytes_read)):
                try:
                    # 找到第一个空字符并截断，然后解码
                    value = buffer.value.split(b'\0', 1)[0]
                    return value.decode('utf-8', errors='ignore')
                except Exception:
                    return buffer.value.decode('gbk', errors='ignore')
            return None

        if data_type not in DATA_TYPES:
            raise ValueError(f"不支持的数据类型: {data_type}")

        c_type, size = DATA_TYPES[data_type]
        buffer = c_type()
        bytes_read = ctypes.c_size_t(0)

        if ctypes.windll.kernel32.ReadProcessMemory(handle, address, ctypes.byref(buffer), size,
                                                    ctypes.byref(bytes_read)):
            return buffer.value
        else:
            return None

    def find_dynamic_address(self, pid: int, base_address: int, offsets: List[int]) -> Optional[int]:
        """通过基地址和多级偏移量计算动态地址 (寻址)。"""
        try:
            address = base_address
            # 遍历除最后一个之外的所有偏移
            for offset in offsets[:-1]:
                address = self.read_memory(pid, address, 'long')
                if address is None: return None
                address += offset

            # 最后一个偏移加上后就是最终地址
            last_ptr = self.read_memory(pid, address, 'long')
            if last_ptr is None: return None
            return last_ptr + offsets[-1]

        except Exception as e:
            logger.error(f"寻址失败: {e}", exc_info=True)
            return None
