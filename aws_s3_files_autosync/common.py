#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>
import json
import logging as logthings
import sys
import warnings
from os import environ, path

import yaml
from importlib_resources import files as pkg_files
from jsonschema import RefResolver, validate
from yaml import Loader


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


LOG = setup_logging()


def validate_input(config):
    source = pkg_files("aws_s3_files_autosync").joinpath("input.json")
    LOG.info(f"Validating input against {path.dirname(source)}")
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
        with open(path.abspath(file_path)) as file_fd:
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
    except yaml.YAMLError as error:
        print("ERROR?", error)
        config = json.loads(config_content)
        validate_input(config)
        LOG.info(f"Successfully loaded JSON config")
        return config
    except Exception:
        LOG.error("Input content is neither JSON nor YAML formatted")
        raise
