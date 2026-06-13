from __future__ import annotations

import base64
from typing import Any, Optional

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    SandboxBackendProtocol,
)
from deepagents.backends.sandbox import BaseSandbox

try:
    from e2b import Sandbox
except ImportError:
    Sandbox = None

class E2BBackend(BaseSandbox):
    """E2B Sandbox backend implementation for DeepAgents.
    
    This backend uses E2B (https://e2b.dev) to provide a secure, isolated 
    execution environment.
    """

    def __init__(
        self,
        template: str = "base",
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> None:
        """Initialize E2B sandbox.

        Args:
            template: E2B sandbox template ID (default: "base")
            api_key: E2B API key (optional, defaults to E2B_API_KEY env var)
            timeout: Sandbox timeout in seconds
            metadata: Custom metadata for the sandbox
        """
        if Sandbox is None:
            raise ImportError(
                "e2b package is not installed. "
                "Please install it with `pip install e2b`."
            )
            
        self.sandbox = Sandbox.create(
            template=template,
            api_key=api_key,
            timeout=timeout,
            metadata=metadata,
        )

    @property
    def id(self) -> str:
        """Unique identifier for the sandbox backend."""
        return self.sandbox.sandbox_id

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox."""
        try:
            # E2B commands.run returns CommandResult with stdout, stderr, exit_code
            result = self.sandbox.commands.run(command)
            
            return ExecuteResponse(
                output=result.stdout + result.stderr,
                exit_code=result.exit_code,
                truncated=False, 
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error executing command: {str(e)}",
                exit_code=1,
                truncated=False,
            )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the sandbox."""
        responses = []
        for path, content in files:
            try:
                # Ensure directory exists before writing
                # We can use execute to mkdir -p
                parent_dir = path.rsplit("/", 1)[0]
                if parent_dir:
                    self.sandbox.commands.run(f"mkdir -p {parent_dir}")
                
                # Write file
                self.sandbox.files.write(path, content)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                error_msg = str(e).lower()
                error = "invalid_path"
                if "permission" in error_msg:
                    error = "permission_denied"
                
                responses.append(FileUploadResponse(path=path, error=error))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the sandbox."""
        responses = []
        for path in paths:
            try:
                content = self.sandbox.files.read(path)
                # Ensure content is bytes
                if isinstance(content, str):
                    content = content.encode("utf-8")
                
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception as e:
                error_msg = str(e).lower()
                error = "invalid_path"
                if "not found" in error_msg:
                    error = "file_not_found"
                elif "directory" in error_msg:
                    error = "is_directory"
                elif "permission" in error_msg:
                    error = "permission_denied"
                
                responses.append(FileDownloadResponse(path=path, content=None, error=error))
        return responses

    def close(self):
        """Close the sandbox session."""
        self.sandbox.kill()
