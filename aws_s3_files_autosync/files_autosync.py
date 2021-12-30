#  -*- coding: utf-8 -*-
#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

"""Files watcher."""
import datetime
import json
import time
from datetime import datetime as dt
from os import environ, path

import boto3
import pytz
import yaml
from boto3.session import Session
from botocore.exceptions import ClientError
from compose_x_common.aws import get_assume_role_session, get_session
from compose_x_common.compose_x_common import keyisset
from importlib_resources import files as pkg_files
from jsonschema import RefResolver, validate
from yaml import Loader

from .common import setup_logging

PRIORITY_TO_CLOUD = 1
PRIORITY_TO_LOCAL = 2

LOG = setup_logging()


class File(object):
    """
    Class to represent a file and its S3 manipulation

    :ivar bucket: The S3 Bucket for the object
    :ivar S3.Object object: The S3 Object to watch
    :ivar boto3.session.Session session: The Boto3 session to use for all following API calls
    """

    def __init__(
        self,
        file_path: str,
        definition: dict,
        iam_override=None,
        session=None,
    ):
        self.path = path.abspath(file_path)
        self.definition = definition
        if iam_override:
            self.session = iam_override.session
        elif not iam_override and session:

            self.session = session
        else:
            self.session = Session()

        self.resource = self.session.resource("s3")
        s3_def = self.definition["S3"]
        self.object = self.resource.ObjectSummary(
            s3_def["BucketName"], s3_def["ObjectKey"]
        )
        self.bucket = self.object.Bucket()
        self.priority = PRIORITY_TO_CLOUD
        self.set_priority_from_definition()

    def __repr__(self):
        return self.path

    def set_priority_from_definition(self):
        """
        Sets the priority to cloud or local if set. If not set, priority goes to cloud
        """
        if keyisset("Priority", self.definition):
            if self.definition["Priority"] == "cloud":
                self.priority = PRIORITY_TO_CLOUD
            elif self.definition["Priority"] == "local":
                self.priority = PRIORITY_TO_LOCAL

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
                        f"File in S3 was not modified since {timestamp}. Uploading newer file"
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
                override_object = self.resource.Object(self.bucket.name, override_key)
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
        backup_suffix = self.object.last_modified.timestamp()
        file_backup = self.resource.Object(
            self.bucket.name,
            f"{self.object.key}-{backup_suffix}{path.splitext(self.path)[-1]}",
        )
        file_backup.copy({"Bucket": file_backup.bucket_name, "Key": self.object.key})


def validate_input(config):
    source = pkg_files("aws_s3_files_autosync").joinpath("input.json")
    LOG.info(f"Validating input against {source}")
    resolver = RefResolver(f"file://{path.abspath(path.dirname(source))}/", None)
    validate(
        config,
        json.loads(source.read_text()),
        resolver=resolver,
    )


def init_config(raw=None, file_path=None, env_var=None):
    """
    Function to initialize the configuration

    :param raw: The raw content of a content
    :param str file_path: The path to a job configuration file
    :param str env_var: Key of the env var to load the instructions from
    :rtype: dict
    """
    if file_path:
        with open(path.abspath(file_path), "r") as file_fd:
            config_content = file_fd.read()
    elif raw and isinstance(raw, str):
        config_content = raw
    elif raw and isinstance(raw, dict):
        validate_input(raw)
        return raw
    elif env_var:
        config_content = environ.get(env_var, None)
    else:
        raise Exception("No input source was provided")
    try:
        config = yaml.load(config_content, Loader=Loader)
        validate_input(config)
        LOG.info(f"Successfully loaded YAML config")
        return config
    except yaml.YAMLError:
        config = json.loads(config_content)
        validate_input(config)
        LOG.info(f"Successfully loaded JSON config")
        return config
    except Exception:
        LOG.error("Input content is neither JSON nor YAML formatted")
        raise


def define_session_from_iam_override(
    iam_override: dict, session=None
) -> boto3.session.Session:
    """
    Function to parse IamOverride and return a boto3.session.Session

    :param dict iam_override:
    :param boto3.session.Session session: Session to use to invoke the AssumeRole
    :rtype: boto3.session.Session
    :return: The boto3 session to use given iam override settings
    """
    source_session = get_session(session)
    session = get_assume_role_session(
        source_session, iam_override["RoleArn"], **iam_override
    )
    return session


def init_files_jobs(config: dict, session=None) -> dict:
    """
    Function to initialize files and create the different files mappings to their respective objects.
    Will be given to the watch dog

    :param config:
    :param session: Override Session
    :return: The dict mapping from file name to File
    :rtype: dict
    """
    files = {}
    if keyisset("IamOverride", config):
        global_session = define_session_from_iam_override(
            config["IamOverride"], session
        )
    else:
        global_session = get_session(session)

    for file_name, file_def in config["files"].items():
        LOG.info(f"{file_name} - importing settings")
        if keyisset("IamOverride", file_def):
            resource_session = define_session_from_iam_override(
                config["IamOverride"], global_session
            )
        else:
            resource_session = global_session
        managed_file = File(
            file_name,
            file_def,
            session=resource_session,
        )
        if not managed_file.exists() and managed_file.exists_in_s3():
            managed_file.download()
            LOG.info(
                f"{managed_file} - Initial download file from S3. ",
                f"s3://{managed_file.object.bucket_name}/{managed_file.object.key}",
            )
        files[file_name] = managed_file

    return files


def handle_both_files_present(file: File):
    """
    Function to go over the conditions when the file is present locally and in S3, of a different size and timestamp

    :param File file: The file to evaluate.
    """
    if file.s3_last_modified == file.local_last_modified:
        LOG.info(f"{file} - not modified since {file.local_last_modified}")
    elif (
        file.s3_last_modified > file.local_last_modified
        and not file.local_and_remote_size_identical()
    ):
        LOG.info(f"{file} - newer S3 version")
        file.download()
        LOG.info(f"{file.object.key} - downloaded to {file.path}")
        file._local_last_modified = file.local_last_modified
    elif (
        file.local_last_modified > file.s3_last_modified
        and not file.local_and_remote_size_identical()
    ):
        LOG.info(f"{file} - newer local version.")
        file.create_s3_backup()
        file.upload()
        LOG.info(f"{file.path} - uploaded to {file.object.key}")
        file.object.load()


def check_s3_changes(file: File):
    """
    Function to check whether the file in S3 changed.
    Logic for updates

    if s3 has changed and local has not: update local from S3
    if s3 has not changed and local has changed: update S3
    if s3 has not changed and neither has local: pass
    if both changed:
      if priority is to cloud -> download from S3
      if priority is to local -> upload to S3

    :param File file: The file to evaluate.
    """
    if (
        file.exists()
        and file.exists_in_s3()
        and not file.local_and_remote_size_identical()
    ):
        handle_both_files_present(file)

    elif file.exists_in_s3() and not file.exists():
        LOG.info(f"{file} - initial download from S3")
        file.download()
        LOG.debug(f"{file} - downloaded from S3 - {file.object.size}")
    elif file.exists() and not file.exists_in_s3():
        LOG.info(f"{file} - Exists locally, not in cloud. Initial upload")
        file.upload()
        file.object.load()
        LOG.debug(f"{file} - Uploaded. {file.object.size}")
    elif file.local_and_remote_size_identical():
        LOG.debug(f"{file} is the same locally and in AWS S3. {file.object.size}")
    else:
        LOG.info(f"File {file} does not exist locally or in S3")


def init_s3_watch_dog(config: dict, interval=5):
    """
    Function to keep looking at the AWS S3 files and for local changes

    :param dict config: The input config for the job
    :param int interval: Intervals between checks. The higher, the more S3 API GET call made.
    """
    files = init_files_jobs(config)
    LOG.info(f"S3 watchdog starting for {list(files.keys())}")
    while True:
        LOG.info("S3 Watchdog running.")
        try:
            for file_name, file in files.items():
                check_s3_changes(file)
            time.sleep(interval)
        except KeyboardInterrupt:
            LOG.info("\rKeyboard interruption. Exit.")
            break
