# SPDX-License-Identifier: LGPL-2.1-or-later

import subprocess
import json

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
