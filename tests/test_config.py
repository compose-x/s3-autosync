"""
Tests for config input validation
"""

from os import environ, path

import pytest
from jsonschema.exceptions import ValidationError
from pytest import raises

from aws_s3_files_autosync.common import init_config

HERE = path.abspath(path.dirname(__file__))


@pytest.fixture()
def valid_config():
    return {
        "files": {
            "/tmp/tox.ini": {
                "S3": {
                    "BucketName": "sacrificial-lamb",
                    "ObjectKey": "aws_s3_files_autosync/test-files/tox.ini",
                }
            },
            "/tmp/HISTORY.rst": {
                "S3": {
                    "BucketName": "sacrificial-lamb",
                    "ObjectKey": "aws_s3_files_autosync/test-files/HISTORY.rst",
                }
            },
        }
    }


@pytest.fixture()
def invalid_config():
    return {
        "/tmp/tox.ini": {
            "S3": {
                "BucketName": "sacrificial-lamb",
                "ObjectKey": "aws_s3_files_autosync/test-files/tox.ini",
            }
        },
        "/tmp/HISTORY.rst": {
            "S3": {
                "BucketName": "sacrificial-lamb",
                "ObjectKey": "aws_s3_files_autosync/test-files/HISTORY.rst",
            }
        },
    }


def test_init_config(valid_config):
    config = init_config(raw=valid_config)
    config = init_config(file_path=f"{HERE}/test.yaml")
    config = init_config(file_path=f"{HERE}/test.json")


def test_invalid_config(invalid_config):
    with raises(ValidationError):
        config = init_config(raw=invalid_config)
