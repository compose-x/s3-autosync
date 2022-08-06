ARG BASE_IMAGE=public.ecr.aws/ews-network/python:3.9

FROM $BASE_IMAGE as mysql-clients
COPY mariadb.repo /etc/yum.repos.d/mariadb.repo
RUN yum repolist; \
    yum update --security -y ;\
    yum install MariaDB-client --downloadonly; \
    find /var/cache/yum/ -iname "*mariadb*client*.rpm" | xargs -i rpm -Uvh {} --nodeps;\
    yum clean all; rm -rf /var/cache/yum

FROM $BASE_IMAGE as wheel
WORKDIR /app
COPY . /app
RUN pip install pip poetry -U
RUN poetry build


FROM mysql-clients as app
COPY --from=wheel /app/dist/*.whl /tmp/
RUN pip install pip --no-cache-dir -U; pip install /tmp/*.whl --no-cache-dir
ENTRYPOINT ["local-to-s3-watchdog"]
