=======================
aws-s3-files-autosync
=======================


Files watcher program to autosync with AWS S3

Inspiration
================

Failed to find libraries that work properly to deal with AWS S3 files in the same way *watchdog* does for local
filesystem changes.

The files changed in S3 are pulled down and the local changes are uploaded to S3 **with a backup in S3 prior to upload**
(avoids accidental loss of files).


Usage
======

.. code-block:: bash

    files_s3_autosync -h
    usage: files_s3_autosync [-h] [-f FILE_PATH | -e ENV_VAR] [_ ...]

    positional arguments:
      _

    optional arguments:
      -h, --help            show this help message and exit
      -f FILE_PATH, --from-file FILE_PATH
                            Configuration for execution from a file
      -e ENV_VAR, --from-env-var ENV_VAR
                            Configuration for execution is in an environment variable

Input files model

.. literalinclude:: aws_s3_files_autosync/input.json
    :language: json


Features
--------

* Synchronize (GET/PUT) files from/to local filesystem to S3.
* Validates whether downloading the file is necessary based on file size and timestamps
* Automatically creates a copy of the current object in S3 before uploading a newer version.
* Simulates **aws s3 sync** for specific files
