import logging
import sys
import threading
from datetime import datetime
from typing import Optional

from colorama import Fore, Style, init

init()


_thread_local = threading.local()


class ThreadFormatter(logging.Formatter):
    LEVEL_COLORS = {
        'DEBUG': Fore.WHITE,
        'INFO': Fore.CYAN,
        'SUCCESS': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT,
    }

    THREAD_COLORS = {
        'SCRAPER': Fore.CYAN,
        'W': Fore.MAGENTA,
        'E': Fore.BLUE,
        'MAIN': Fore.WHITE,
    }

    def __init__(self, include_timestamp: bool = True):
        super().__init__()
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        thread_id = getattr(_thread_local, 'thread_id', None)
        if thread_id is None:
            thread_id = threading.current_thread().name[:8]

        thread_color = Fore.WHITE
        for prefix, color in self.THREAD_COLORS.items():
            if thread_id.upper().startswith(prefix):
                thread_color = color
                break

        level_color = self.LEVEL_COLORS.get(record.levelname, Fore.WHITE)

        parts = []

        if self.include_timestamp:
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            parts.append(f"{Fore.WHITE}{timestamp}{Style.RESET_ALL}")

        thread_display = f"{thread_color}{thread_id:>8}{Style.RESET_ALL}"
        parts.append(thread_display)

        level_display = f"{level_color}{record.levelname:>8}{Style.RESET_ALL}"
        parts.append(level_display)

        parts.append(record.getMessage())

        return " | ".join(parts)


class UnbufferedStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            stream.flush()
        except Exception:
            self.handleError(record)


SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, 'SUCCESS')


def success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)


logging.Logger.success = success


class ThreadLogger:
    _root_logger: Optional[logging.Logger] = None
    _lock = threading.Lock()
    _initialized = False

    @classmethod
    def initialize(cls, level: int = logging.INFO, include_timestamp: bool = True):
        with cls._lock:
            if cls._initialized:
                return

            cls._root_logger = logging.getLogger('kaa')
            cls._root_logger.setLevel(level)
            cls._root_logger.handlers.clear()

            handler = UnbufferedStreamHandler(sys.stdout)
            handler.setLevel(level)
            handler.setFormatter(ThreadFormatter(include_timestamp=include_timestamp))
            cls._root_logger.addHandler(handler)

            cls._root_logger.propagate = False

            cls._initialized = True

    @classmethod
    def set_thread_id(cls, thread_id: str):
        _thread_local.thread_id = thread_id

    @classmethod
    def get_thread_id(cls) -> Optional[str]:
        return getattr(_thread_local, 'thread_id', None)

    @classmethod
    def get_logger(cls, name: str = '') -> logging.Logger:
        if not cls._initialized:
            cls.initialize()

        if name:
            return logging.getLogger(f'kaa.{name}')
        return cls._root_logger


def get_worker_logger(worker_type: str, worker_id: int) -> logging.Logger:
    prefix = 'W' if worker_type == 'download' else 'E'
    thread_id = f"{prefix}{worker_id}"
    ThreadLogger.set_thread_id(thread_id)
    return ThreadLogger.get_logger(f'worker.{thread_id}')


def get_scraper_logger() -> logging.Logger:
    ThreadLogger.set_thread_id('SCRAPER')
    return ThreadLogger.get_logger('scraper')


def get_main_logger() -> logging.Logger:
    ThreadLogger.set_thread_id('MAIN')
    return ThreadLogger.get_logger('main')


def log_info(message: str):
    ThreadLogger.get_logger().info(message)


def log_success(message: str):
    ThreadLogger.get_logger().success(message)


def log_warning(message: str):
    ThreadLogger.get_logger().warning(message)


def log_error(message: str):
    ThreadLogger.get_logger().error(message)


def log_debug(message: str):
    ThreadLogger.get_logger().debug(message)
