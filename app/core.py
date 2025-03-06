# SPDX-License-Identifier: LGPL-2.1-or-later


import subprocess
import json
import os


def get_gpu_info():
    # Get nodes with GPU capacity
    nodes = json.loads(subprocess.check_output(
        "microk8s kubectl get nodes -o json", shell=True
    ))["items"]

    # Cluster-wide totals
    total_gpus = 0
    allocated_gpus = 0

    # Per-node breakdown
    node_info = []

    # Get GPU resource name (default to NVIDIA)
    gpu_resource = "nvidia.com/gpu"

    # Process nodes
    for node in nodes:
        capacity = node["status"].get("capacity", {})
        if gpu_resource in capacity:
            node_name = node["metadata"]["name"]
            node_total = int(capacity[gpu_resource])
            total_gpus += node_total

            # Get allocated GPUs for this node
            node_allocated = 0
            pods = json.loads(subprocess.check_output(
                f"microk8s kubectl get pods --all-namespaces --field-selector spec.nodeName={node_name} -o json",
                shell=True
            ))["items"]

            for pod in pods:
                for container in pod["spec"]["containers"]:
                    requests = container.get("resources", {}).get("requests", {})
                    node_allocated += int(requests.get(gpu_resource, 0))

            node_available = node_total - node_allocated
            allocated_gpus += node_allocated
            node_info.append({
                "node": node_name,
                "total": node_total,
                "allocated": node_allocated,
                "available": node_available
            })

    # Calculate cluster-wide available
    available_gpus = total_gpus - allocated_gpus

    return {
        "cluster": {
            "total": total_gpus,
            "allocated": allocated_gpus,
            "available": available_gpus
        },
        "nodes": node_info
    }


def get_pod_info(pod_name):
    return json.loads(subprocess.check_output(
        f"microk8s kubectl get pod {pod_name} -n default -o json", shell=True
    ))


def create_pod_yaml(pod_name='', storage_id=0, container_image='', storage_name='', cpu=0, memory=0, gpu=0, port=0, env=[]):
    pod_file_name = os.environ['PODS_META_PATH'] + f"/{pod_name}.yaml"
    with open(pod_file_name, "w") as f:
        f.write(f"""
            apiVersion: v1
            kind: Pod
            metadata:
                name: {pod_name}
            spec:{f'''
                  volumes:
                    - name: pv-storage
                      persistentVolumeClaim:
                          claimName: {storage_name}
                  '''
                  if storage_id != 0
                  else ''}
                  containers:
                        - name: {pod_name}
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
                              - mountPath: "/workspace"
                                name: pv-storage
                            '''
                          if storage_id != 0
                          else ''
                          }
                          {
                          '''
                          env:
                          '''
                          if env 
                          else ''
                          }
                          {'\n'.join([f'''
                              - name: {e['name']}
                                value: '{e['value']}'
                            ''' for e in env])
                          if env 
                          else ''
                          }
        """)

    return pod_file_name


