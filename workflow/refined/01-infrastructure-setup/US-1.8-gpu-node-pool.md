# US-1.8: GPU Node Pool & NVIDIA Plugin

## Goal
Provide schedulable GPU capacity with NVIDIA device plugin, taints/tolerations, and node selectors to support LLM/embedding/reranker services.

## Requirements
- Create GPU node pool with taints (e.g., `gpu=true:NoSchedule`) and labels (e.g., `node.kubernetes.io/instance-type`).
- Install NVIDIA device plugin DaemonSet; verify `nvidia.com/gpu` resources advertised.
- Define resource classes/RuntimeClass if needed for GPU scheduling.
- Document tolerations/nodeSelectors for GPU workloads (vLLM, embeddings, reranker) and pod priority class.
- Add PodDisruptionBudget for GPU workloads (min available 1).

## Acceptance Criteria
- GPU node pool exists and advertises `nvidia.com/gpu` capacity; `kubectl describe node` shows allocatable GPUs.
- NVIDIA device plugin DaemonSet `Ready` on GPU nodes.
- Sample GPU pod scheduled using taint toleration and nodeSelector; `nvidia-smi` succeeds inside pod.
- PDB applied for GPU workloads; eviction respects availability.
- Runbook documents labels/taints/tolerations for GPU-bound deployments.

## Verification
- `kubectl get nodes -l gpu=true -o wide`
- `kubectl get ds nvidia-device-plugin -n kube-system`
- Deploy sample Job/Pod with `resources.limits/requests nvidia.com/gpu: 1` and validate scheduling/output.
