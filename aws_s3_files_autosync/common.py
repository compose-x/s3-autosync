#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

from __future__ import annotations

import json
from os import environ, path

import yaml
from importlib_resources import files as pkg_files
from jsonschema import RefResolver, validate
from yaml import Loader

from aws_s3_files_autosync.logging import LOG

PRIORITY_TO_CLOUD = 1
PRIORITY_TO_LOCAL = 2


def validate_input(config):
    source = pkg_files("aws_s3_files_autosync").joinpath("input.json")
    LOG.debug(f"Validating input against {path.dirname(source)}")
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
        LOG.debug(f"Successfully loaded YAML config")
        return config
    except yaml.YAMLError as error:
        config = json.loads(config_content)
        validate_input(config)
        LOG.debug(f"Successfully loaded JSON config")
        return config
    except Exception:
        LOG.debug("Input content is neither JSON nor YAML formatted")
        raise


def get_prefix_key(key: str) -> str:
    if key.endswith("/"):
        return key
    else:
        return key + "/"


def lean_path(origin_path: str) -> str:
    return origin_path.replace(r"//", "/")
