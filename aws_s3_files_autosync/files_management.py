"""
Management of files and folders in the file system
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from boto3.session import Session

import re
from os import makedirs, path

from compose_x_common.aws import get_assume_role_session, get_session
from compose_x_common.compose_x_common import keyisset, set_else_none
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .s3_file_mgmt import S3ManagedFile


def get_iam_override_session(
    iam_override: dict, src_session: Session = None
) -> Session:
    """

    :param iam_override:
    :param src_session:
    :return:
    """
    src_session = get_session(src_session)
    kwargs: dict = {}
    if keyisset("external_id", iam_override):
        kwargs["external_id"]: str = iam_override["external_id"]
    session_name = set_else_none("session_name", iam_override)
    iam_role = set_else_none("iam_role", iam_override)
    dst_session: Session = get_assume_role_session(
        src_session, iam_role, session_name, **kwargs
    )
    return dst_session


class S3Config:
    """
    Class to represent the S3 object of the files
    """

    def __init__(
        self,
        bucket_name: str,
        prefix_key: str,
        iam_override: dict = None,
        session: Session = None,
    ):
        self.bucket_name = bucket_name
        self.prefix_key = (
            prefix_key if not prefix_key.startswith(r"/") else prefix_key[1:]
        )
        if iam_override:
            self.session = get_iam_override_session(iam_override, src_session=session)
        else:
            self.session = get_session(session)

    def s3_object(self, file_name: str):
        return (
            self.session.resource("s3")
            .Bucket(self.bucket_name)
            .Object(f"{self.prefix_key}/{file_name}")
        )


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

    # def on_modified(self, event):
    #     file = get_file_from_event(event, self.folder)
    #     if not file:
    #         print(self.folder.files)
    #         return
    #     print("File modified. Uploading newer version")
    #     try:
    #         file.upload()
    #     except Exception as error:
    #         print("Failed to upload after  modification", error)
    #         print("Waiting for closed.")

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
