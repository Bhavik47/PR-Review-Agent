FROM python:3.11-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app
COPY ./operator ./operator

ENV PYTHONUNBUFFERED=1
ENV SANDBOX_BACKEND=kubernetes
ENV K8S_IN_CLUSTER=true

CMD ["kopf", "run", "--all-namespaces", "operator/controller.py"]
