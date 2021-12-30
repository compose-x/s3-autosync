#  -*- coding: utf-8 -*-
#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

import logging as logthings
import sys
import warnings
from os import environ


def setup_logging():
    """Function to setup logging for ECS ComposeX.
    In case this is used in a Lambda function, removes the AWS Lambda default log handler

    :returns: the_logger
    :rtype: Logger
    """
    level = environ.get("LOGLEVEL", "INFO").upper()
    formats = {
        "INFO": logthings.Formatter(
            "%(asctime)s [%(levelname)8s] %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ),
        "DEBUG": logthings.Formatter(
            "%(asctime)s [%(levelname)8s] %(filename)s.%(lineno)d , %(funcName)s, %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ),
    }

    if level not in formats:
        warnings.warn(
            f"Log level {level} is not valid. Must be one of {formats.keys()}. Defaulting to INFO"
        )
        level = "INFO"
    logthings.basicConfig(level=level)
    root_logger = logthings.getLogger()
    for h in root_logger.handlers:
        root_logger.removeHandler(h)
    the_logger = logthings.getLogger(__file__)

    if not the_logger.handlers:
        formatter = formats[level]
        handler = logthings.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        the_logger.addHandler(handler)

    return the_logger
