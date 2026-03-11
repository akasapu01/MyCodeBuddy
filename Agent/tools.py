import pathlib
import subprocess
from typing import Tuple, Optional, Callable
import threading

from langchain_core.tools import tool

# Global event emitter for file operations
_event_emitter: Optional[Callable[[str, dict], None]] = None
_session_id: Optional[str] = None

def set_event_emitter(emitter: Callable[[str, dict], None], session_id: str):
    """Set the event emitter function and session ID for this thread."""
    global _event_emitter, _session_id
    _event_emitter = emitter
    _session_id = session_id

def emit_event(event_type: str, data: dict):
    """Emit an event if emitter is set."""
    if _event_emitter and _session_id:
        _event_emitter(_session_id, {"type": event_type, **data})

def get_project_root(session_id: str) -> pathlib.Path:
    """Get the project root for a specific session."""
    return pathlib.Path.cwd() / "generated_project" / session_id

def safe_path_for_project(path: str, session_id: str) -> pathlib.Path:
    project_root = get_project_root(session_id)
    p = (project_root / path).resolve()
    if project_root.resolve() not in p.parents and project_root.resolve() != p.parent and project_root.resolve() != p:
        raise ValueError("Attempt to write outside project root")
    return p


@tool
def write_file(path: str, content: str) -> str:
    """Writes content to a file at the specified path within the project root."""
    if not _session_id:
        raise ValueError("Session ID not set. Call set_event_emitter first.")
    
    p = safe_path_for_project(path, _session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    
    # Emit file write event
    emit_event("file", {"path": path, "action": "write", "size": len(content)})
    
    return f"WROTE:{p}"


@tool
def read_file(path: str) -> str:
    """Reads content from a file at the specified path within the project root."""
    if not _session_id:
        raise ValueError("Session ID not set. Call set_event_emitter first.")
    
    p = safe_path_for_project(path, _session_id)
    if not p.exists():
        return ""
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@tool
def get_current_directory() -> str:
    """Returns the current working directory."""
    if not _session_id:
        raise ValueError("Session ID not set. Call set_event_emitter first.")
    
    return str(get_project_root(_session_id))


@tool
def list_files(directory: str = ".") -> str:
    """Lists all files in the specified directory within the project root."""
    if not _session_id:
        raise ValueError("Session ID not set. Call set_event_emitter first.")
    
    p = safe_path_for_project(directory, _session_id)
    if not p.is_dir():
        return f"ERROR: {p} is not a directory"
    files = [str(f.relative_to(get_project_root(_session_id))) for f in p.glob("**/*") if f.is_file()]
    return "\n".join(files) if files else "No files found."

@tool
def run_cmd(cmd: str, cwd: str = None, timeout: int = 30) -> Tuple[int, str, str]:
    """Runs a shell command in the specified directory and returns the result."""
    if not _session_id:
        raise ValueError("Session ID not set. Call set_event_emitter first.")
    
    cwd_dir = safe_path_for_project(cwd, _session_id) if cwd else get_project_root(_session_id)
    res = subprocess.run(cmd, shell=True, cwd=str(cwd_dir), capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout, res.stderr


def init_project_root(session_id: str):
    """Initialize project root for a specific session."""
    project_root = get_project_root(session_id)
    project_root.mkdir(parents=True, exist_ok=True)
    return str(project_root)