# SPDX-License-Identifier: LGPL-2.1-or-later


import subprocess
import os
import re
import psutil
import GPUtil

import asyncio
import aiohttp
import random
import string
import logging

from fastapi import WebSocket
from tenacity import retry, stop_after_attempt, wait_exponential
import bcrypt
import jwt
from sqlalchemy import select, func

from app.db import get_session
from app.core import get_gpu_info, create_pod_yaml
from app.models import User, Storage, Pod, ReservedPort, PodEnv


@retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=0.2, max=3))
async def get_docker_token():
    async with aiohttp.ClientSession() as session:
        url = f"https://auth.docker.io/token"
        async with session.get(url) as response:
            if response.status == 200:
                token = await response.json()
                token = token['token']
            else:
                logging.error(f"Cannot get token cause of: {await response.text()}")
                token = None

        return token


@retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=0.2, max=3))
async def docker_search_image(text, headers):
    async with aiohttp.ClientSession() as session:
        url = f"https://hub.docker.com/api/search/v4?query=${text}&from=0&size=20"
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
            else:
                print(headers, url)
                logging.error(f"Cannot get search results cause of: {await response.text()}")
                data = None

        return data


async def create_volume(name='', capacity='', session_key=''):
    session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        name_s = name.strip().replace(" ", "_")

        storage = Storage(
            name=name_s,
            capacity=capacity,
            user_id=user.id
        )
        session.add(storage)
        await session.flush()

        storage_file_name = os.environ['VOLUMES_META_PATH'] + f"/{name_s}.yaml"
        with open(storage_file_name, "w") as f:
            f.write(f"""
                apiVersion: v1
                kind: PersistentVolumeClaim
                metadata:
                    name: {name_s}
                spec:
                    storageClassName: manual
                    accessModes:
                        - ReadWriteOncePod
                    resources:
                        requests:
                            storage: {capacity}
            """)

        subprocess.run(f"microk8s kubectl apply -f {storage_file_name}", shell=True)

    return 200, "OK."


async def get_volumes(session_key=''):
    session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        storages = (await session.execute(select(Storage).where(Storage.user_id == session_jwt['id']))).scalars()

    return 200, storages


async def create_pod(name='', container_image='', cpu='', memory='', mount_path='/workspace', gpu=0, storage_id=0, port=80, session_key=''):
    session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        storages = (await session.execute(select(Storage).where(Storage.user_id == session_jwt['id']))).scalars()
        storage = None
        for store in storages:
            if store.id == storage_id:
                storage = store

        name_s = name.strip().replace(" ", "_")

        pod = Pod(
            name=name_s,
            container_image=container_image,
            cpu=cpu,
            memory=memory,
            gpu=gpu,
            port=port,
            user_id=user.id,
            storage_id=storage_id if storage_id != 0 else None,
            mount_path=mount_path
        )
        session.add(pod)
        await session.flush()

        pod_file_name = create_pod_yaml(
            pod_name=name_s,
            storage_id=storage_id,
            container_image=container_image,
            storage_name=storage.name if storage_id != 0 else None,
            cpu=cpu,
            memory=memory,
            gpu=gpu,
            port=port,
            mount_path=mount_path
        )

        subprocess.run(f"microk8s kubectl apply -f {pod_file_name}", shell=True)

    return 200, "OK."


async def get_pods(session_key=''):
    session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()

    return 200, pods


async def register(username='', password='', session_key=''):
    async with get_session() as session:
        is_admin = False
        users = (await session.execute(select(func.count()).select_from(User))).scalar()
        if users == 0:
            is_admin = True

        if users > 0:
            session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
            user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
            if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
                return 403, "Invalid credentials."
            if not user.is_admin:
                return 403, "Invalid credentials."

        user = User(
            username=username,
            password=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            is_admin=is_admin
        )
        session.add(user)
        await session.flush()

        key = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(30))
        session_jwt = jwt.encode({
            'id': user.id,
            'key': key
        }, os.environ['SECRET_KEY'], algorithm="HS256")

        user.session_key = bcrypt.hashpw(key.encode(), bcrypt.gensalt()).decode()

    return 200, session_jwt


async def login(username='', password=''):
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.username == username))).scalar()
        if not user:
            users = (await session.execute(select(func.count()).select_from(User))).scalar()
            if users == 0:
                return await register(username, password)
            else:
                return 403, "Invalid credentials."

        if not bcrypt.checkpw(password.encode(), user.password.encode()):
            return 403, "Invalid credentials."

        key = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(30))
        session_jwt = jwt.encode({
            'id': user.id,
            'key': key
        }, os.environ['SECRET_KEY'], algorithm="HS256")

        user.session_key = bcrypt.hashpw(key.encode(), bcrypt.gensalt()).decode()
        session.add(user)

    return 200, session_jwt


async def get_stat(session_key=''):
    session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

    stat = {
        'cpu': {},
        'ram': {},
        'disk': {},
        'gpu': [],
        'power': {}
    }
    stat['cpu']['used'] = psutil.cpu_percent()
    stat['cpu']['free'] = 100.0 - stat['cpu']['used']

    stat['ram']['used'] = psutil.virtual_memory().percent
    stat['ram']['free'] = psutil.virtual_memory().available * 100 / psutil.virtual_memory().total

    stat['disk']['used'] = psutil.disk_usage('/').percent
    stat['disk']['free'] = 100.0 - stat['disk']['used']

    gpus = GPUtil.getGPUs()
    for gpu in gpus:
        gpu_dict = {
            'load': gpu.load * 100.0,
            'memory': gpu.memoryUsed / gpu.memoryTotal
        }
        stat['gpu'].append(gpu_dict)

    return 200, stat


async def get_gpus_available(session_key=''):
    session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

    return 200, get_gpu_info()


async def get_users(session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."
        if not user.is_admin:
            return 403, "Invalid credentials."

        users = (await session.execute(select(User))).scalars()

    return 200, users


async def delete_user(user_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."
        if not user.is_admin:
            return 403, "Invalid credentials."

        user = (await session.execute(select(User).where(User.id == user_id))).scalar()
        await session.delete(user)

    return 200, "Done."


async def delete_pod(pod_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]

        reserved_ports = (await session.execute(select(ReservedPort).where(
            ReservedPort.user_id == session_jwt['id'],
            ReservedPort.pod_id == pod.id
        ))).scalars()
        for reserved_port in reserved_ports:
            await session.delete(reserved_port)
            subprocess.run(f"microk8s kubectl delete svc {pod.name}-{reserved_port.port} -n default", shell=True)

        envs = (await session.execute(select(PodEnv).where(
            PodEnv.user_id == session_jwt['id'],
            PodEnv.pod_id == pod.id
        ))).scalars()
        for env in envs:
            await session.delete(env)

    async with get_session() as session:
        regex = re.compile(f"{pod.name}.*")
        pod_file_names = [
            i
            for i in os.listdir(os.environ['PODS_META_PATH'])
            if re.match(regex, i)
        ]
        for pod_file_name in pod_file_names:
            os.remove(f"{os.environ['PODS_META_PATH']}/{pod_file_name}")

        await session.delete(pod)

        subprocess.run(f"microk8s kubectl delete pod {pod.name} -n default", shell=True)

    return 200, "Done."


async def get_pod_ports(pod_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]

        pod_ports = (await session.execute(select(ReservedPort).where(
            ReservedPort.user_id == session_jwt['id'],
            ReservedPort.pod_id == pod.id
        ))).scalars()

    return 200, pod_ports


async def add_exposed_port_to_pod(pod_id=0, port=0, protocol='TCP', session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]
        reserved_ports = (await session.execute(select(ReservedPort).where(
            ReservedPort.user_id == session_jwt['id'],
            ReservedPort.pod_id == pod.id
        ))).scalars()
        if port in [i.port for i in reserved_ports]:
            return 400, "Invalid Request."

        port_to_reserve = (await session.execute(select(func.max(ReservedPort.external_port)))).scalar()
        if not port_to_reserve:
            port_to_reserve = 30001
        else:
            port_to_reserve += 1

        reserved_port = ReservedPort(
            port=port,
            external_port=port_to_reserve,
            protocol=protocol,
            user_id=user.id,
            pod_id=pod.id
        )
        session.add(reserved_port)
        await session.flush()

        service_yaml = f"""
            apiVersion: v1
            kind: Service
            metadata:
              name: {pod.name}-{reserved_port.port}
            spec:
              type: NodePort
              ports:
                - protocol: {protocol}
                  port: {reserved_port.port}
                  targetPort: {reserved_port.port}
                  nodePort: {reserved_port.external_port}
              selector:
                app.kubernetes.io/name: {pod.name}
        """

        pod_file_name = os.environ['PODS_META_PATH'] + f"/{pod.name}-{reserved_port.port}.yaml"
        with open(pod_file_name, "w") as f:
            f.write(service_yaml)

        subprocess.run(f"microk8s kubectl apply -f {pod_file_name}", shell=True)

    return 200, "Done."


async def delete_exposed_port(pod_id=0, port_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]

        reserved_ports = (await session.execute(select(ReservedPort).where(ReservedPort.user_id == session_jwt['id']))).scalars()
        reserved_ports = [i for i in reserved_ports]
        if not port_id in [i.id for i in reserved_ports]:
            return 403, "Invalid credentials."

        reserved_port = [i for i in reserved_ports if i.id == port_id][0]

        reserved_port_file_name = os.environ['PODS_META_PATH'] + f"/{pod.name}-{reserved_port.port}.yaml"
        os.remove(reserved_port_file_name)

        await session.delete(reserved_port)

        subprocess.run(f"microk8s kubectl delete svc {pod.name}-{reserved_port.port} -n default", shell=True)

    return 200, "Done."


async def get_pod_envs(pod_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]

        pod_envs = (await session.execute(select(PodEnv).where(
            PodEnv.user_id == session_jwt['id'],
            PodEnv.pod_id == pod.id
        ))).scalars()

    return 200, pod_envs


async def add_pod_env(pod_id=0, name='', value='', session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]
        pod_env = PodEnv(
            name=name,
            value=value,
            user_id=user.id,
            pod_id=pod.id
        )
        session.add(pod_env)
        await session.flush()

    return 200, "Done."


async def delete_pod_env(pod_id=0, env_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        envs = (await session.execute(select(PodEnv).where(PodEnv.user_id == session_jwt['id']))).scalars()
        envs = [i for i in envs]
        if not env_id in [i.id for i in envs]:
            return 403, "Invalid credentials."

        env = [i for i in envs if i.id == env_id][0]
        await session.delete(env)

    return 200, "Done."


async def delete_volume(volume_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        volumes = (await session.execute(select(Storage).where(Storage.user_id == session_jwt['id']))).scalars()
        volumes = [i for i in volumes]
        if not volume_id in [i.id for i in volumes]:
            return 403, "Invalid credentials."

        volume = [i for i in volumes if i.id == volume_id][0]

        volume_file_name = os.environ['VOLUMES_META_PATH'] + f"/{volume.name}.yaml"
        os.remove(volume_file_name)

        await session.delete(volume)

        subprocess.run(f"microk8s kubectl delete pvc {volume.name}", shell=True)

    return 200, "Done."


async def recreate_pod(pod_id=0, session_key=''):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return 403, "Invalid credentials."

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        pods = [i for i in pods]
        if not pod_id in [i.id for i in pods]:
            return 403, "Invalid credentials."

        pod = [i for i in pods if i.id == pod_id][0]
        pod_envs = (await session.execute(select(PodEnv).where(
            PodEnv.user_id == session_jwt['id'],
            PodEnv.pod_id == pod.id
        ))).scalars()

        if pod_envs:
            pod_envs = [pod_env.to_dict() for pod_env in pod_envs]

        storage = None
        if pod.storage_id:
            storage = (await session.execute(select(Storage).where(
                Storage.user_id == session_jwt['id'],
                Storage.id == pod.storage_id
            ))).scalar()

        subprocess.run(f"microk8s kubectl delete pod {pod.name} -n default", shell=True)

        pod_file_name = create_pod_yaml(
            pod_name=pod.name,
            storage_id=storage.id if storage else 0,
            container_image=pod.container_image,
            storage_name=storage.name if storage else '',
            cpu=pod.cpu,
            memory=pod.memory,
            gpu=pod.gpu,
            port=pod.port,
            env=pod_envs if pod_envs else [],
            mount_path=pod.mount_path
        )

        subprocess.run(f"microk8s kubectl apply -f {pod_file_name}", shell=True)

    return 200, "Done."


async def get_pod_logs_realtime(ws: WebSocket, pod_id=0):
    async with get_session() as session:
        pods = (await session.execute(select(Pod).where(Pod.id == pod_id))).scalars()
        pod = [i for i in pods if i.id == pod_id][0]

    command = [
        "microk8s",
        "kubectl",
        "logs",
        pod.name,
        "-n",
        "default",
        "-f",
    ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await ws.send_text(line.decode().strip())

    except Exception as e:
        await ws.close(code=1011, reason=str(e))
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()


async def auth_ws(session_key, pod_id=0):
    async with get_session() as session:
        session_jwt = jwt.decode(session_key, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user = (await session.execute(select(User).where(User.id == session_jwt['id']))).scalar()
        if not bcrypt.checkpw(session_jwt['key'].encode(), user.session_key.encode()):
            return False

        pods = (await session.execute(select(Pod).where(Pod.user_id == session_jwt['id']))).scalars()
        if not pod_id in [i.id for i in pods]:
            return False

    return True
