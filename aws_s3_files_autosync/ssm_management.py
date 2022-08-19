#  SPDX-License-Identifier: MPL-2.0
#  Copyright 2020-2022 John Mille <john@compose-x.io>

"""
Management of the SSM parameter that stores the path to a file in S3.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Union

from boto3.session import Session
from compose_x_common.aws import get_session


class SsmParameter:
    def __init__(self, config: dict, session: Session = None):
        self._config = deepcopy(config)
        self.name = config["name"]
        self.session = get_session(session)

    @property
    def current(self) -> dict:
        return self.session.client("ssm").get_parameter(ParameterName=self.name)

    @property
    def current_value(self) -> str:
        return self.current["Value"]

    @current_value.setter
    def current_value(self, value: Union[str, dict, list]):
        if not isinstance(value, (str, list, dict)):
            raise TypeError(
                f"Unsupported type {type(value)}. Expected one of", (str, list, dict)
            )
        client = self.session.client("ssm")
        if isinstance(value, str):
            client.put_parameter(
                Name=self.name, Value=value, Type="String", Overwrite=True
            )
        elif isinstance(value, (dict, list)):
            client.put_parameter(
                Name=self.name, Value=json.dumps(value), Type="String", Overwrite=True
            )
