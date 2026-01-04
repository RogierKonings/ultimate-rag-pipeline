# GPU Workloads Runbook

This runbook documents GPU configuration for LLM, embedding, and reranker services in the RAG pipeline.

## Node Configuration

### Labels and Taints

GPU nodes must have the following configuration:

| Type | Key | Value | Effect |
|------|-----|-------|--------|
| **Label** | `gpu` | `true` | - |
| **Taint** | `nvidia.com/gpu` | `true` | `NoSchedule` |
| **Taint** | `gpu` | `true` | `NoSchedule` |

### Cloud Provider Commands

**GKE:**
```bash
gcloud container node-pools create gpu-pool \
  --cluster=rag-cluster \
  --machine-type=n1-standard-8 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --num-nodes=1 \
  --node-labels=gpu=true \
  --node-taints=nvidia.com/gpu=true:NoSchedule
```

**EKS:**
```bash
eksctl create nodegroup \
  --cluster=rag-cluster \
  --name=gpu-workers \
  --node-type=g4dn.xlarge \
  --nodes=1 \
  --node-labels=gpu=true
```

## Pod Configuration

### Required Settings for GPU Workloads

Every GPU workload (vLLM, embeddings, reranker) must include:

```yaml
spec:
  runtimeClassName: nvidia
  priorityClassName: gpu-high-priority
  nodeSelector:
    gpu: "true"
  tolerations:
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
    - key: gpu
      operator: Equal
      value: "true"
      effect: NoSchedule
  containers:
    - name: <container-name>
      resources:
        limits:
          nvidia.com/gpu: 1
        requests:
          nvidia.com/gpu: 1
```

### PDB Coverage

Add this label to pod templates for PodDisruptionBudget coverage:

```yaml
metadata:
  labels:
    gpu-workload: "true"
```

## Resource Classes

| Resource | Description |
|----------|-------------|
| `nvidia` | RuntimeClass for GPU containers |
| `gpu-high-priority` | PriorityClass (value: 1000000) |
| `gpu-workloads-pdb` | PodDisruptionBudget (minAvailable: 1) |

## Verification Commands

```bash
# Check GPU nodes
kubectl get nodes -l gpu=true -o wide

# Verify device plugin
kubectl get ds nvidia-device-plugin -n kube-system
kubectl logs -n kube-system -l app.kubernetes.io/name=nvidia-device-plugin

# Check GPU resources
kubectl describe node <gpu-node> | grep -A5 "Allocatable:"

# Test GPU scheduling
kubectl apply -f k8s/base/gpu-nodepool.yaml
kubectl wait --for=condition=complete job/gpu-test-job -n rag-pipeline --timeout=120s
kubectl logs job/gpu-test-job -n rag-pipeline
```

## Troubleshooting

### Pod Stuck in Pending

1. Check node GPU availability:
   ```bash
   kubectl describe node <gpu-node> | grep -A10 "Allocated resources"
   ```

2. Verify tolerations match taints:
   ```bash
   kubectl get pod <pod> -o yaml | grep -A10 tolerations
   kubectl describe node <gpu-node> | grep Taints
   ```

### nvidia-smi Not Found

1. Verify RuntimeClass is applied:
   ```bash
   kubectl get pod <pod> -o yaml | grep runtimeClassName
   ```

2. Check device plugin logs:
   ```bash
   kubectl logs -n kube-system -l app.kubernetes.io/name=nvidia-device-plugin
   ```

### GPU Not Detected

1. Verify node drivers:
   ```bash
   kubectl debug node/<gpu-node> -it --image=nvidia/cuda:12.2.0-base-ubuntu22.04 -- nvidia-smi
   ```

2. Check device plugin status:
   ```bash
   kubectl get ds nvidia-device-plugin -n kube-system
   kubectl describe ds nvidia-device-plugin -n kube-system
   ```
