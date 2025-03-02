# SPDX-License-Identifier: LGPL-2.1-or-later


FROM nvidia/cuda:12.8.0-base-ubuntu24.04

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt

RUN pip3 install -r requirements.txt --break-system-packages

COPY . .

ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
ENV PATH=/root/.local/bin:$PATH

EXPOSE 4101

CMD python3 main.py
