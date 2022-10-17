#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>

"""
Management mysqlDb objects.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from os import path, walk
from tempfile import TemporaryDirectory

from compose_x_common.compose_x_common import keyisset, set_else_none

from aws_s3_files_autosync.common import get_prefix_key, lean_path
from aws_s3_files_autosync.files_autosync import check_s3_changes
from aws_s3_files_autosync.files_management import (
    Handler,
    ManagedFolder,
    Watcher,
    get_file_from_event,
)
from aws_s3_files_autosync.logging import LOG
from aws_s3_files_autosync.s3_handler import S3ManagedFile


def set_regexes_list(regexes_str: list[str]) -> list[re.Pattern]:
    regexes: list = []
    for regex in regexes_str:
        try:
            regex_re = re.compile(regex)
            regexes.append(regex_re)
        except Exception as error:
            LOG.exception(error)
            LOG.error(f"{regex} is not valid")
    return regexes


def build_sql_command(config: dict) -> str:
    if keyisset("hostname", config):
        cmd = (
            "mysqldump --protocol=TCP"
            f" -h{config['hostname']}"
            f" -u{config['username']}"
            f" -p{config['password']}"
            f" --port={config['port']}"
            if keyisset("port", config)
            else "--port=3306" f" {config['database']}"
        )
    elif keyisset("socket_path", config):
        cmd = (
            "mysqldump"
            f" --socket={lean_path(config['socket_path'])}"
            f" -u{config['username']}"
            f" -p{config['password']}"
            f" {config['database']}"
        )
    else:
        raise KeyError("Missing hostname or socket_path", config.keys())
    return cmd


class ManagedMySQL:
    """
    Watches over specific folders for changes and syncs them to S3.

    The logic goes as follows:

    1. Watch the bin-log directory.
    2. On close event, backup the file to S3 and create DB Dump, also saved to S3.

    Alternatively, if a new bin log file has not been created since the last backup,
    and we are passed interval time, take a backup and store in S3.

    If SSM Parameter name set, updates the path to S3 with the latest dump file.
    """

    def __init__(
        self,
        name: str,
        config: dict,
    ):
        self._job_name = name
        self._config = deepcopy(config)
        self.config = config
        self._binlogs_path = self._config["bin_logs"]["path"]
        self._dumps_config = set_else_none(
            "dumps", config, alt_value={"interval": "15m"}
        )
        self._temp_dir = None
        if not self._dumps_config:
            self.create_dumps_config_from_bin_logs()
        else:
            self.set_dumps_config()

        self._sql_command = build_sql_command(config)
        self._bin_logs_config = config["bin_logs"]
        self.binlogs_folder = BinLogFolder(
            self._binlogs_path, self._bin_logs_config["folder"], self
        )
        self.dumps_folder = ManagedFolder(
            self.dumps_path, self._dumps_config["folder"], create=True
        )

    @property
    def dumps_path(self) -> str:
        return path.abspath(self._dumps_config["path"])

    @property
    def dirname(self) -> str:
        return path.basename(self._binlogs_path)

    @property
    def path(self) -> str:
        return self._binlogs_path

    @property
    def abspath(self) -> str:
        return path.abspath(self._binlogs_path)

    def create_dumps_config_from_bin_logs(self):
        self._temp_dir = TemporaryDirectory()
        folder_config = self.import_bin_logs_folder_config()
        self._dumps_config: dict = {
            "path": self._temp_dir.name,
            "folder": folder_config,
        }

    def set_dumps_config(self):
        if not keyisset("path", self._dumps_config):
            self._temp_dir = TemporaryDirectory()
            self._dumps_config["path"] = self._temp_dir.name

        if not keyisset("folder", self._dumps_config):
            folder_config = self.import_bin_logs_folder_config()
            self._dumps_config["folder"] = folder_config

    def import_bin_logs_folder_config(self) -> dict:
        folder_config = deepcopy(self._config["bin_logs"]["folder"])
        if keyisset("whitelist", folder_config):
            del folder_config["whitelist"]
        if keyisset("blacklist", folder_config):
            del folder_config["blacklist"]
        folder_config["whitelist_regex"]: list = [r".*.sql$"]
        folder_config["s3"]["prefix_key"] = lean_path(
            f"{self._job_name}/dumps"
            if not keyisset("prefix_key", folder_config["s3"])
            else f"{get_prefix_key(folder_config['s3']['prefix_key'])}{self._job_name}/dumps"
        )
        return folder_config

    def create_mysql_dump(self, name: str):
        """
        Creates a MySQL dump of the database.
        """
        cmd = self._sql_command
        cmd += f" > {self.dumps_path}/{name}"
        LOG.debug(f"Creating dump {name}")
        return_code = self.run_command(cmd)
        if return_code != 0:
            raise OSError(f"Failed to create dump {name}")

    def create_dump_from_binary_logs(
        self,
        destination_file: str,
        index_file_regex: str = ".*-bin.index$",
        index_file_name: str = None,
    ):
        index_file_pattern = re.compile(index_file_regex)
        for root, folders, files in walk(self.abspath):
            for _file in files:
                if (
                    index_file_name and _file == index_file_name
                ) or index_file_pattern.match(_file):
                    LOG.debug(f"Found index file {path.join(root, _file)}")
                    index_file = path.join(root, _file)
                    self.create_dump_from_index_file(destination_file, index_file)

    def auto_store_index_files(self, files_paths: list[str]) -> None:
        for file_path in files_paths:
            s3_file = S3ManagedFile(file_path, self)
            check_s3_changes(s3_file)

    def create_dump_from_index_file(self, destination_file, index_file):
        index_dir_path = path.abspath(path.dirname(index_file))
        binary_log_files: list = []
        with open(index_file) as index_fd:
            lines = index_fd.readlines()
        LOG.debug(f"DB Index files: {lines}")
        for count, line in enumerate(lines):
            line = line.strip()
            file_name = path.basename(line)
            file_path = (
                path.join(index_dir_path, file_name) if not path.exists(line) else line
            )
            if not path.exists(file_path):
                continue
            binary_log_files.append(file_path)
        files_names = " ".join(binary_log_files)
        tmp_dir = TemporaryDirectory()
        dest_file_name = path.basename(destination_file)
        temp_file_name = f"{tmp_dir.name}/{dest_file_name}"
        cmd = (
            f"for file in {files_names}; do"
            " mysqlbinlog --skip-annotate-row-events --short-form $file"
            f" -d {self.config['database']}"
            f" >> {temp_file_name}"
            "; done"
        )
        LOG.debug(f"Creating {temp_file_name} to process all changes.")
        self.run_command(cmd)
        LOG.debug(f"Copy {temp_file_name} to {destination_file}")
        self.run_command(f"cp {tmp_dir.name}/{dest_file_name} {destination_file}")
        LOG.info(f"{destination_file} creation complete.")

    @staticmethod
    def run_command(cmd: str) -> int:
        """
        Runs a command in a subprocess.
        """
        import subprocess

        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.wait()
        stdout, stderr = process.communicate()
        if stdout:
            LOG.debug(stdout.decode("utf-8"))
        if stderr:
            LOG.error("Error output from command")
            LOG.error(stderr.decode("utf-8"))
        return process.returncode

    def create_db_dump(self, file, event):
        try:
            LOG.warning(f"{file.path} closed - Triggering mysqldump")
            self.create_mysql_dump(
                f"{path.basename(event.src_path)}-{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
            )
        except OSError as error:
            LOG.exception(error)
            LOG.error(
                "Failed to execute mysqldump. Creating .sql file from DB indexes."
            )
            self.create_dump_from_binary_logs(
                lean_path(
                    f"{self.dumps_path}"
                    "/from-binary-files_"
                    f"{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
                )
            )


class BinLogFolder(ManagedFolder):
    def __init__(self, folder_path: str, config: dict, sql_manager: ManagedMySQL):
        super().__init__(folder_path, config)
        self._sql_manager = sql_manager
        self.watcher = BinLogsWatcher(self.abspath, self)

    @property
    def sql_manager(self) -> ManagedMySQL:
        return self._sql_manager


class BinLogsWatcher(Watcher):
    def __init__(self, directory_path: str, folder: BinLogFolder):
        super().__init__(directory_path, folder)

    @property
    def sql_manager(self) -> ManagedMySQL:
        return self.folder.sql_manager

    def run(self):
        event_handler = BinLogHandler(self, self.sql_manager)
        self.observer.schedule(event_handler, self.directory_path, recursive=True)
        self.observer.start()


class BinLogHandler(Handler):
    def __init__(self, watcher: BinLogsWatcher, sql_manager: ManagedMySQL):
        super().__init__(watcher)
        self._sql_manager = sql_manager

    @property
    def sql_manager(self) -> ManagedMySQL:
        return self._sql_manager

    def on_closed(self, event) -> None:
        file = get_file_from_event(
            event, self.folder, override_match_regex=r"mariadb-bin.[0-9]+$"
        )
        if not file:
            LOG.warning(f"File {event.src_path} not found in the watcher files")
            return
        LOG.debug(f"{file.path} has been closed. Updating to S3.")
        file.upload()
        self.folder.sql_manager.create_db_dump(file, event)
