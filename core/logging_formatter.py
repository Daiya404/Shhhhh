# core/logging_formatter.py
import logging


class TikaFormatter(logging.Formatter):
    """A custom log formatter to inject Tika's personality into the console."""

    # ANSI escape codes for colors
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    def format(self, record):
        # Define Tika's prefixes based on log level
        if record.levelno == logging.INFO:
            prefix = f"[Tika | Info]    - {self.GREY}"
        elif record.levelno == logging.WARNING:
            prefix = f"[Tika | Warning]  - {self.YELLOW}Hmph. "
        elif record.levelno == logging.ERROR:
            prefix = f"[Tika | Error]    - {self.RED}This is a problem. "
        elif record.levelno == logging.CRITICAL:
            prefix = f"[Tika | CRITICAL] - {self.BOLD_RED}A disaster. Look what happened: "
        else:
            prefix = f"[{record.levelname}]"

        # Set the format for the log message itself
        log_format = f"%(asctime)s {prefix}%(message)s{self.RESET}"

        formatter = logging.Formatter(log_format, "%Y-%m-%d %H:%M:%S")
        return formatter.format(record)