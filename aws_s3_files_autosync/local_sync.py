#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>

"""Files watcher."""

import signal
from datetime import datetime
from time import sleep

from compose_x_common.compose_x_common import keyisset

from aws_s3_files_autosync.common import lean_path
from aws_s3_files_autosync.files_management import ManagedFolder
from aws_s3_files_autosync.logging import LOG
from aws_s3_files_autosync.mysqldb_management import ManagedMySQL

PRIORITY_TO_CLOUD = 1
PRIORITY_TO_LOCAL = 2


class Cerberus:
    def __init__(self, config: dict):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        self.config = config
        self.observers: list = []
        self.db_jobs: dict = {}
        self.folders_jobs: dict = {}

    def run(self):
        self.folders_jobs = init_folders_jobs(self.config)
        self.db_jobs = init_mysqldb_jobs(self.config)
        for folder_name, folder in self.folders_jobs.items():
            folder.watcher.run()
            self.observers.append(folder.watcher.observer)
        init_db_jobs(self.db_jobs, self.observers)

        try:
            while True:
                cycle_over_folders(self.folders_jobs, self.observers)
                cycle_over_db_jobs(self.db_jobs, self.observers)
                sleep(1)
        except KeyboardInterrupt:
            graceful_observers_close(self.observers)
            LOG.debug("\rExited due to Keyboard interrupt")
        except ChildProcessError as error:
            LOG.exception(error)
            graceful_observers_close(self.observers)
            LOG.error("One of the observers died.")
        for observer in self.observers:
            observer.join()

    def exit_gracefully(self, signum, frame):
        final_dumps_db_jobs(self.db_jobs)
        cycle_over_db_jobs(self.db_jobs, self.observers)
        cycle_over_folders(self.folders_jobs, self.observers)
        LOG.debug("Closing all observers")
        graceful_observers_close(self.observers)
        LOG.info(f"Exiting due to caught signal {signum}")
        exit(0)


def init_folders_jobs(config: dict):
    folders: dict = {}
    if not keyisset("folders", config):
        return folders
    for folder_name, folder_config in config["folders"].items():
        folder = ManagedFolder(
            folder_name, folder_config, create=keyisset("auto_create", folder_config)
        )
        folders[folder_name] = folder
    return folders


def init_mysqldb_jobs(config: dict) -> dict:
    jobs: dict = {}
    if not keyisset("mysqlDb", config):
        return jobs
    for job_name, job_config in config["mysqlDb"].items():
        job = ManagedMySQL(job_name, job_config)
        jobs[job_name] = job
    return jobs


def graceful_observers_close(observers: list) -> None:
    """
    Close all observers gracefully
    :param observers:
    :return:
    """
    for observer in observers:
        observer.stop()
        observer.join()


def cycle_over_folders(folders: dict, observers: list):
    for folder in folders.values():
        LOG.debug(
            f"Observer? {folder.watcher.observer} - {folder.watcher.observer.is_alive()}"
        )
        if not folder.watcher.observer.is_alive():
            try:
                folder.watcher.run()
                if folder.watcher.observer not in observers:
                    observers.append(folder.watcher.observer)
            except FileNotFoundError:
                LOG.info(f"{folder.path} - Not yet available")
            except RuntimeError as error:
                LOG.exception(error)
                LOG.error(f"Stopping observer for {folder.path}")
                folder.watcher.observer.stop()
                folder.watcher.observer.join()
                try:
                    observers.remove(folder.watcher.observer)
                except Exception as error:
                    LOG.exception(error)
                    LOG.error("Failed to remove observer from observers?")
            except Exception as error:
                LOG.error("Error with watcher for {folder.path}")
                LOG.exception(error)


def init_db_jobs(db_jobs: dict, observers: list) -> None:
    for db_job_name, db_job in db_jobs.items():
        try:
            db_job.binlogs_folder.watcher.run()
            observers.append(db_job.binlogs_folder.watcher.observer)
            LOG.debug(
                f"mysqlDb.{db_job_name} - Successfully started monitoring Binary Logs dir"
            )
        except FileNotFoundError:
            LOG.warning(
                f"mysqlDb.{db_job_name} - Binary Logs directory does not yet exist."
            )
        try:
            db_job.dumps_folder.watcher.run()
            observers.append(db_job.dumps_folder.watcher.observer)
            LOG.debug(
                f"mysqlDb.{db_job_name} - Successfully started monitoring Dumps dir"
            )
        except FileNotFoundError:
            LOG.warning(f"mysqlDb.{db_job_name} - Dump directory does not yet exist.")


def cycle_over_db_jobs(db_jobs: dict, observers: list) -> None:
    for db_job_name, db_job in db_jobs.items():
        if not db_job.binlogs_folder.watcher.observer.is_alive():
            try:
                db_job.binlogs_folder.watcher.run()
                if db_job.binlogs_folder.watcher.observer not in observers:
                    observers.append(db_job.binlogs_folder.watcher.observer)
            except FileNotFoundError:
                LOG.debug(f"mysqlDb.{db_job_name} - BinLogs not yet available")
            except Exception as error:
                LOG.exception(error)


def final_dumps_db_jobs(db_jobs):
    for db_job_name, db_job in db_jobs.items():
        LOG.info(f"mysqlDb.{db_job_name} - Creating on exit DB Dump from binary logs")
        db_job.create_dump_from_binary_logs(
            lean_path(
                f"{db_job.dumps_folder.path}/"
                "from-binary-logs-exit_"
                f"{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
            )
        )
