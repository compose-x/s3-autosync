from __future__ import annotations

from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .files_management import S3Config, ManagedFolder

import datetime
from datetime import datetime as dt
from os import path

import pytz
from boto3 import Session
from botocore.exceptions import ClientError

from aws_s3_files_autosync.common import setup_logging

PRIORITY_TO_CLOUD = 1
PRIORITY_TO_LOCAL = 2
LOG = setup_logging()


class S3ManagedFile:
    """
    Class to represent a file and manage the sync to S3
    """

    def __init__(self, file_path: str, folder: ManagedFolder):
        self.folder = folder
        self._file_path = file_path
        self.path = path.abspath(file_path)
        self.resource = self.session.resource("s3")
        self.object = self.resource.ObjectSummary(self.bucket_name, self.s3_path)

    @property
    def session(self) -> Session:
        return self.folder.s3_config.session

    @property
    def file_name(self) -> str:
        return path.basename(self.path)

    @property
    def priority(self) -> str:
        return self.folder.sync_priority

    @property
    def bucket_name(self) -> str:
        return self.folder.s3_config.bucket_name

    @property
    def s3_path(self) -> str:
        if self.folder.s3_config.prefix_key.endswith("/"):
            prefix_key = self.folder.s3_config.prefix_key
        else:
            prefix_key = self.folder.s3_config.prefix_key + "/"
        if prefix_key.startswith(r"/"):
            prefix_key = prefix_key[1:]
        return prefix_key + path.relpath(self.path, self.folder.abspath)

    def __repr__(self):
        return self.path

    @property
    def local_last_modified(self) -> datetime.datetime:
        """
        Last modified datetime for local file
        :return:
        """
        if self.exists():
            return pytz.UTC.localize(dt.fromtimestamp(path.getmtime(self.path)))
        return None

    @property
    def _local_last_modified(self):
        return self._local_last_modified

    @_local_last_modified.setter
    def _local_last_modified(self, modified):
        self._local_last_modified = modified

    def local_has_changed(self):
        """
        Checks if the local last modified changed.
        """
        return self._local_last_modified < self.local_last_modified

    @property
    def s3_last_modified(self) -> datetime.datetime:
        """
        Gets the last modified time for object
        :return:
        """
        if self.exists_in_s3():
            self.object.load()
            try:
                return pytz.UTC.localize(self.object.last_modified)
            except ValueError:
                return self.object.last_modified
        return None

    def local_and_remote_size_identical(self) -> bool:
        """
        Checks whether the files are different based on size

        :return: remote size == local size ?
        :rtype: bool
        """
        if not self.exists():
            return False
        local_size = path.getsize(self.path)
        remote_size = self.object.size
        return local_size == remote_size

    def exists(self) -> bool:
        """
        Whether the file exists or not in filesystem

        :return: If the file exists and is a file
        :rtype: bool
        """
        return path.isfile(self.path)

    def updated_in_s3(self, timestamp=None):
        """
        Checks whether the file exists in AWS S3 Bucket or not.

        :rtype: bool
        :raises: botocore.exceptions.ClientError if the ClientError code is not 404
        """
        if timestamp is None:
            timestamp = dt.now()
        if self.exists_in_s3():
            try:
                self.object.get(IfModifiedSince=timestamp)
                return True
            except ClientError as error:
                if error.response["Error"]["Code"] == "304":
                    print(
                        f"WatchedFolderToSync in S3 was not modified since {timestamp}. Uploading newer file"
                    )
                    return False
        return False

    def exists_in_s3(self) -> bool:
        """
        Checks whether the file exists in AWS S3 Bucket or not.

        :rtype: bool
        :raises: botocore.exceptions.ClientError if the ClientError code is not 404
        """
        try:
            if self.object.e_tag:
                return True
            return False
        except self.resource.meta.client.exceptions.NoSuchKey:
            return False
        except ClientError as error:
            if error.response["Error"]["Code"] == "404":
                return False
            raise

    def upload(self, override_key=None):
        """
        Simple method to upload the file data content to AWS S3
        """
        with open(self.path, "rb") as data:
            if not override_key:
                self.object.Object().upload_fileobj(data)
            else:
                override_object = self.resource.Object(self.bucket_name, override_key)
                override_object.upload_fileobj(data)

    def download(self, override_path=None):
        """
        Simple method to download the file from S3
        """
        with open(self.path if not override_path else override_path, "wb") as data:
            self.object.Object().download_fileobj(data)

    def create_s3_backup(self):
        """
        Creates a copy of the current object into S3 with the last modified timestamp of the original file.
        Gets the file extension (if any) and appends it back to the extension back for ease.
        """
        if not self.exists_in_s3():
            print("ERROR - File not present in S3 for copy to backup")
        backup_suffix = self.object.last_modified.timestamp()
        file_backup = self.resource.Object(
            self.bucket_name,
            f"{self.object.key}-{backup_suffix}{path.splitext(self.path)[-1]}",
        )
        file_backup.copy({"Bucket": file_backup.bucket_name, "Key": self.object.key})
