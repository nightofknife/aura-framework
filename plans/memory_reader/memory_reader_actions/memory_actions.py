from packages.aura_core.api import register_action, requires_services
from packages.aura_shared_utils.utils.logger import logger
from typing import Optional, List, Any


@register_action(name="attach_to_process", public=True)
@requires_services(mr='memory_reader')
def attach_to_process(mr, process_name: str) -> Optional[int]:
    """
    查找并附加到指定名称的进程。

    参数:
        process_name: 进程的可执行文件名 (例如 "game.exe")。

    返回:
        成功则返回进程ID (PID)，失败则返回 None。
    """
    pid = mr.find_process_id(process_name)
    if pid:
        if mr.attach_to_process(pid):
            return pid
    return None


@register_action(name="detach_from_process", public=True)
@requires_services(mr='memory_reader')
def detach_from_process(mr, pid: int):
    """
    从指定PID的进程分离，释放句柄。

    参数:
        pid: 由 attach_to_process 返回的进程ID。
    """
    mr.detach_from_process(pid)


@register_action(name="read_memory_value", public=True, read_only=True)
@requires_services(mr='memory_reader')
def read_memory_value(mr, pid: int, base_module: str, offsets: List[int], data_type: str = 'int') -> Optional[Any]:
    """
    读取一个动态内存地址的值 (一条龙服务)。
    这是最常用的Action，用于读取通过指针链定位的数据。

    参数:
        pid: 进程ID。
        base_module: 模块名，如 "game.exe"。
        offsets: 多级指针的偏移量列表。第一个是基址偏移，后面是逐级指针偏移。
        data_type: 'int', 'float', 'string', 'long' 等。

    返回:
        读取到的值，如果任何步骤失败则返回 None。
    """
    if not offsets:
        logger.error("offsets列表不能为空。")
        return None

    # 1. 获取模块基地址
    module_base = mr.get_module_base_address(pid, base_module)
    if not module_base:
        return None

    # 2. 计算静态基地址 (模块基址 + 第一个偏移)
    static_base_address = module_base + offsets[0]

    # 3. 如果只有一个偏移，说明是静态地址
    if len(offsets) == 1:
        return mr.read_memory(pid, static_base_address, data_type)

    # 4. 通过剩余的偏移量寻址，找到最终的动态地址
    final_address = mr.find_dynamic_address(pid, static_base_address, offsets[1:])
    if not final_address:
        return None

    # 5. 从最终地址读取值
    return mr.read_memory(pid, final_address, data_type)


@register_action(name="read_static_value", public=True, read_only=True)
@requires_services(mr='memory_reader')
def read_static_value(mr, pid: int, base_module: str, offset: int, data_type: str = 'int') -> Optional[Any]:
    """
    读取一个静态内存地址的值。

    参数:
        pid: 进程ID。
        base_module: 模块名。
        offset: 静态地址相对于模块基址的偏移。
        data_type: 数据类型。
    """
    return read_memory_value(mr, pid, base_module, [offset], data_type)
