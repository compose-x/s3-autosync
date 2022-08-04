#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

"""Console script for aws_s3_files_autosync."""

import argparse
import sys
from os import environ

from aws_s3_files_autosync.common import init_config

# from .files_autosync import init_s3_watch_dog
from .local_sync import init_local_watch_dog


class MissingConfig(ValueError):
    """
    Custom exception for missing configuration to start the program
    """

    pass


def main():
    """Console script for aws_s3_files_autosync."""
    parser = argparse.ArgumentParser()
    parser.add_argument("_", nargs="*")
    options = parser.add_mutually_exclusive_group()
    options.add_argument(
        "-f",
        "--from-file",
        help="Configuration for execution from a file",
        type=str,
        required=False,
        dest="file_path",
    )
    options.add_argument(
        "-e",
        "--from-env-var",
        dest="env_var",
        required=False,
        help="Configuration for execution is in an environment variable",
    )
    args = parser.parse_args()
    print("Arguments: " + str(args._))

    if not (args.env_var or args.file_path) and environ.get("FILES_CONFIG", None):
        config = init_config(env_var="FILES_CONFIG")
    elif args.env_var:
        config = init_config(
            env_var=args.env_var,
        )
    elif args.file_path:
        config = init_config(
            file_path=args.file_path,
        )
    else:
        raise MissingConfig(
            "Failed to import configuration for the s3 watchdog. Specify an argument or set FILES_CONFIG"
        )
    return config


def local_main():
    """
    Uses watchdog to drive the the changes, only based on local files changes.
    """
    config = main()
    init_local_watch_dog(config)


# def s3_main():
#     """
#     Uses custom watchdog logic to look at the files in S3 and locally to decide what to do. Default.
#     :return:
#     """
#     config = main()
#     init_s3_watch_dog(config)


# if __name__ == "__main__":
#     sys.exit(s3_main())  # pragma: no cover
