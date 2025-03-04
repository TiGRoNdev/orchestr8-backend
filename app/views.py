# SPDX-License-Identifier: LGPL-2.1-or-later


import subprocess
import os
import psutil
import GPUtil

import aiohttp
import random
import string
import logging

from tenacity import retry, stop_after_attempt, wait_exponential
import bcrypt
import jwt
from sqlalchemy import select, func

from app.db import get_session
from app.core import get_gpu_info
from app.models import User, Storage, Pod


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


async def create_pod(name='', container_image='', cpu='', memory='', gpu=0, storage_id=0, port=80, session_key=''):
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
            storage_id=storage_id
        )
        session.add(pod)
        await session.flush()

        pod_file_name = os.environ['PODS_META_PATH'] + f"/{name_s}.yaml"
        with open(pod_file_name, "w") as f:
            f.write(f"""
                apiVersion: v1
                kind: Pod
                metadata:
                    name: {name_s}
                spec:{f'''
                      volumes:
                        - name: pv-storage
                          persistentVolumeClaim:
                              claimName: {storage.name}
                      '''
                      if storage_id != 0
                      else ''}
                      containers:
                            - name: {name}
                              image: {container_image}
                              resources:
                                limits:
                                  cpu: {cpu}
                                  memory: {memory}
                                  {f'nvidia.com/gpu: {gpu}' if gpu > 0 else ''}
                              ports:
                              - containerPort: {port}
                              {f'''
                              nodeSelector:
                                  hardware-type: gpu
                                ''' 
                                if gpu > 0 
                                else ''
                              }
                              {f'''
                              volumeMounts:
                                  - mountPath: "/"
                                    name: pv-storage
                                '''
                                if storage_id != 0
                                else ''
                              }
            """)

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


