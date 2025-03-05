# SPDX-License-Identifier: LGPL-2.1-or-later


import json
import logging
import traceback

from fastapi import APIRouter, Request, Response, WebSocket

from app.core import get_pod_info
from app.views import (
    get_docker_token,
    docker_search_image,
    create_pod,
    create_volume,
    get_pods,
    get_volumes,
    register,
    login,
    get_stat,
    get_gpus_available,
    get_users,
    delete_user,
    delete_pod,
    delete_volume,
    add_exposed_port_to_pod,
    get_pod_envs,
    add_pod_env,
    recreate_pod,
    get_pod_logs_realtime,
    auth_ws
)
from app.schemas import Pod, Storage, User, Id, PodPort, PodEnv


router = APIRouter()


@router.get("/api/docker/token")
async def docker_token():
    return {"token": await get_docker_token()}


@router.get("/api/docker/search")
async def docker_search(text: str, request: Request):
    return {"data": await docker_search_image(text, {"Authorization": request.headers.get("Authorization")})}


@router.post("/api/pod")
async def create_pod_route(item: Pod, request: Request):
    status, res = await create_pod(
        name=item.name,
        container_image=item.container_image,
        cpu=item.cpu,
        gpu=item.gpu,
        memory=item.memory,
        port=item.port,
        storage_id=item.storage_id,
        session_key=request.headers.get("Authorization")
    )
    return Response(res, status_code=status)


@router.get("/api/pod")
async def get_pods_route(request: Request):
    status, res = await get_pods(session_key=request.headers.get("Authorization"))
    pods = [{**(i.to_dict()), "k8s_info": get_pod_info(i.name)} for i in res]

    if status == 200:
        return Response(json.dumps(pods), status_code=status)
    else:
        return Response(res, status_code=status)


@router.delete("/api/pod")
async def delete_pod_route(item: Id, request: Request):
    status, res = await delete_pod(pod_id=item.id, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.post("/api/pod/port")
async def add_port_route(item: PodPort, request: Request):
    status, res = await add_exposed_port_to_pod(pod_id=item.pod_id, port=item.port, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.post("/api/volume")
async def create_volume_route(item: Storage, request: Request):
    status, res = await create_volume(name=item.name, capacity=item.capacity, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.get("/api/volume")
async def get_volumes_route(request: Request):
    status, res = await get_volumes(session_key=request.headers.get("Authorization"))
    if status == 200:
        return Response(json.dumps([i.to_dict() for i in res]), status_code=status)
    else:
        return Response(res, status_code=status)


@router.delete("/api/volume")
async def delete_volume_route(item: Id, request: Request):
    status, res = await delete_volume(volume_id=item.id, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.get("/api/gpu")
async def get_gpus_route(request: Request):
    status, res = await get_gpus_available(session_key=request.headers.get("Authorization"))
    if status == 200:
        return Response(json.dumps(res), status_code=status)
    else:
        return Response(res, status_code=status)


@router.post("/api/register")
async def register_route(item: User, request: Request):
    status, res = await register(username=item.username, password=item.password, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.post("/api/login")
async def login_route(item: User):
    status, res = await login(username=item.username, password=item.password)
    return Response(res, status_code=status)


@router.get("/api/stat")
async def stat(request: Request):
    status, res = await get_stat(session_key=request.headers.get("Authorization"))
    if status == 200:
        return Response(json.dumps(res), status_code=status)
    else:
        return Response(res, status_code=status)


@router.get("/api/users")
async def users(request: Request):
    status, res = await get_users(session_key=request.headers.get("Authorization"))
    if status == 200:
        return Response(json.dumps([i.to_dict() for i in res]), status_code=status)
    else:
        return Response(res, status_code=status)


@router.delete("/api/register")
async def login_route(item: Id, request: Request):
    status, res = await delete_user(user_id=item.id, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.get("/api/pod/{pod_id}/env")
async def get_pod_envs_route(request: Request, pod_id: int):
    status, res = await get_pod_envs(pod_id=pod_id, session_key=request.headers.get("Authorization"))
    if status == 200:
        return Response(json.dumps([i.to_dict() for i in res]), status_code=status)
    else:
        return Response(res, status_code=status)


@router.post("/api/pod/env")
async def add_pod_env_route(item: PodEnv, request: Request):
    status, res = await add_pod_env(pod_id=item.pod_id, name=item.name, value=item.value, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.patch("/api/pod/{pod_id}")
async def recreate_pod_route(request: Request, pod_id: int):
    status, res = await recreate_pod(pod_id=pod_id, session_key=request.headers.get("Authorization"))
    return Response(res, status_code=status)


@router.websocket("/ws/logs/{pod_id}")
async def get_logs_realtime(websocket: WebSocket, pod_id: int):
    await websocket.accept()
    try:
        token = await websocket.receive_text()
        if not await auth_ws(token, pod_id=pod_id):
            await websocket.close(
                code=1008,
                reason="Invalid credentials."
            )
            return

        await get_pod_logs_realtime(websocket, pod_id=pod_id)
    except:
        logging.error(traceback.format_exc())
        await websocket.close(code=1011, reason="Internal error.")
