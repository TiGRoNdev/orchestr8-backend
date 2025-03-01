# SPDX-License-Identifier: LGPL-2.1-or-later


FROM python:latest

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip3 install -r requirements.txt

COPY . .

ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
ENV PATH=/root/.local/bin:$PATH

EXPOSE 4101

CMD python3 main.py
