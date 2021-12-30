# Run files_s3_autosync as a docker container

ARG BASE_IMAGE=public.ecr.aws/compose-x/python:3.9
FROM $BASE_IMAGE as security_updates

RUN yum upgrade --security -y; yum clean all; rm -rfv /var/cache/yum


FROM security_updates as wheel
WORKDIR /app
COPY . /app
RUN python -m pip install pip poetry -U
RUN poetry build

FROM security_updates as app
COPY --from=wheel /app/dist/*.whl /tmp/
RUN python -m pip install pip --no-cache-dir -U; pip install /tmp/*.whl --no-cache-dir

ENTRYPOINT ["files_s3_autosync"]
CMD ["-h"]
