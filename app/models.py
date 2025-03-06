# SPDX-License-Identifier: LGPL-2.1-or-later


from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class User(SQLModel, table=True):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("username"),)

    id: int | None = Field(None, primary_key=True)
    password: str
    username: str
    is_admin: bool
    session_key: str | None  # sha1(id|ip|user-agent)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": self.is_admin
        }


class Storage(SQLModel, table=True):
    __tablename__ = "storage"
    __table_args__ = (UniqueConstraint("name"),)

    id: int | None = Field(None, primary_key=True)
    name: str
    capacity: str

    # keys
    user_id: int = Field(index=True, foreign_key="user.id")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'capacity': self.capacity
        }


class Pod(SQLModel, table=True):
    __tablename__ = "pod"
    __table_args__ = (UniqueConstraint("name"),)

    id: int | None = Field(None, primary_key=True)
    name: str
    container_image: str
    cpu: str
    memory: str
    gpu: int
    port: int

    # keys
    user_id: int = Field(index=True, foreign_key="user.id")
    storage_id: int | None = Field(index=True, foreign_key="storage.id")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'cpu': self.cpu,
            'memory': self.memory,
            'gpu': self.gpu,
            'storage_id': self.storage_id
        }


class ReservedPort(SQLModel, table=True):
    __tablename__ = "reserved_port"
    __table_args__ = (UniqueConstraint("external_port"),)

    id: int | None = Field(None, primary_key=True)
    port: int
    external_port: int
    protocol: str | None = Field(default="TCP")

    # keys
    user_id: int = Field(index=True, foreign_key="user.id")
    pod_id: int = Field(index=True, foreign_key="pod.id")

    def to_dict(self):
        return {
            'id': self.id,
            'port': self.port,
            'external_port': self.external_port
        }


class PodEnv(SQLModel, table=True):
    __tablename__ = "pod_env"

    id: int | None = Field(None, primary_key=True)
    name: str
    value: str

    # keys
    user_id: int = Field(index=True, foreign_key="user.id")
    pod_id: int = Field(index=True, foreign_key="pod.id")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'value': self.value
        }




