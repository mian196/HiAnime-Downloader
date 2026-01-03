"""
Thread-aware logging system for HiAnime Downloader.

Provides real-time, interleaved logging across multiple threads with:
- Thread-specific identifiers (similar to Docker Compose output)
- Color-coded log levels and thread types
- Unbuffered StreamHandler for immediate output
- Consistent timestamp and format across all threads
"""

import logging
import sys
import threading
from datetime import datetime
from typing import Optional

from colorama import Fore, Style, init

init()


# Thread-local storage for thread identifiers
_thread_local = threading.local()


class ThreadFormatter(logging.Formatter):
    """
    Custom formatter that includes thread identifier and color coding.

    Format: [TIMESTAMP] [THREAD_ID] [LEVEL] MESSAGE

    Colors:
    - Scraper threads: Cyan
    - Download workers (W1, W2, ...): Magenta
    - Embed workers (E1, E2, ...): Blue
    - Log levels: INFO=Cyan, SUCCESS=Green, WARNING=Yellow, ERROR=Red
    """

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
        'W': Fore.MAGENTA,  # Download workers
        'E': Fore.BLUE,     # Embed workers
        'MAIN': Fore.WHITE,
    }

    def __init__(self, include_timestamp: bool = True):
        super().__init__()
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        # Get thread identifier from thread-local storage or generate one
        thread_id = getattr(_thread_local, 'thread_id', None)
        if thread_id is None:
            thread_id = threading.current_thread().name[:8]

        # Determine thread color
        thread_color = Fore.WHITE
        for prefix, color in self.THREAD_COLORS.items():
            if thread_id.upper().startswith(prefix):
                thread_color = color
                break

        # Get level color
        level_color = self.LEVEL_COLORS.get(record.levelname, Fore.WHITE)

        # Build formatted message
        parts = []

        if self.include_timestamp:
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            parts.append(f"{Fore.WHITE}{timestamp}{Style.RESET_ALL}")

        # Thread identifier with fixed width for alignment
        thread_display = f"{thread_color}{thread_id:>8}{Style.RESET_ALL}"
        parts.append(thread_display)

        # Level with fixed width
        level_display = f"{level_color}{record.levelname:>8}{Style.RESET_ALL}"
        parts.append(level_display)

        # Message
        parts.append(record.getMessage())

        return " | ".join(parts)


class UnbufferedStreamHandler(logging.StreamHandler):
    """
    StreamHandler that flushes after every emit for real-time output.
    """

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            stream.flush()
        except Exception:
            self.handleError(record)


# Add SUCCESS level between INFO and WARNING
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, 'SUCCESS')


def success(self, message, *args, **kwargs):
    """Log a success message."""
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)


logging.Logger.success = success


class ThreadLogger:
    """
    Thread-aware logger factory.

    Creates loggers with consistent formatting and thread identification.
    Each logger automatically includes the thread's identifier in output.

    Usage:
        # In main thread
        logger = ThreadLogger.get_logger('main')
        logger.info("Starting application")

        # In worker thread
        ThreadLogger.set_thread_id('W1')  # Download worker 1
        logger = ThreadLogger.get_logger('worker')
        logger.info("Downloading episode 1")
    """

    _root_logger: Optional[logging.Logger] = None
    _lock = threading.Lock()
    _initialized = False

    @classmethod
    def initialize(cls, level: int = logging.INFO, include_timestamp: bool = True):
        """
        Initialize the logging system.

        Args:
            level: Logging level (default: INFO)
            include_timestamp: Whether to include timestamps in output
        """
        with cls._lock:
            if cls._initialized:
                return

            # Create root logger
            cls._root_logger = logging.getLogger('hianime')
            cls._root_logger.setLevel(level)
            cls._root_logger.handlers.clear()

            # Add unbuffered stream handler
            handler = UnbufferedStreamHandler(sys.stdout)
            handler.setLevel(level)
            handler.setFormatter(ThreadFormatter(include_timestamp=include_timestamp))
            cls._root_logger.addHandler(handler)

            # Prevent propagation to root logger
            cls._root_logger.propagate = False

            cls._initialized = True

    @classmethod
    def set_thread_id(cls, thread_id: str):
        """
        Set the thread identifier for the current thread.

        Args:
            thread_id: Identifier string (e.g., 'W1', 'E2', 'SCRAPER')
        """
        _thread_local.thread_id = thread_id

    @classmethod
    def get_thread_id(cls) -> Optional[str]:
        """Get the current thread's identifier."""
        return getattr(_thread_local, 'thread_id', None)

    @classmethod
    def get_logger(cls, name: str = '') -> logging.Logger:
        """
        Get a logger instance.

        Args:
            name: Logger name (appended to 'hianime.')

        Returns:
            Logger instance with thread-aware formatting
        """
        if not cls._initialized:
            cls.initialize()

        if name:
            return logging.getLogger(f'hianime.{name}')
        return cls._root_logger


def get_worker_logger(worker_type: str, worker_id: int) -> logging.Logger:
    """
    Convenience function to get a logger for a worker thread.

    Args:
        worker_type: Type of worker ('download' or 'embed')
        worker_id: Worker number (1, 2, 3, ...)

    Returns:
        Logger configured for this worker
    """
    prefix = 'W' if worker_type == 'download' else 'E'
    thread_id = f"{prefix}{worker_id}"
    ThreadLogger.set_thread_id(thread_id)
    return ThreadLogger.get_logger(f'worker.{thread_id}')


def get_scraper_logger() -> logging.Logger:
    """
    Get a logger for the scraper thread.

    Returns:
        Logger configured for the scraper
    """
    ThreadLogger.set_thread_id('SCRAPER')
    return ThreadLogger.get_logger('scraper')


def get_main_logger() -> logging.Logger:
    """
    Get a logger for the main thread.

    Returns:
        Logger configured for the main thread
    """
    ThreadLogger.set_thread_id('MAIN')
    return ThreadLogger.get_logger('main')


# Convenience functions for direct logging without explicit logger
def log_info(message: str):
    """Log an info message."""
    ThreadLogger.get_logger().info(message)


def log_success(message: str):
    """Log a success message."""
    ThreadLogger.get_logger().success(message)


def log_warning(message: str):
    """Log a warning message."""
    ThreadLogger.get_logger().warning(message)


def log_error(message: str):
    """Log an error message."""
    ThreadLogger.get_logger().error(message)


def log_debug(message: str):
    """Log a debug message."""
    ThreadLogger.get_logger().debug(message)
