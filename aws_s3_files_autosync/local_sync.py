#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2021 John Mille <john@compose-x.io>

"""Files watcher."""
from time import sleep

from compose_x_common.compose_x_common import keyisset

from .common import setup_logging
from .files_management import ManagedFolder

PRIORITY_TO_CLOUD = 1
PRIORITY_TO_LOCAL = 2

LOG = setup_logging()


def init_folders_jobs(config: dict):
    folders: dict = {}
    for folder_name, folder_config in config["folders"].items():
        folder = ManagedFolder(
            folder_name, folder_config, create=keyisset("auto_create", folder_config)
        )
        folders[folder_name] = folder
    return folders


def graceful_observers_close(observers: list) -> None:
    """
    Close all observers gracefully
    :param observers:
    :return:
    """
    for observer in observers:
        observer.unschedule_all()
        observer.stop()


def init_local_watch_dog(config: dict):
    """
    Function to start the watch dog
    """
    folders = init_folders_jobs(config)
    observers: list = []
    for folder_name, folder in folders.items():
        folder.watcher.run()
        observers.append(folder.watcher.observer)

    try:
        while True:
            for folder in folders.values():
                print(folder.abspath, folder.watcher.observer.is_alive())
            sleep(1)
    except KeyboardInterrupt:
        graceful_observers_close(observers)
        print("\rExited due to Keyboard interrupt")
    for observer in observers:
        observer.join()
