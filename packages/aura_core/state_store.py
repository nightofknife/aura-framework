# aura_core/state_store.py

import threading
import time
from typing import Any, Dict, Optional

from packages.aura_shared_utils.utils.logger import logger


class StateStore:
    """
    一个线程安全的、支持TTL（存活时间）的键值存储服务。
    用于在Aura框架中管理“驻留信号”（持久化状态）。
    """

    def __init__(self, check_interval: float = 60.0):
        """
        初始化StateStore。
        :param check_interval: 清理过期键的后台线程检查间隔（秒）。
        """
        self._data: Dict[str, Any] = {}
        self._ttl: Dict[str, float] = {}  # 存储键的过期时间戳
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self._cleaner_thread = threading.Thread(
            target=self._ttl_cleanup_loop,
            args=(check_interval,),
            daemon=True
        )
        self._cleaner_thread.start()
        logger.info("StateStore已初始化，TTL清理线程已启动。")

    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        """
        设置一个键值对，并可选地为其设置一个存活时间。

        :param key: 状态的唯一键。
        :param value: 要存储的值。
        :param ttl: (可选) 存活时间（秒）。如果为None，则永不过期。
        """
        with self._lock:
            self._data[key] = value
            if ttl is not None:
                expire_time = time.time() + ttl
                self._ttl[key] = expire_time
                logger.debug(f"[StateStore] Set key '{key}' with TTL {ttl}s. Expires at {time.ctime(expire_time)}.")
            else:
                # 如果之前有TTL，现在设置为None，则移除TTL
                if key in self._ttl:
                    del self._ttl[key]
                logger.debug(f"[StateStore] Set key '{key}' with no expiration.")

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取一个键的值。如果键不存在或已过期，返回默认值。

        :param key: 要获取的键。
        :param default: (可选) 如果找不到键，则返回此值。
        :return: 键对应的值或默认值。
        """
        with self._lock:
            # 首先检查是否已过期
            if key in self._ttl and time.time() > self._ttl[key]:
                self._do_delete(key)  # 惰性删除
                logger.debug(f"[StateStore] Get key '{key}' failed: key has expired.")
                return default

            return self._data.get(key, default)

    def delete(self, key: str) -> bool:
        """
        删除一个键。

        :param key: 要删除的键。
        :return: 如果成功删除则返回True，如果键不存在则返回False。
        """
        with self._lock:
            return self._do_delete(key)

    def _do_delete(self, key: str) -> bool:
        """内部删除方法，不加锁，供内部调用。"""
        if key in self._data:
            del self._data[key]
            if key in self._ttl:
                del self._ttl[key]
            logger.debug(f"[StateStore] Deleted key '{key}'.")
            return True
        return False

    def get_all_states(self) -> Dict[str, Any]:
        """返回所有当前未过期的状态的副本。"""
        with self._lock:
            # 在返回前，先清理一次过期的
            self._cleanup_expired_keys()
            return self._data.copy()

    def _ttl_cleanup_loop(self, check_interval: float):
        """后台线程，定期清理过期的键。"""
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    self._cleanup_expired_keys()
            except Exception as e:
                logger.error(f"[StateStore] TTL cleanup thread encountered an error: {e}", exc_info=True)

            self._stop_event.wait(check_interval)

    def _cleanup_expired_keys(self):
        """清理所有已过期的键。必须在锁内调用。"""
        now = time.time()
        expired_keys = [key for key, expire_time in self._ttl.items() if now > expire_time]
        if expired_keys:
            logger.debug(f"[StateStore] Cleaning up {len(expired_keys)} expired keys: {expired_keys}")
            for key in expired_keys:
                self._do_delete(key)

    def shutdown(self):
        """安全关闭StateStore，停止后台线程。"""
        logger.info("StateStore is shutting down...")
        self._stop_event.set()
        self._cleaner_thread.join(timeout=5)
        if self._cleaner_thread.is_alive():
            logger.warning("[StateStore] TTL cleaner thread did not shut down gracefully.")
