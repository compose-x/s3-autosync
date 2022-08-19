#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>

"""
Management of files and folders in the file system
"""

from __future__ import annotations

import re
import warnings
from os import makedirs, path
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from aws_s3_files_autosync.mysqldb_management import (
        ManagedMySQL,
        BinLogsWatcher,
    )

from compose_x_common.compose_x_common import set_else_none
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from aws_s3_files_autosync.common import lean_path
from aws_s3_files_autosync.logging import LOG
from aws_s3_files_autosync.s3_handler import S3Config, S3ManagedFile


def set_regexes_list(regexes_str: list[str]) -> list[re.Pattern]:
    regexes: list = []
    for regex in regexes_str:
        try:
            regex_re = re.compile(regex)
            regexes.append(regex_re)
        except Exception as error:
            LOG.exception(error)
            LOG.error(f"{regex} - invalid regular expression")
    return regexes


class ManagedFolder:
    """
    Manages a defined folder based on input configuration.
    Manages the watcher lifecycle and sets the IAM / S3 / else options.
    """

    def __init__(self, folder_path: str, config: dict, create: bool = False):
        self._path = folder_path
        self._config = config
        self.sync_priority = set_else_none("priority", config, alt_value="local")
        self.whitelist: list = set_else_none("whitelist", config, alt_value=[])
        self.whitelist_regex: list = set_else_none(
            "whitelist_regex", config, alt_value=[]
        )
        self.whitelist_re = set_regexes_list(self.whitelist_regex)

        self.blacklist_regex: list = set_else_none(
            "blacklist_regex", config, alt_value=[]
        )
        self.blacklist_re = set_regexes_list(self.blacklist_regex)

        s3_config = config["s3"]
        self.s3_config = S3Config(
            bucket_name=s3_config["bucket_name"],
            prefix_key=lean_path(
                set_else_none("prefix_key", s3_config, alt_value=self.dirname)
            ),
            iam_override=set_else_none("iam_override", s3_config),
        )

        if not path.exists(self.abspath):
            if not create:
                warnings.warn(UserWarning(f"{self.abspath} does not exist."))
            else:
                LOG.info(f"Folder {self.abspath} successfully created.")
                makedirs(self.abspath, exist_ok=True)
        self.watcher = Watcher(self.abspath, self)
        self.files: dict = {}
        self.post_init_summary()

    def post_init_summary(self):
        LOG.debug(self._path)
        LOG.debug(
            f"self._path, BlackList Regex {[_re.pattern for _re in self.blacklist_re]}"
        )
        LOG.debug(
            f"self._path, Whitelist Regex {[_re.pattern for _re in self.whitelist_re]}"
        )

    @property
    def dirname(self) -> str:
        return path.basename(self._path)

    @property
    def path(self) -> str:
        return self._path

    @property
    def abspath(self) -> str:
        return path.abspath(self._path)

    def file_is_to_watch(self, file_name: str):
        return file_is_to_watch(
            file_name, self.whitelist, self.whitelist_re, self.blacklist_re
        )


class Watcher:
    def __init__(self, directory_path: str, folder: ManagedFolder):
        self._directory = directory_path
        self.observer = Observer()
        self.files: dict = {}
        self.folder = folder

    @property
    def directory_path(self):
        return path.abspath(self._directory)

    def run(self):
        event_handler = Handler(self)
        self.observer.schedule(event_handler, self.directory_path, recursive=True)
        self.observer.start()


class Handler(FileSystemEventHandler):
    def __init__(self, watcher: Union[Watcher, BinLogsWatcher]):
        super().__init__()
        self.watcher = watcher

    @property
    def folder(self) -> Union[ManagedFolder, ManagedMySQL]:
        return self.watcher.folder

    def on_created(self, event) -> None:
        file = get_file_from_event(event, self.folder)
        if not file:
            return
        LOG.debug(f"{file.path} - New file added to folder monitoring")
        try:
            file.upload()
        except Exception as error:
            LOG.exception(error)
            LOG.error(
                f"{file.path} - Failure to upload on create. Will upload on close."
            )

    def on_closed(self, event) -> None:
        file = get_file_from_event(event, self.folder)
        if not file:
            return
        LOG.debug(f"{file.path } - File closed, uploading.")
        file.upload()

    def on_deleted(self, event) -> None:
        file = get_file_from_event(event, self.folder)
        if not file:
            return
        LOG.debug(f"{file.path} - File deleted, attempting to create backup in S3.")
        file.create_s3_backup()


def get_file_from_event(
    event, folder: Union[ManagedFolder, ManagedMySQL], override_match_regex: str = None
) -> Union[S3ManagedFile, None]:
    """
    Using the file name from the event, identify using white/black list and regular expressions
    to identify if the file should be ignored or used.

    Defaults use the object definition, allows for override inclusion regular expression.
    """
    if event.is_directory:
        LOG.debug("Event is for a directory.")
        return
    _file_name = path.basename(event.src_path)
    if event.src_path not in folder.files:
        if not folder.file_is_to_watch(event.src_path):
            LOG.debug(f"{event.src_path} does not match whitelisting")
            return None
        elif override_match_regex and not re.match(override_match_regex, _file_name):
            LOG.debug(
                f"{_file_name} does not match with override {override_match_regex}"
            )
            return None
        else:
            LOG.debug(f"New file to monitor {event.src_path}")
            file_obj = S3ManagedFile(event.src_path, folder)
            folder.files[event.src_path] = file_obj
            return file_obj
    else:
        return folder.files[event.src_path]


def file_is_to_watch(
    file_name: str,
    whitelist: list[str] = None,
    whitelist_re: list[re.Pattern] = None,
    blacklist_re: list[re.Pattern] = None,
) -> bool:
    """
    Determines if the file is to be watched based on the whitelist and blacklist
    """
    _file_name = path.basename(file_name)
    if blacklist_re and any(pattern.match(_file_name) for pattern in blacklist_re):
        return False
    elif whitelist_re and any(pattern.match(_file_name) for pattern in whitelist_re):
        return True
    elif whitelist and _file_name in whitelist:
        return True
    return False
