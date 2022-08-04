"""
Management of files and folders in the file system
"""

from __future__ import annotations

import re
from os import makedirs, path
from typing import TYPE_CHECKING, Union

from compose_x_common.compose_x_common import set_else_none
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from aws_s3_files_autosync.s3_handler import S3Config, S3ManagedFile


def set_regexes_list(regexes_str: list[str]) -> list[re.Pattern]:
    regexes: list = []
    for regex in regexes_str:
        try:
            regex_re = re.compile(regex)
            regexes.append(regex_re)
        except Exception as error:
            print(error)
            print(regex, "is not valid")
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
            prefix_key=set_else_none("prefix_key", s3_config, alt_value=self.dirname),
            iam_override=set_else_none("iam_override", s3_config),
        )

        if not path.exists(self.abspath):
            if not create:
                raise OSError(f"Directory {self.abspath} does not exist")
            else:
                print(f"Folder {self.abspath} successfully created.")
                makedirs(self.abspath, exist_ok=True)
        self.watcher = Watcher(self.abspath, self)
        self.files: dict = {}
        self.post_init_summary()

    def post_init_summary(self):
        print(self._path)
        print(self._path, "BlackList Regex", [_re.pattern for _re in self.blacklist_re])
        print(self._path, "Whitelist Regex", [_re.pattern for _re in self.whitelist_re])

    @property
    def dirname(self) -> str:
        return path.basename(self._path)

    @property
    def path(self) -> str:
        return self._path

    @property
    def abspath(self) -> str:
        return path.abspath(self._path)

    def file_is_to_watch(self, file_name: str) -> bool:
        """
        Determines if the file is to be watched based on the whitelist and blacklist
        :param file_name:
        :return:
        """
        _file_name = path.basename(file_name)
        if self.blacklist_regex and any(
            pattern.match(_file_name) for pattern in self.blacklist_re
        ):
            return False
        elif self.whitelist_regex and any(
            pattern.match(_file_name) for pattern in self.whitelist_re
        ):
            return True
        elif self.whitelist and _file_name in self.whitelist:
            return True
        return False


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
    def __init__(self, watcher: Watcher):
        super().__init__()
        self.watcher = watcher

    @property
    def folder(self) -> ManagedFolder:
        return self.watcher.folder

    def on_created(self, event):
        file = get_file_from_event(event, self.folder)
        if not file:
            return
        print("New file added to folder monitoring", file.path)
        try:
            file.upload()
        except Exception as error:
            print("Failed to perform initial upload. ", error)
            print("File will be uploaded on close.")

    def on_closed(self, event):
        file = get_file_from_event(event, self.folder)
        if not file:
            return
        print("File closed. Uploading newer version")
        file.upload()

    def on_deleted(self, event):
        file = get_file_from_event(event, self.folder)
        if not file:
            return
        print("File deleted. Generating S3 backup")
        file.create_s3_backup()


def get_file_from_event(event, folder: ManagedFolder) -> Union[S3ManagedFile, None]:
    if event.is_directory:
        return
    if not folder.file_is_to_watch(event.src_path):
        return None
    if event.src_path in folder.files:
        return folder.files[event.src_path]
    else:
        file_obj = S3ManagedFile(event.src_path, folder)
        folder.files[event.src_path] = file_obj
        return file_obj
