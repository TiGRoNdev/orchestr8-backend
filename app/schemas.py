# SPDX-License-Identifier: LGPL-2.1-or-later


from pydantic import BaseModel


class Pod(BaseModel):
    name: str
    container_image: str
    cpu: str
    memory: str
    gpu: int
    port: int
    storage_id: int

class PodPort(BaseModel):
    port: int
    pod_id: int

class PodEnv(BaseModel):
    pod_id: int
    name: str
    value: str

class Storage(BaseModel):
    name: str
    capacity: str

class User(BaseModel):
    username: str
    password: str

class Id(BaseModel):
    id: int

