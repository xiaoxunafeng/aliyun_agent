#pip install docker
#这个 Backend 会在本地启动一个 Docker 容器，并将会话隔离在容器内部。

# - 核心功能 ：
#   - 自动生命周期管理 ：初始化时启动容器，结束时自动销毁 ( auto_remove=True )。
#   - 高效文件传输 ：使用 tar 流在宿主机和容器之间传输文件，支持批量操作。
#   - 资源限制 ：支持设置 CPU ( cpu_quota ) 和内存 ( memory_limit ) 限制，防止 Agent 耗尽本机资源。
#   - 网络控制 ：可选禁用网络 ( network_disabled=True ) 以增强安全性。
from __future__ import annotations

import io
import tarfile
import time
import uuid
from typing import Optional

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    SandboxBackendProtocol,
)
from deepagents.backends.sandbox import BaseSandbox

try:
    import docker
    from docker.errors import NotFound, APIError
except ImportError:
    docker = None

class DockerBackend(BaseSandbox):
    """Docker Sandbox backend implementation for DeepAgents.
    
    This backend uses a local Docker daemon to provide an isolated execution environment.
    It requires the `docker` python package and a running Docker daemon.
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        auto_remove: bool = True,
        cpu_quota: int = 50000,  # 50% CPU
        memory_limit: str = "512m",
        network_disabled: bool = False,
        working_dir: str = "/workspace",
        volumes: dict[str, dict[str, str]] | None = None,
    ) -> None:
        """Initialize Docker sandbox.

        Args:
            image: Docker image to use (default: "python:3.11-slim")
            auto_remove: Whether to remove the container on close (default: True)
            cpu_quota: CPU quota in microseconds (default: 50000)
            memory_limit: Memory limit (default: "512m")
            network_disabled: Whether to disable network access (default: False)
            working_dir: Working directory inside the container (default: "/workspace")
            volumes: Docker volumes configuration (e.g., {'/host/path': {'bind': '/container/path', 'mode': 'rw'}})
        """
        if docker is None:
            raise ImportError(
                "docker package is not installed. "
                "Please install it with `pip install docker`."
            )
        
        self.client = docker.from_env()
        self.image = image
        self.auto_remove = auto_remove
        self.working_dir = working_dir
        self.volumes = volumes or {}
        self._container = None
        
        # Start container
        try:
            # Ensure image exists
            try:
                self.client.images.get(image)
            except NotFound:
                print(f"Pulling image {image}...")
                self.client.images.pull(image)

            self._container = self.client.containers.run(
                image,
                command="tail -f /dev/null",  # Keep container running
                detach=True,
                tty=True,
                cpu_quota=cpu_quota,
                mem_limit=memory_limit,
                network_disabled=network_disabled,
                working_dir=working_dir,
                volumes=self.volumes,
            )
            
            # Ensure working directory exists
            self.execute(f"mkdir -p {working_dir}")
            
        except Exception as e:
            raise RuntimeError(f"Failed to start Docker container: {e}")

    @property
    def id(self) -> str:
        """Unique identifier for the sandbox backend."""
        return self._container.id if self._container else "unknown"

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox."""
        if not self._container:
            return ExecuteResponse(
                output="Container not running",
                exit_code=1,
                truncated=False
            )

        try:
            # Docker exec_run returns (exit_code, output)
            # output is bytes
            # Use list form for cmd to avoid shell quoting issues
            exit_code, output = self._container.exec_run(
                cmd=["bash", "-c", command],
                workdir=self.working_dir,
                demux=False # Combine stdout and stderr
            )
            
            return ExecuteResponse(
                output=output.decode("utf-8", errors="replace"),
                exit_code=exit_code,
                truncated=False, 
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error executing command: {str(e)}",
                exit_code=1,
                truncated=False,
            )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the sandbox using tar archive."""
        if not self._container:
            return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]

        responses = []
        
        # Create a tar archive in memory
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            for path, content in files:
                # Docker put_archive expects relative paths inside the tar to be relative to the destination
                # But here we want absolute paths to be respected. 
                # Actually put_archive extracts to a directory.
                # To support absolute paths, we should probably upload to root /? 
                # Or handle relative paths relative to working_dir.
                
                # Let's handle paths:
                # If path is absolute, we strip leading / and upload to root.
                # If path is relative, we upload to working_dir.
                
                # Simplification: We will create a tar with full structure and extract to /
                
                # Normalize path
                if path.startswith("/"):
                    arcname = path.lstrip("/")
                    dest_path = "/"
                else:
                    arcname = path
                    dest_path = self.working_dir

                info = tarfile.TarInfo(name=arcname)
                info.size = len(content)
                info.mtime = time.time()
                tar.addfile(info, io.BytesIO(content))
                
                responses.append(FileUploadResponse(path=path, error=None))

        tar_stream.seek(0)
        
        try:
            # We extract to / to support absolute paths in the tar
            # Note: This assumes all files in the batch can be extracted to the same root.
            # If mixed absolute/relative, this might be tricky.
            # For robustness, we might need to upload one by one if paths are mixed, 
            # or group them.
            # Strategy: Always extract to / (root), and ensure arcnames are full paths (without leading /)
            
            self._container.put_archive(
                path="/", 
                data=tar_stream
            )
        except Exception as e:
            # Mark all as failed if batch fails
            return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]

        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the sandbox."""
        if not self._container:
            return [FileDownloadResponse(path=p, error="permission_denied") for p in paths]

        responses = []
        for path in paths:
            try:
                # get_archive returns a tuple (generator, stat)
                bits, stat = self._container.get_archive(path)
                
                # Reconstruct tar from bits
                file_content = io.BytesIO()
                for chunk in bits:
                    file_content.write(chunk)
                file_content.seek(0)
                
                # Extract file from tar
                with tarfile.open(fileobj=file_content, mode='r') as tar:
                    # There should be only one file/dir
                    member = tar.next()
                    if member.isdir():
                        responses.append(FileDownloadResponse(path=path, error="is_directory"))
                        continue
                        
                    f = tar.extractfile(member)
                    if f:
                        content = f.read()
                        responses.append(FileDownloadResponse(path=path, content=content, error=None))
                    else:
                        responses.append(FileDownloadResponse(path=path, error="file_not_found"))

            except NotFound:
                responses.append(FileDownloadResponse(path=path, error="file_not_found"))
            except Exception as e:
                error_msg = str(e).lower()
                error = "invalid_path"
                if "permission" in error_msg:
                    error = "permission_denied"
                
                responses.append(FileDownloadResponse(path=path, content=None, error=error))
        return responses

    def close(self):
        """Close the sandbox session."""
        if self._container:
            try:
                if self.auto_remove:
                    self._container.remove(force=True)
                else:
                    self._container.stop()
            except Exception:
                pass
            self._container = None
