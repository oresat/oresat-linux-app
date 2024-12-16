"""Service for the getting system logs over CAN."""

import logging
import os
import tarfile

from loguru import logger

from ...common.oresat_file import new_oresat_file
from ...common.service import Service

_logs = []


class LogServiceHandler(logging.Handler):
    """Custom Log handler that doesn't log to file."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = []

    def emit(self, record: logging.LogRecord) -> None:
        """Override the emit method to save to memory."""
        global _logs  # pylint: disable=W0603
        _logs.append(record.getMessage())
        _logs = _logs[-500:]


class LogsService(Service):
    """Service for getting system logs"""

    def __init__(self):
        super().__init__()

        self.logs_dir_path = "/var/log/journal/"

    def on_start(self):
        self.node.od_write("logs", "make_file", False)  # make sure this is False by default

        self.node.add_sdo_callbacks("logs", "since_boot", self.on_read_since_boot, None)

    def on_loop(self):
        if self.node.od_read("logs", "make_file"):
            logger.info("Making a copy of logs")

            tar_file_path = "/tmp/" + new_oresat_file("logs", ext=".tar.xz")

            with tarfile.open(tar_file_path, "w:xz") as t:
                for i in os.listdir(self.logs_dir_path):
                    t.add(self.logs_dir_path + "/" + i, arcname=i)

            self.node.fread_cache.add(tar_file_path, consume=True)
            self.node.od_write("logs", "make_file", False)

        self.sleep(0.1)

    def on_read_since_boot(self) -> str:
        """SDO callback to get a copy of the OLAF app logs since boot."""

        return "\n".join(reversed(_logs))
