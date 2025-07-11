# plans/data_collector/collector_actions/collection_actions.py
from typing import Dict, Any, List

from packages.aura_core.api import register_action, requires_services
from packages.aura_shared_utils.utils.logger import logger


# === HTTP采集Actions ===

@register_action(name="fetch_url", public=True)
@requires_services(collector='data_collector')
def fetch_url(collector, url: str, method: str = "GET", headers: Dict = None,
              data: Any = None, timeout: int = None, **kwargs) -> Dict[str, Any]:
    """
    获取HTTP数据

    参数:
        url: 目标URL
        method: HTTP方法 (GET, POST, PUT, DELETE等)
        headers: 请求头字典
        data: 请求数据
        timeout: 超时时间(秒)

    返回: 包含响应数据的字典
    """
    try:
        result = collector.fetch_url(url, method, headers, data, timeout, **kwargs)
        logger.info(f"HTTP请求完成: {url} -> {result.get('status_code', 'Unknown')}")
        return result
    except Exception as e:
        logger.error(f"HTTP请求失败: {e}")
        return {'success': False, 'error': str(e)}


@register_action(name="fetch_json_api", public=True)
@requires_services(collector='data_collector')
def fetch_json_api(collector, url: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
    """
    获取JSON API数据的便捷方法

    参数:
        url: API端点URL
        method: HTTP方法

    返回: 包含JSON数据的字典
    """
    try:
        result = collector.fetch_json(url, method=method, **kwargs)
        if result.get('success') and 'json' in result:
            logger.info(f"JSON API调用成功: {url}")
            return result['json']
        else:
            logger.warning(f"JSON API调用失败: {result.get('error', 'Unknown error')}")
            return None
    except Exception as e:
        logger.error(f"JSON API调用异常: {e}")
        return None


# === 文件操作Actions ===

@register_action(name="get_file_info", public=True)
@requires_services(collector='data_collector')
def get_file_info(collector, file_path: str) -> Dict[str, Any]:
    """
    获取文件详细信息

    参数:
        file_path: 文件路径

    返回: 包含文件信息的字典
    """
    try:
        info = collector.get_file_info(file_path)
        logger.debug(f"获取文件信息: {file_path} -> 存在: {info.get('exists', False)}")
        return info
    except Exception as e:
        logger.error(f"获取文件信息失败: {e}")
        return {'exists': False, 'error': str(e)}


@register_action(name="start_file_monitor", public=True)
@requires_services(collector='data_collector')
def start_file_monitor(collector, task_id: str, file_path: str,
                       callback_event: str = None, poll_interval: int = None) -> bool:
    """
    开始监控文件变化

    参数:
        task_id: 监控任务ID
        file_path: 要监控的文件路径
        callback_event: 文件变化时发布的事件名
        poll_interval: 检查间隔(秒)

    返回: 是否启动成功
    """
    try:
        success = collector.start_file_monitor(task_id, file_path, callback_event, poll_interval)
        if success:
            logger.info(f"文件监控已启动: {task_id} -> {file_path}")
        return success
    except Exception as e:
        logger.error(f"启动文件监控失败: {e}")
        return False


@register_action(name="stop_file_monitor", public=True)
@requires_services(collector='data_collector')
def stop_file_monitor(collector, task_id: str) -> bool:
    """
    停止文件监控

    参数:
        task_id: 监控任务ID

    返回: 是否停止成功
    """
    try:
        success = collector.stop_file_monitor(task_id)
        if success:
            logger.info(f"文件监控已停止: {task_id}")
        return success
    except Exception as e:
        logger.error(f"停止文件监控失败: {e}")
        return False


# === RSS采集Actions ===

@register_action(name="fetch_rss", public=True)
@requires_services(collector='data_collector')
def fetch_rss(collector, url: str, max_entries: int = None) -> Dict[str, Any]:
    """
    获取RSS源数据

    参数:
        url: RSS源URL
        max_entries: 最大条目数

    返回: RSS数据字典
    """
    try:
        result = collector.fetch_rss(url, max_entries)
        if result.get('success'):
            logger.info(f"RSS获取成功: {url} -> {len(result.get('entries', []))} 条目")
        return result
    except Exception as e:
        logger.error(f"RSS获取失败: {e}")
        return {'success': False, 'error': str(e)}


@register_action(name="start_rss_monitor", public=True)
@requires_services(collector='data_collector')
def start_rss_monitor(collector, task_id: str, url: str,
                      callback_event: str = None, poll_interval: int = None) -> bool:
    """
    开始监控RSS源更新

    参数:
        task_id: 监控任务ID
        url: RSS源URL
        callback_event: 有新条目时发布的事件名
        poll_interval: 检查间隔(秒)

    返回: 是否启动成功
    """
    try:
        success = collector.start_rss_monitor(task_id, url, callback_event, poll_interval)
        if success:
            logger.info(f"RSS监控已启动: {task_id} -> {url}")
        return success
    except Exception as e:
        logger.error(f"启动RSS监控失败: {e}")
        return False


# === 数据库操作Actions ===

@register_action(name="query_database", public=True)
@requires_services(collector='data_collector')
def query_database(collector, query: str, db_path: str = None,
                   params: List = None) -> List[Dict[str, Any]]:
    """
    查询数据库

    参数:
        query: SQL查询语句
        db_path: 数据库文件路径(可选)
        params: 查询参数列表

    返回: 查询结果列表
    """
    try:
        params_tuple = tuple(params) if params else None
        results = collector.query_database(query, db_path, params_tuple)
        logger.info(f"数据库查询完成: 返回 {len(results)} 条记录")
        return results
    except Exception as e:
        logger.error(f"数据库查询失败: {e}")
        return []


@register_action(name="execute_database", public=True)
@requires_services(collector='data_collector')
def execute_database(collector, query: str, db_path: str = None,
                     params: List = None) -> int:
    """
    执行数据库语句

    参数:
        query: SQL执行语句
        db_path: 数据库文件路径(可选)
        params: 执行参数列表

    返回: 影响的行数
    """
    try:
        params_tuple = tuple(params) if params else None
        affected_rows = collector.execute_database(query, db_path, params_tuple)
        logger.info(f"数据库执行完成: 影响 {affected_rows} 行")
        return affected_rows
    except Exception as e:
        logger.error(f"数据库执行失败: {e}")
        return 0


@register_action(name="save_data_to_db", public=True)
@requires_services(collector='data_collector')
def save_data_to_db(collector, table_name: str, data: Dict[str, Any],
                    db_path: str = None, create_table: bool = True) -> bool:
    """
    保存数据到数据库的便捷方法

    参数:
        table_name: 表名
        data: 要保存的数据字典
        db_path: 数据库路径(可选)
        create_table: 是否自动创建表

    返回: 是否保存成功
    """
    try:
        # 自动创建表(如果需要且表不存在)
        if create_table:
            # 推断列类型
            columns = {}
            for key, value in data.items():
                if isinstance(value, int):
                    columns[key] = "INTEGER"
                elif isinstance(value, float):
                    columns[key] = "REAL"
                else:
                    columns[key] = "TEXT"

            collector.database_collector.create_table_if_not_exists(
                table_name, columns, db_path
            )

        # 插入数据
        columns = list(data.keys())
        values = list(data.values())
        placeholders = ", ".join(["?" for _ in columns])
        query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

        affected_rows = collector.execute_database(query, db_path, values)
        success = affected_rows > 0

        if success:
            logger.info(f"数据已保存到表 '{table_name}'")
        return success

    except Exception as e:
        logger.error(f"保存数据到数据库失败: {e}")
        return False


# === 数据处理和转换Actions ===

@register_action(name="extract_json_field", public=True, read_only=True)
def extract_json_field(data: Dict[str, Any], field_path: str, default: Any = None) -> Any:
    """
    从JSON数据中提取指定字段

    参数:
        data: JSON数据字典
        field_path: 字段路径，用点分隔 (如: "user.profile.name")
        default: 字段不存在时的默认值

    返回: 提取的字段值
    """
    try:
        current = data
        for field in field_path.split('.'):
            if isinstance(current, dict) and field in current:
                current = current[field]
            else:
                return default
        return current
    except Exception as e:
        logger.error(f"提取JSON字段失败: {e}")
        return default


@register_action(name="filter_data_by_condition", public=True, read_only=True)
def filter_data_by_condition(data_list: List[Dict], condition_field: str,
                             condition_value: Any, condition_type: str = "equals") -> List[Dict]:
    """
    根据条件过滤数据列表

    参数:
        data_list: 数据列表
        condition_field: 条件字段名
        condition_value: 条件值
        condition_type: 条件类型 (equals, contains, greater_than, less_than)

    返回: 过滤后的数据列表
    """
    try:
        filtered = []
        for item in data_list:
            if not isinstance(item, dict) or condition_field not in item:
                continue

            field_value = item[condition_field]

            match = False
            if condition_type == "equals":
                match = field_value == condition_value
            elif condition_type == "contains":
                match = str(condition_value) in str(field_value)
            elif condition_type == "greater_than":
                match = field_value > condition_value
            elif condition_type == "less_than":
                match = field_value < condition_value

            if match:
                filtered.append(item)

        logger.debug(f"数据过滤完成: {len(data_list)} -> {len(filtered)} 条记录")
        return filtered

    except Exception as e:
        logger.error(f"数据过滤失败: {e}")
        return []


# === 监控管理Actions ===

@register_action(name="get_monitoring_status", public=True, read_only=True)
@requires_services(collector='data_collector')
def get_monitoring_status(collector) -> Dict[str, Any]:
    """
    获取所有监控任务状态

    返回: 监控状态字典
    """
    try:
        status = collector.get_monitoring_status()
        logger.debug(f"当前活跃监控任务: {len(status.get('active_tasks', []))}")
        return status
    except Exception as e:
        logger.error(f"获取监控状态失败: {e}")
        return {'active_tasks': [], 'task_details': {}}


@register_action(name="stop_all_monitoring", public=True)
@requires_services(collector='data_collector')
def stop_all_monitoring(collector) -> bool:
    """
    停止所有监控任务

    返回: 是否成功
    """
    try:
        collector.stop_all_monitoring()
        logger.info("所有监控任务已停止")
        return True
    except Exception as e:
        logger.error(f"停止所有监控失败: {e}")
        return False
