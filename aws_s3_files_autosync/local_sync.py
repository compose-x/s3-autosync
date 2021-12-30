#  -*- coding: utf-8 -*-
#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

"""Files watcher."""
import time
from datetime import datetime as dt
from os import path

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from .common import setup_logging
from .files_autosync import init_files_jobs

PRIORITY_TO_CLOUD = 1
PRIORITY_TO_LOCAL = 2


LOG = setup_logging()


class S3FilesSyncHandler(PatternMatchingEventHandler):
    """
    Custom class to evaluate and decide what to do when files are changed locally and/or in S3.
    """

    def __init__(self, managed_files, **kwargs):
        self.managed_files = managed_files
        super().__init__(**kwargs)

    def get_file(self, file_path):
        if file_path in self.managed_files:
            return self.managed_files[file_path]
        return None

    def on_modified(self, event):
        """
        Actions to take when the file has been modified locally
        :param event:
        :return:
        """
        the_file = self.get_file(event.src_path)
        if not the_file:
            return
        print(f"{the_file} has been modified")
        now = dt.now()
        if the_file.updated_in_s3(now):
            the_file.upload()

    def on_created(self, event):
        """
        Actions to take when the file has been created locally.
        Currently, simply uploads to S3
        """
        the_file = self.get_file(event.src_path)
        if not the_file:
            return
        print(f"{the_file} has been created. Uploading to AWS S3")
        self.managed_files[event.src_path].upload()

    def on_deleted(self, event):
        """
        Actions to take when the local file is deleted. For now, not doing anything.
        """
        the_file = self.get_file(event.src_path)
        if not the_file:
            return
        print(f"{the_file} has been deleted locally")


def init_local_watch_dog(config: dict):
    """
    Function to start the watch dog

    :param config:
    :return:
    """
    files = init_files_jobs(config)
    event_handler = S3FilesSyncHandler(
        managed_files=files,
        ignore_directories=False,
        case_sensitive=True,
        patterns=["*"],
        ignore_patterns=None,
    )
    observer = Observer()
    observers = []
    for file_name, file in files.items():
        if not file.exists():
            observer.schedule(event_handler, path.dirname(file.path), recursive=False)
        else:
            observer.schedule(event_handler, file.path, recursive=False)
        observers.append(observer)
    observer.start()

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        for o in observers:
            o.unschedule_all()
            # stop observer if interrupted
            o.stop()
        print("\rExited due to Keyboard interrupt")
    for o in observers:
        # Wait until the thread terminates before exit
        o.join()
