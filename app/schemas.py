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

class Storage(BaseModel):
    name: str
    capacity: str

class User(BaseModel):
    username: str
    password: str

class UserId(BaseModel):
    id: int

