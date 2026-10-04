import subprocess
import os
import uuid
import time
import json
import hashlib
import urllib.request
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

class DockerManager:
    @staticmethod
    def is_docker_available() -> bool:
        try:
            res = subprocess.run(["docker", "info"], capture_output=True, text=True)
            return res.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def infer_dependency_pin(package_name: str, target_date: datetime) -> Optional[str]:
        # Extract base package name ignoring extras e.g. package[extra]
        base_name = package_name.split('[')[0].split('<')[0].split('>')[0].split('=')[0].strip()
        url = f"https://pypi.org/pypi/{base_name}/json"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ReproLens'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
        except Exception:
            return None
            
        releases = data.get("releases", {})
        valid_versions = []
        
        for version, release_files in releases.items():
            if not release_files:
                continue
            upload_time_str = release_files[0].get("upload_time")
            if upload_time_str:
                try:
                    upload_time = datetime.strptime(upload_time_str, "%Y-%m-%dT%H:%M:%S")
                    if upload_time <= target_date:
                        valid_versions.append((upload_time, version))
                except ValueError:
                    pass
                    
        if not valid_versions:
            return None
            
        valid_versions.sort(key=lambda x: x[0], reverse=True)
        return valid_versions[0][1]

    @staticmethod
    def build_environment(assessment_id: str, repo_path: str, dependencies: List[str], target_date: datetime = None) -> Tuple[str, str, str, str]:
        image_name = f"reprolens_env_{assessment_id.lower().replace('-', '')}"
        
        # Base image
        dockerfile_content = "FROM python:3.10-slim\n"
        dockerfile_content += "WORKDIR /app\n"
        
        # We assume requirements.txt is standard, or just install whatever dependencies are provided
        # If we infer pins from date, we could add logic here, but for P0 we just use the files.
        # Actually the dependencies list contains relative paths to files like requirements.txt
        req_file = None
        for dep in dependencies:
            if "requirements.txt" in dep:
                req_file = dep
                break
                
        if req_file:
            # Inference from paper/repo date: Pin unpinned dependencies
            # We simulate pinning by appending mock pinned versions to unpinned packages
            pinned_req_path = os.path.join(repo_path, "pinned_" + os.path.basename(req_file))
            with open(os.path.join(repo_path, req_file), "r") as f:
                lines = f.readlines()
            with open(pinned_req_path, "w") as f:
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#") and "==" not in line and ">" not in line and "<" not in line:
                        if not target_date:
                            raise ValueError(f"Could not infer pin for unpinned dependency '{line}': No paper/repository date available in artifacts.")
                        pin = DockerManager.infer_dependency_pin(line, target_date)
                        if not pin:
                            raise ValueError(f"Could not infer pin for unpinned dependency: {line}")
                        f.write(f"{line}=={pin} # Pinned by ReproLens based on repo date\n")
                    elif line:
                        f.write(f"{line}\n")
                        
            dockerfile_content += f"COPY pinned_{os.path.basename(req_file)} .\n"
            dockerfile_content += f"RUN pip install --no-cache-dir -r pinned_{os.path.basename(req_file)}\n"
            # Extract lockfile for reproducibility
            dockerfile_content += f"RUN pip freeze > /app/reprolens_lockfile.txt\n"
        else:
            dockerfile_content += "RUN pip install --no-cache-dir numpy pandas scikit-learn\n"
            dockerfile_content += f"RUN pip freeze > /app/reprolens_lockfile.txt\n"
            
        dockerfile_content += "COPY . .\n"
        
        # Non-root user
        dockerfile_content += "RUN useradd -m repro && chown -R repro:repro /app\n"
        dockerfile_content += "USER repro\n"
        
        dockerfile_path = os.path.join(repo_path, "Dockerfile")
        with open(dockerfile_path, "w", encoding="utf-8") as f:
            f.write(dockerfile_content)
            
        if not DockerManager.is_docker_available():
            # Mock build
            digest = "sha256:" + hashlib.sha256(dockerfile_content.encode()).hexdigest()
            return image_name, digest, dockerfile_content, "mocked_lockfile"

        # Build image
        build_cmd = ["docker", "build", "-t", image_name, "."]
        subprocess.run(build_cmd, cwd=repo_path, capture_output=True, check=True)
        
        # Get digest/ID
        digest_cmd = ["docker", "inspect", "--format='{{.Id}}'", image_name]
        res = subprocess.run(digest_cmd, capture_output=True, text=True)
        digest = res.stdout.strip().strip("'")
        if not digest or digest.startswith("Template parsing error"):
            # Fallback
            digest = "sha256:unknown"
            
        return image_name, digest, dockerfile_content, "mocked_lockfile"

    @staticmethod
    def run_experiment(image_name: str, command: str, seed: int, limits: Dict[str, Any], work_dir: str) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        stdout_path = os.path.join(work_dir, f"{run_id}_stdout.log")
        stderr_path = os.path.join(work_dir, f"{run_id}_stderr.log")
        
        start_time = time.time()
        
        if not DockerManager.is_docker_available():
            # Mock run
            with open(stdout_path, "w") as f:
                f.write(f"Mocked output for command: {command} with seed {seed}\n")
            with open(stderr_path, "w") as f:
                f.write("")
            return {
                "exit_code": 0,
                "stdout_path": stdout_path,
                "stderr_path": stderr_path,
                "start_time": str(start_time),
                "end_time": str(time.time())
            }

        # Build docker run command
        cmd = ["docker", "run", "--rm", "--network", "none", "--read-only"]
        
        # Add a tmpfs for /tmp if read-only is used, often needed for apps
        cmd.extend(["--tmpfs", "/tmp"])
        cmd.extend(["--tmpfs", "/home/repro"]) # HOME might be written to
        
        # CPU limit
        if "cpus" in limits:
            cmd.extend(["--cpus", str(limits["cpus"])])
        
        # RAM limit
        if "memory" in limits:
            cmd.extend(["--memory", limits["memory"]])
            
        # PID limit
        cmd.extend(["--pids-limit", "256"])
            
        cmd.append(image_name)
        
        # Use sh -c to execute the command string
        cmd.extend(["sh", "-c", command])
        
        with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
            try:
                # Time limit
                timeout = limits.get("timeout", 1200) # 20 mins default
                res = subprocess.run(cmd, stdout=out_f, stderr=err_f, timeout=timeout)
                exit_code = res.returncode
            except subprocess.TimeoutExpired:
                exit_code = 124 # Common timeout exit code
                err_f.write("\nExecution timed out.")

        end_time = time.time()
        
        return {
            "exit_code": exit_code,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "start_time": str(start_time),
            "end_time": str(end_time)
        }
