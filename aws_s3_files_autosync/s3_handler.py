#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>


"""
S3 files manipulation classes and functions
"""


from __future__ import annotations

from typing import TYPE_CHECKING, Union

from compose_x_common.aws import get_assume_role_session, get_session
from compose_x_common.compose_x_common import keyisset, set_else_none

if TYPE_CHECKING:
    from .files_management import ManagedFolder

import datetime
from datetime import datetime as dt
from os import path, stat

import pytz
from boto3 import Session
from botocore.exceptions import ClientError

from aws_s3_files_autosync.logging import LOG


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
    def s3_repr(self) -> str:
        return f"{self.bucket_name}/{self.s3_path}"

    @property
    def local_last_modified(self) -> Union[datetime.datetime, None]:
        """
        Last modified datetime for local file
        :return:
        """
        if self.exists():
            return pytz.UTC.localize(dt.fromtimestamp(path.getmtime(self.path)))
        return None

    @property
    def _local_last_modified(self) -> datetime.datetime:
        return self._local_last_modified

    @_local_last_modified.setter
    def _local_last_modified(self, modified):
        self._local_last_modified = modified

    def local_has_changed(self) -> bool:
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
        """
        return path.isfile(self.path)

    def updated_in_s3(self, timestamp=None) -> bool:
        """
        Checks whether the file exists in AWS S3 Bucket or not.

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
                    LOG.debug(f"In S3 was not modified since {timestamp}.")
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

    def upload(self, override_key: str = None) -> None:
        """
        Simple method to upload the file data content to AWS S3
        """
        try:
            if stat(self.path).st_size == 0:
                LOG.debug(f"File {self.path} is empty. Skipping upload")
                return
            if self.exists_in_s3():
                LOG.debug(
                    f"{self.s3_repr} - "
                    "Creating backup file in S3 before pushing new one with same name"
                )
                self.create_s3_backup()
            with open(self.path, "rb") as data:
                if not override_key:
                    self.object.Object().upload_fileobj(data)
                else:
                    override_object = self.resource.Object(
                        self.bucket_name, override_key
                    )
                    override_object.upload_fileobj(data)
        except OSError as error:
            LOG.exception(error)
            LOG.error("Failed to upload file to S3")

    def download(self, override_path: str = None) -> None:
        """
        Simple method to download the file from S3
        """
        with open(self.path if not override_path else override_path, "wb") as data:
            self.object.Object().download_fileobj(data)

    def create_s3_backup(self, exit_on_failure: bool = False) -> None:
        """
        Creates a copy of the current object into S3 with the last modified timestamp of the original file.
        Gets the file extension (if any) and appends it back to the extension back for ease.
        """
        if not self.exists_in_s3():
            LOG.error(f"{self.s3_repr} - File not present in S3 for copy to backup")
            if exit_on_failure:
                raise FileNotFoundError(
                    "Source file in S3 not found for copy into backup."
                )
            return
        backup_suffix = self.object.last_modified.timestamp()
        file_backup = self.resource.Object(
            self.bucket_name,
            f"{self.object.key}-{backup_suffix}{path.splitext(self.path)[-1]}",
        )
        file_backup.copy({"Bucket": file_backup.bucket_name, "Key": self.object.key})
