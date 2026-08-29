import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# ================= 配置区域 =================

# 尝试获取项目根目录，如果没找到则使用当前目录下的 logs
def get_log_dir():
    # 假设项目结构是 backend/common/infrastructure/logging/logger.py
    # 向上四级到达项目根目录
    try:
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        log_dir = base_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir
    except Exception:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

LOG_DIR = get_log_dir()

FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"

class ColoredFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = CONSOLE_FORMAT

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: green + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

def get_logger(name="ITS_Project"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 1. 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # 2. 通用日志
    app_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    logger.addHandler(app_handler)

    # 3. 错误日志
    error_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "error.log",
        when="midnight",
        interval=1,
        backupCount=60,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    logger.addHandler(error_handler)

    return logger

logger = get_logger()
