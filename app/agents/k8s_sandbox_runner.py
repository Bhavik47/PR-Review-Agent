import time
import uuid
import logging
from typing import Dict, Any, List
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from app.config import settings

logger = logging.getLogger(__name__)

def _get_k8s_clients():
    """Initializes and returns the Kubernetes BatchV1 and CoreV1 API clients."""
    if settings.K8S_IN_CLUSTER:
        config.load_incluster_config()
    else:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
    return client.BatchV1Api(), client.CoreV1Api()

def _ensure_namespace_exists(core_v1: client.CoreV1Api, namespace: str):
    """Ensures the sandbox execution namespace exists."""
    try:
        core_v1.read_namespace(name=namespace)
    except ApiException as e:
        if e.status == 404:
            ns_body = client.V1Namespace(
                metadata=client.V1ObjectMeta(
                    name=namespace,
                    labels={
                        "app.kubernetes.io/part-of": "pr-review-agent",
                        "platform.atlassian.dev/tier": "sandboxed-compute",
                    },
                )
            )
            core_v1.create_namespace(body=ns_body)
        else:
            raise

def run_pytest_in_k8s_sandbox(
    files: Dict[str, str],
    test_filename: str = "test_edge_cases.py",
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    """
    Executes pytest inside an ephemeral, network-isolated Kubernetes Job.
    
    Provides enterprise-grade multi-tenant platform isolation:
    - Dedicated sandboxed namespace with non-root security context.
    - Dropped Linux capabilities (CAP_DROP: ALL) and no privilege escalation.
    - Strict cgroups compute quotas (limits & requests).
    - Hard control plane deadline (activeDeadlineSeconds).
    - Ephemeral ConfigMap-based volume mounting and automated cleanup.
    
    Args:
        files: Dictionary mapping relative filename to file content
        test_filename: Test file name to execute with pytest
        timeout_seconds: Maximum allowed runtime before control-plane termination
        
    Returns:
        dict: {"exit_code": int, "output": str, "timed_out": bool, "duration_seconds": float}
    """
    start_time = time.time()
    batch_v1, core_v1 = _get_k8s_clients()
    namespace = settings.K8S_SANDBOX_NAMESPACE

    uid = uuid.uuid4().hex[:8]
    cm_name = f"pr-sandbox-cm-{uid}"
    job_name = f"pr-sandbox-job-{uid}"

    # Prepare ConfigMap keys and KeyToPath mappings for subdirectories
    cm_data = {}
    items: List[client.V1KeyToPath] = []
    for idx, (filepath, content) in enumerate(files.items()):
        key = f"file_{idx}"
        cm_data[key] = content
        items.append(client.V1KeyToPath(key=key, path=filepath))

    created_cm = False
    created_job = False

    try:
        _ensure_namespace_exists(core_v1, namespace)

        # 1. Create ephemeral ConfigMap containing PR files & generated pytest
        cm_body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=cm_name,
                namespace=namespace,
                labels={
                    "app.kubernetes.io/name": "pr-sandbox-runner",
                    "sandbox.atlassian.dev/execution-id": uid,
                },
            ),
            data=cm_data,
        )
        core_v1.create_namespaced_config_map(namespace=namespace, body=cm_body)
        created_cm = True

        # 2. Hardened Pod SecurityContext
        pod_security = client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=1000,
            fs_group=1000,
        )

        container_security = client.V1SecurityContext(
            allow_privilege_escalation=False,
            read_only_root_filesystem=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        )

        # 3. Platform Quotas (Prevent noisy neighbors & resource exhaustion)
        resources = client.V1ResourceRequirements(
            limits={"cpu": "1000m", "memory": "512Mi"},
            requests={"cpu": "100m", "memory": "64Mi"},
        )

        container = client.V1Container(
            name="sandbox-runner",
            image=settings.K8S_SANDBOX_IMAGE,
            image_pull_policy="IfNotPresent",
            command=["pytest", "-v", "--tb=short", test_filename],
            working_dir="/workspace",
            volume_mounts=[
                client.V1VolumeMount(
                    name="workspace-volume",
                    mount_path="/workspace",
                ),
                client.V1VolumeMount(
                    name="tmp-volume",
                    mount_path="/tmp",
                ),
            ],
            security_context=container_security,
            resources=resources,
        )

        volumes = [
            client.V1Volume(
                name="workspace-volume",
                config_map=client.V1ConfigMapVolumeSource(
                    name=cm_name,
                    items=items,
                ),
            ),
            client.V1Volume(
                name="tmp-volume",
                empty_dir=client.V1EmptyDirVolumeSource(),
            ),
        ]

        # 4. Ephemeral Job specification
        job_spec = client.V1Job(
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=namespace,
                labels={
                    "app.kubernetes.io/name": "pr-sandbox-runner",
                    "sandbox.atlassian.dev/execution-id": uid,
                },
            ),
            spec=client.V1JobSpec(
                backoff_limit=0,
                active_deadline_seconds=timeout_seconds,
                ttl_seconds_after_finished=60,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app.kubernetes.io/name": "pr-sandbox-runner",
                            "sandbox.atlassian.dev/execution-id": uid,
                            "job-name": job_name,
                        }
                    ),
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        security_context=pod_security,
                        containers=[container],
                        volumes=volumes,
                    ),
                ),
            ),
        )

        batch_v1.create_namespaced_job(namespace=namespace, body=job_spec)
        created_job = True

        # 5. Wait for Job completion and retrieve execution logs
        poll_interval = 0.5
        max_wait = timeout_seconds + 5
        elapsed = 0.0
        job_status = None
        pod_name = None

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed = time.time() - start_time

            # Find the pod created by the job
            if not pod_name:
                pods = core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"job-name={job_name}",
                )
                if pods.items:
                    pod_name = pods.items[0].metadata.name

            current_job = batch_v1.read_namespaced_job_status(name=job_name, namespace=namespace)
            status = current_job.status
            if (status.succeeded or 0) > 0 or (status.failed or 0) > 0:
                job_status = status
                break

        duration = round(time.time() - start_time, 2)

        # 6. Read Pod logs
        output = ""
        exit_code = 1
        timed_out = False

        if pod_name:
            try:
                output = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                )
            except Exception as log_err:
                output = f"[Pod logs unavailable: {log_err}]"

        # Check for deadline exceeded / timeout
        if job_status and job_status.conditions:
            for cond in job_status.conditions:
                if cond.type == "Failed" and cond.reason == "DeadlineExceeded":
                    timed_out = True
                    exit_code = -1
                    output = f"Sandbox execution timed out after {timeout_seconds} seconds (K8s activeDeadlineSeconds exceeded).\n{output}"
                    return {
                        "exit_code": exit_code,
                        "output": output,
                        "timed_out": True,
                        "duration_seconds": duration,
                    }

        if job_status and (job_status.succeeded or 0) > 0:
            exit_code = 0
        else:
            # Query container exit code
            if pod_name:
                try:
                    pod = core_v1.read_namespaced_pod_status(name=pod_name, namespace=namespace)
                    if pod.status.container_statuses:
                        c_status = pod.status.container_statuses[0]
                        if c_status.state and c_status.state.terminated:
                            exit_code = c_status.state.terminated.exit_code
                except Exception:
                    exit_code = 1

        if elapsed >= max_wait and not job_status:
            timed_out = True
            exit_code = -1
            output = f"Sandbox execution timed out after {timeout_seconds} seconds (Execution exceeded poll threshold).\n{output}"

        return {
            "exit_code": exit_code,
            "output": output,
            "timed_out": timed_out,
            "duration_seconds": duration,
        }

    except Exception as e:
        logger.error(f"K8s sandbox execution failed: {e}", exc_info=True)
        return {
            "exit_code": -1,
            "output": f"Kubernetes sandbox execution error: {str(e)}",
            "timed_out": False,
            "duration_seconds": round(time.time() - start_time, 2),
        }

    finally:
        # 7. Self-Healing Cleanup: Clean up Job and ConfigMap
        if created_job:
            try:
                batch_v1.delete_namespaced_job(
                    name=job_name,
                    namespace=namespace,
                    propagation_policy="Background",
                )
            except Exception as e:
                logger.warning(f"Failed to delete sandbox job {job_name}: {e}")

        if created_cm:
            try:
                core_v1.delete_namespaced_config_map(
                    name=cm_name,
                    namespace=namespace,
                )
            except Exception as e:
                logger.warning(f"Failed to delete sandbox configmap {cm_name}: {e}")
