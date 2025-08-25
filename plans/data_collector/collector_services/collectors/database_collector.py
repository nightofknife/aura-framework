# plans/data_collector/collector_services/collectors/database_collector.py
import sqlite3
from pathlib import Path
from typing import Dict, Any, List

from packages.aura_core.logger import logger


class DatabaseCollector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.default_timeout = config.get('default_timeout', 30)
        self.default_sqlite_path = config.get('sqlite', {}).get('default_path', './data/collector.db')

    def query(self, query: str, db_path: str = None, params: tuple = None) -> List[Dict[str, Any]]:
        """查询数据库并返回结果"""
        db_path = db_path or self.default_sqlite_path
        params = params or ()

        try:
            # 确保数据库目录存在
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(db_path, timeout=self.default_timeout) as conn:
                conn.row_factory = sqlite3.Row  # 让结果可以按列名访问
                cursor = conn.cursor()
                cursor.execute(query, params)

                results = []
                for row in cursor.fetchall():
                    results.append(dict(row))

                logger.debug(f"数据库查询成功，返回 {len(results)} 条记录")
                return results

        except Exception as e:
            logger.error(f"数据库查询失败: {e}")
            raise

    def execute(self, query: str, db_path: str = None, params: tuple = None) -> int:
        """执行数据库语句（INSERT、UPDATE、DELETE等）"""
        db_path = db_path or self.default_sqlite_path
        params = params or ()

        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(db_path, timeout=self.default_timeout) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()

                affected_rows = cursor.rowcount
                logger.debug(f"数据库执行成功，影响 {affected_rows} 行")
                return affected_rows

        except Exception as e:
            logger.error(f"数据库执行失败: {e}")
            raise

    def create_table_if_not_exists(self, table_name: str, columns: Dict[str, str],
                                   db_path: str = None) -> bool:
        """创建表（如果不存在）"""
        try:
            columns_sql = ", ".join([f"{name} {type_}" for name, type_ in columns.items()])
            query = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})"
            self.execute(query, db_path)
            logger.info(f"表 '{table_name}' 创建/确认成功")
            return True
        except Exception as e:
            logger.error(f"创建表失败: {e}")
            return False
