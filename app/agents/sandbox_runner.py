import os
import shutil
import tempfile
import time
import logging
from typing import Dict, Any
import docker
from app.config import settings

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "pr-sandbox-runner:latest"

def run_pytest_in_sandbox(
    files: Dict[str, str],
    test_filename: str = "test_edge_cases.py",
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    """
    Executes pytest inside an ephemeral sandbox. Automatically routes execution
    to either a Kubernetes Job or a Docker container based on settings.SANDBOX_BACKEND.
    """
    if getattr(settings, "SANDBOX_BACKEND", "docker").lower() == "kubernetes":
        from app.agents.k8s_sandbox_runner import run_pytest_in_k8s_sandbox
        logger.info("Executing test in Kubernetes-native ephemeral Job sandbox...")
        return run_pytest_in_k8s_sandbox(files, test_filename, timeout_seconds)

    logger.info("Executing test in Docker container sandbox...")
    return run_pytest_in_docker_sandbox(files, test_filename, timeout_seconds)

def run_pytest_in_docker_sandbox(
    files: Dict[str, str],
    test_filename: str = "test_edge_cases.py",
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    """
    Executes pytest inside an ephemeral, network-isolated Docker sandbox container.
    
    Args:
        files: Dictionary mapping filename to file content (e.g. {"feature.py": "...", "test_edge_cases.py": "..."})
        test_filename: Name of the test file to execute with pytest
        timeout_seconds: Hard timeout in seconds to kill runaway execution / infinite loops
        
    Returns:
        dict: {"exit_code": int, "output": str, "timed_out": bool, "duration_seconds": float}
    """
    temp_dir = tempfile.mkdtemp(prefix="pr_sandbox_")
    container = None
    start_time = time.time()

    try:
        # Write files into temporary workspace directory
        for filename, content in files.items():
            file_path = os.path.join(temp_dir, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        client = docker.from_env()

        # Mount directory into container /workspace
        volumes = {os.path.abspath(temp_dir): {"bind": "/workspace", "mode": "rw"}}

        container = client.containers.run(
            image=SANDBOX_IMAGE,
            command=["pytest", "-v", "--tb=short", test_filename],
            volumes=volumes,
            working_dir="/workspace",
            network_mode="none",
            mem_limit="512m",
            nano_cpus=1000000000,  # 1 CPU core max
            detach=True,
            stdout=True,
            stderr=True,
        )

        # Wait with timeout
        try:
            wait_result = container.wait(timeout=timeout_seconds)
            exit_code = wait_result.get("StatusCode", 1)
            raw_logs = container.logs(stdout=True, stderr=True)
            output = raw_logs.decode("utf-8", errors="replace")
            duration = round(time.time() - start_time, 2)

            return {
                "exit_code": exit_code,
                "output": output,
                "timed_out": False,
                "duration_seconds": duration,
            }

        except Exception as e:
            # Check for timeout
            duration = round(time.time() - start_time, 2)
            try:
                container.kill()
            except Exception:
                pass
            return {
                "exit_code": -1,
                "output": f"Sandbox execution timed out after {timeout_seconds} seconds (infinite loop or resource exhaustion). Error: {str(e)}",
                "timed_out": True,
                "duration_seconds": duration,
            }

    except Exception as e:
        logger.error(f"Sandbox runner failure: {e}", exc_info=True)
        return {
            "exit_code": -1,
            "output": f"Sandbox execution failed to start: {str(e)}",
            "timed_out": False,
            "duration_seconds": round(time.time() - start_time, 2),
        }

    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
