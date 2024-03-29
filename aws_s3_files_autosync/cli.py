#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>

"""Console script for aws_s3_files_autosync."""

import argparse
import logging
import sys
from os import environ

from aws_s3_files_autosync.common import init_config
from aws_s3_files_autosync.local_sync import Cerberus
from aws_s3_files_autosync.logging import LOG


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
    parser.add_argument(
        "--debug", action="store_true", default=False, help="Enable debug logging"
    )
    args = parser.parse_args()
    print("Arguments: " + str(args._))

    if args.debug and LOG.hasHandlers():
        LOG.setLevel(logging.DEBUG)
        LOG.handlers[0].setLevel(logging.DEBUG)

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


def local_sync_main():
    """
    Uses watchdog to drive the the changes, only based on local files changes.
    """
    config = main()
    watchdog = Cerberus(config)
    watchdog.run()


if __name__ == "__main__":
    sys.exit(local_sync_main())  # pragma: no cover
