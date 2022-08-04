#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

"""Files watcher."""
import time

from .s3_file_mgmt import LOG, S3FileWatcher


def handle_both_files_present(file: S3FileWatcher):
    """
    Function to go over the conditions when the file is present locally and in S3, of a different size and timestamp

    :param WatchedFolderToSync file: The file to evaluate.
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


def check_s3_changes(file: S3FileWatcher):
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
        LOG.info(f"WatchedFolderToSync {file} does not exist locally or in S3")


# def init_s3_watch_dog(config: dict, interval=5):
#     """
#     Function to keep looking at the AWS S3 files and for local changes
#
#     :param dict config: The input config for the job
#     :param int interval: Intervals between checks. The higher, the more S3 API GET call made.
#     """
#     files = init_files_jobs(config)
#     LOG.info(f"S3 watchdog starting for {list(files.keys())}")
#     while True:
#         LOG.info("S3 Watchdog running.")
#         try:
#             for file_name, file in files.items():
#                 check_s3_changes(file)
#             time.sleep(interval)
#         except KeyboardInterrupt:
#             LOG.info("\rKeyboard interruption. Exit.")
#             break
