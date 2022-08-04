"""Unit test package for aws_s3_files_autosync."""

from os import environ, path

import pytest
from boto3.session import Session
from botocore.exceptions import ClientError
from pytest import raises

from aws_s3_files_autosync.files_autosync import WatchedFolderToSync

HERE = path.abspath(path.dirname(__file__))


@pytest.fixture()
def get_bucket():
    return environ.get("TEST_BUCKET", "sacrificial-lamb")


def test_simple_file(get_bucket):
    file_config = {
        "S3": {
            "BucketName": get_bucket,
            "ObjectKey": "aws_s3_files_autosync/test-files/tox.ini",
        },
        "Priority": "cloud",
    }
    test_file = WatchedFolderToSync(f"{HERE}/../tox.ini", file_config)
    test_file.exists()
    test_file.exists_in_s3()
    test_file.upload()
    test_file.download("/tmp/tox.ini")
    test_file.upload("/aws_s3_files_autosync/test-files/overrides/tox.ini")
    test_file.exists_in_s3()
    print(test_file.object.e_tag)


def test_wrong_bucket():
    file_config = {
        "S3": {
            "BucketName": "etc",
            "ObjectKey": "aws_s3_files_autosync/test-files/tox.ini",
        }
    }
    test_file = WatchedFolderToSync(f"{HERE}/../tox.ini", file_config)
    with raises(ClientError):
        test_file.exists_in_s3()


def test_inexistant_key(get_bucket):
    test_session = Session()
    test_file = WatchedFolderToSync(
        f"{HERE}/../tox.ini",
        {
            "S3": {
                "BucketName": get_bucket,
                "ObjectKey": "aws_s3_files_autosync/does-not-exist",
            }
        },
        session=test_session,
    )
    test_file.exists()
    test_file.exists_in_s3()
