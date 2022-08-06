#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>

"""Files watcher."""

from aws_s3_files_autosync.logging import LOG


def handle_both_files_present(file):
    """
    Function to go over the conditions when the file is present locally and in S3, of a different size and timestamp

    :param WatchedFolderToSync file: The file to evaluate.
    """
    if file.s3_last_modified == file.local_last_modified:
        LOG.debug(f"{file} - not modified since {file.local_last_modified}")
    elif (
        file.s3_last_modified > file.local_last_modified
        and not file.local_and_remote_size_identical()
    ):
        LOG.debug(f"{file} - newer S3 version")
        file.download()
        LOG.debug(f"{file.object.key} - downloaded to {file.path}")
        file._local_last_modified = file.local_last_modified
    elif (
        file.local_last_modified > file.s3_last_modified
        and not file.local_and_remote_size_identical()
    ):
        LOG.debug(f"{file} - newer local version.")
        file.create_s3_backup()
        file.upload()
        LOG.debug(f"{file.path} - uploaded to {file.object.key}")
        file.object.load()


def check_s3_changes(file):
    """
    Function to check whether the file in S3 changed.
    Logic for updates

    if s3 has changed and local has not: update local from S3
    if s3 has not changed and local has changed: update S3
    if s3 has not changed and neither has local: pass
    if both changed:
      if priority is to cloud -> download from S3
      if priority is to local -> upload to S3

    :param WatchedFolderToSync file: The file to evaluate.
    """
    if (
        file.exists()
        and file.exists_in_s3()
        and not file.local_and_remote_size_identical()
    ):
        handle_both_files_present(file)

    elif file.exists_in_s3() and not file.exists():
        LOG.debug(f"{file} - initial download from S3")
        file.download()
        LOG.debug(f"{file} - downloaded from S3 - {file.object.size}")
    elif file.exists() and not file.exists_in_s3():
        LOG.debug(f"{file} - Exists locally, not in cloud. Initial upload")
        file.upload()
        file.object.load()
        LOG.debug(f"{file} - Uploaded. {file.object.size}")
    elif file.local_and_remote_size_identical():
        LOG.debug(f"{file} is the same locally and in AWS S3. {file.object.size}")
    else:
        LOG.debug(f"WatchedFolderToSync {file} does not exist locally or in S3")
