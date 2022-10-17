ARG BUILD_IMAGE=public.ecr.aws/ews-network/python:3.9
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.9.15-alpine


FROM $BUILD_IMAGE as wheel
WORKDIR /app
RUN pip install pip poetry -U
COPY . /app
RUN poetry build

FROM $BASE_IMAGE as app
RUN apk add mariadb-client
COPY --from=wheel /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl --no-cache-dir
ENTRYPOINT ["python", "-u", "-m", "aws_s3_files_autosync.cli"]
