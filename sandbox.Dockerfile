FROM python:3.11-slim
COPY docker_wheels /tmp/docker_wheels
RUN pip install --no-index --find-links=/tmp/docker_wheels pytest && rm -rf /tmp/docker_wheels
WORKDIR /workspace
