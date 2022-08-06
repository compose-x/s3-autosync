# Run files_s3_autosync as a docker container

ARG BASE_IMAGE=public.ecr.aws/ews-network/python:3.9
FROM $BASE_IMAGE as security_updates

FROM $BASE_IMAGE as wheel
WORKDIR /app
COPY . /app
RUN pip install pip poetry -U
RUN poetry build


FROM $BASE_IMAGE as with-mysql
COPY mariadb.repo /etc/yum.repos.d/mariadb.repo
RUN yum install mariadb --downloadonly; find /var/cache/yum/ -iname "*mariadb*client*.rpm" | xargs -i rpm -Uvh {} --nodeps;\
    yum clean all; rm -rf /var/cache/yum

FROM with-mysql as app
RUN yum update --security -y; yum clean all; rm -rv /var/cache/yum
COPY --from=wheel /app/dist/*.whl /tmp/
RUN pip install pip --no-cache-dir -U; pip install /tmp/*.whl --no-cache-dir
ENTRYPOINT ["local-to-s3-watchdog"]
