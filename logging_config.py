import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class DailyNumberedRotatingFileHandler(TimedRotatingFileHandler):
    """A timed rotating file handler that rotates daily at midnight,

    renames rotated files to numbered suffixes (.1, .2, ..., .N),
    and deletes files exceeding backupCount (default 30 days).
    """

    def __init__(
        self,
        filename: str | Path,
        backup_count: int = 30,
        encoding: str = "utf-8",
        delay: bool = False,
        utc: bool = False,
    ):
        super().__init__(
            filename=str(filename),
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding=encoding,
            delay=delay,
            utc=utc,
        )

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

        if self.backupCount > 0:
            # Delete any files beyond backupCount if present
            overflow_file = f"{self.baseFilename}.{self.backupCount}"
            if os.path.exists(overflow_file):
                try:
                    os.remove(overflow_file)
                except OSError:
                    pass

            # Shift existing numbered files: .29 -> .30, .28 -> .29, ..., .1 -> .2
            for i in range(self.backupCount - 1, 0, -1):
                sfn = f"{self.baseFilename}.{i}"
                dfn = f"{self.baseFilename}.{i + 1}"
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        try:
                            os.remove(dfn)
                        except OSError:
                            pass
                    try:
                        os.rename(sfn, dfn)
                    except OSError:
                        pass

            # Rotate current active file to .1
            dfn = f"{self.baseFilename}.1"
            if os.path.exists(dfn):
                try:
                    os.remove(dfn)
                except OSError:
                    pass
            if os.path.exists(self.baseFilename):
                try:
                    os.rename(self.baseFilename, dfn)
                except OSError:
                    pass

        if not self.delay:
            self.stream = self._open()

        current_time = int(time.time())
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at = new_rollover_at + self.interval
        self.rolloverAt = new_rollover_at


def setup_logging(
    log_file: str | Path | None = None,
    log_level: str | int | None = None,
    backup_count: int = 30,
) -> None:
    """Configure application logging with console and daily numbered file rotation."""
    if log_file is None:
        if os.environ.get("LOG_FILE"):
            log_file = Path(os.environ["LOG_FILE"])
        else:
            log_dir = Path(os.environ.get("LOG_DIR", Path(__file__).parent / "logs"))
            log_file = log_dir / "secretary.log"
    else:
        log_file = Path(log_file)

    resolved_level: int
    if log_level is None:
        log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        resolved_level = getattr(logging, log_level_name, logging.INFO)
    elif isinstance(log_level, str):
        resolved_level = getattr(logging, log_level.upper(), logging.INFO)
    else:
        resolved_level = log_level

    # Ensure log directory exists
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    # Avoid duplicate handlers if setup_logging is invoked more than once
    existing_handler_types = {type(h) for h in root_logger.handlers}

    if logging.StreamHandler not in existing_handler_types:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(resolved_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if DailyNumberedRotatingFileHandler not in existing_handler_types:
        file_handler = DailyNumberedRotatingFileHandler(
            filename=log_file,
            backup_count=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(resolved_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Silence noisy file watcher and HTTP library loggers to prevent feedback loops
    for noisy_logger in ("watchfiles", "watchfiles.main", "httpcore", "httpx"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # Register log directory with watchfiles DefaultFilter to prevent dev reloader loops
    try:
        import watchfiles

        dir_name = log_file.parent.name
        if dir_name and dir_name not in watchfiles.DefaultFilter.ignore_dirs:
            watchfiles.DefaultFilter.ignore_dirs = (
                *watchfiles.DefaultFilter.ignore_dirs,
                dir_name,
            )
    except (ImportError, AttributeError):
        pass
