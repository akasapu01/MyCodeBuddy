from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid
import asyncio
from typing import Dict, Any, Optional, List
import threading
from datetime import datetime
import json
import os
import pathlib
import zipfile
import io

load_dotenv()

app = FastAPI(title="Code Builder API", version="0.1.0")

# Add CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage (in production, use Redis or database)
sessions: Dict[str, Dict[str, Any]] = {}

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def send_to_session(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except:
                    disconnected.append(connection)
            
            # Remove disconnected connections
            for conn in disconnected:
                self.active_connections[session_id].remove(conn)

manager = ConnectionManager()

class RunRequest(BaseModel):
    prompt: str
    model: Optional[str] = "llama-3.3-70b-versatile"
    temperature: Optional[float] = 0.0

class RunResponse(BaseModel):
    session_id: str
    status: str
    message: str

def run_agent_background(session_id: str, prompt: str, model: str, temperature: float):
    """Run the agent in a background thread."""
    try:
        # Import here to avoid circular imports
        import sys
        import os
        # Add project root to Python path
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        from Agent.graph import create_session_agent
        
        # Create event emitter that updates session status and sends WebSocket messages
        def session_emitter(sid: str, event: dict):
            if sid in sessions:
                # Add timestamp to event
                event_with_timestamp = {
                    "timestamp": datetime.now().isoformat(),
                    **event
                }
                
                # Store event in session
                sessions[sid]["events"].append(event_with_timestamp)
                
                # Update session status based on event type
                if event["type"] == "node":
                    sessions[sid]["current_node"] = event["value"]
                elif event["type"] == "file":
                    if event["path"] not in sessions[sid]["files"]:
                        sessions[sid]["files"].append(event["path"])
                elif event["type"] == "done":
                    sessions[sid]["status"] = "completed"
                elif event["type"] == "error":
                    sessions[sid]["status"] = "error"
                    sessions[sid]["error"] = event.get("message", "Unknown error")
                
                # Send WebSocket message (run in async context)
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(manager.send_to_session(sid, event_with_timestamp))
                    loop.close()
                except Exception as ws_error:
                    print(f"WebSocket error: {ws_error}")
        
        # Create session-aware agent
        agent = create_session_agent(session_id, session_emitter)
        
        # Update session status
        sessions[session_id]["status"] = "running"
        sessions[session_id]["started_at"] = datetime.now().isoformat()
        
        # Send initial status via WebSocket
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(manager.send_to_session(session_id, {
                "type": "status",
                "status": "running",
                "timestamp": datetime.now().isoformat()
            }))
            loop.close()
        except Exception as ws_error:
            print(f"WebSocket error: {ws_error}")
        
        # Run the agent
        result = agent.invoke(
            {"user_prompt": prompt},
            {"recursion_limit": 100}
        )
        
        # Store final result
        sessions[session_id]["result"] = result
        sessions[session_id]["completed_at"] = datetime.now().isoformat()
        
        if sessions[session_id]["status"] != "error":
            sessions[session_id]["status"] = "completed"
            
        # Send completion message via WebSocket
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(manager.send_to_session(session_id, {
                "type": "status",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "result": result
            }))
            loop.close()
        except Exception as ws_error:
            print(f"WebSocket error: {ws_error}")
            
    except Exception as e:
        # Handle any errors
        if session_id in sessions:
            sessions[session_id]["status"] = "error"
            sessions[session_id]["error"] = str(e)
            sessions[session_id]["completed_at"] = datetime.now().isoformat()
            
            # Send error message via WebSocket
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(manager.send_to_session(session_id, {
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                }))
                loop.close()
            except Exception as ws_error:
                print(f"WebSocket error: {ws_error}")

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

@app.post("/api/run", response_model=RunResponse)
async def run_project(request: RunRequest, background_tasks: BackgroundTasks):
    """Start a new project generation session."""
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    
    # Initialize session
    sessions[session_id] = {
        "session_id": session_id,
        "prompt": request.prompt,
        "model": request.model,
        "temperature": request.temperature,
        "status": "starting",
        "created_at": datetime.now().isoformat(),
        "current_node": None,
        "files": [],
        "events": [],
        "result": None,
        "error": None
    }
    
    # Start background task
    background_tasks.add_task(
        run_agent_background,
        session_id,
        request.prompt,
        request.model,
        request.temperature
    )
    
    return RunResponse(
        session_id=session_id,
        status="starting",
        message="Project generation started"
    )

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session status and details."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return sessions[session_id]

@app.websocket("/ws/progress/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time progress updates."""
    await manager.connect(websocket, session_id)
    
    try:
        # Send initial session data if available
        if session_id in sessions:
            await websocket.send_text(json.dumps({
                "type": "session_data",
                "data": sessions[session_id],
                "timestamp": datetime.now().isoformat()
            }))
        
        # Keep connection alive and handle any incoming messages
        while True:
            try:
                # Wait for messages from client (ping/pong, etc.)
                data = await websocket.receive_text()
                # Echo back or handle client messages if needed
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "message": data,
                    "timestamp": datetime.now().isoformat()
                }))
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"WebSocket error: {e}")
                break
                
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as e:
        print(f"WebSocket connection error: {e}")
        manager.disconnect(websocket, session_id)

def get_session_project_path(session_id: str) -> pathlib.Path:
    """Get the project path for a specific session."""
    return pathlib.Path.cwd() / "generated_project" / session_id

@app.get("/api/files")
async def list_files(session_id: str):
    """List all files in the session's project directory."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    project_path = get_session_project_path(session_id)
    
    if not project_path.exists():
        return {"files": [], "message": "Project directory not found"}
    
    files = []
    try:
        for file_path in project_path.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(project_path)
                file_size = file_path.stat().st_size
                files.append({
                    "name": str(relative_path),
                    "path": str(relative_path),
                    "size": file_size,
                    "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")
    
    return {"files": files, "session_id": session_id}

@app.get("/api/file")
async def get_file_content(session_id: str, path: str):
    """Get the content of a specific file."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    project_path = get_session_project_path(session_id)
    file_path = project_path / path
    
    # Security check: ensure file is within project directory
    try:
        file_path = file_path.resolve()
        project_path = project_path.resolve()
        if not str(file_path).startswith(str(project_path)):
            raise HTTPException(status_code=403, detail="Access denied: file outside project directory")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {str(e)}")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "path": path,
            "content": content,
            "size": len(content),
            "session_id": session_id
        }
    except UnicodeDecodeError:
        # Try reading as binary for non-text files
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            return {
                "path": path,
                "content": content.decode('utf-8', errors='replace'),
                "size": len(content),
                "session_id": session_id,
                "binary": True
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@app.post("/api/file")
async def update_file_content(session_id: str, path: str, content: str):
    """Update the content of a specific file."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    project_path = get_session_project_path(session_id)
    file_path = project_path / path
    
    # Security check: ensure file is within project directory
    try:
        file_path = file_path.resolve()
        project_path = project_path.resolve()
        if not str(file_path).startswith(str(project_path)):
            raise HTTPException(status_code=403, detail="Access denied: file outside project directory")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {str(e)}")
    
    try:
        # Create parent directories if they don't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write content to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return {
            "path": path,
            "message": "File updated successfully",
            "size": len(content),
            "session_id": session_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")

@app.get("/api/zip")
async def download_project_zip(session_id: str):
    """Download the entire project as a ZIP file."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    project_path = get_session_project_path(session_id)
    
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")
    
    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    
    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add all files from the project directory
            for file_path in project_path.rglob("*"):
                if file_path.is_file():
                    # Get relative path for the ZIP
                    relative_path = file_path.relative_to(project_path)
                    
                    # Read file content and add to ZIP
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
                    
                    zip_file.writestr(str(relative_path), file_content)
        
        # Reset buffer position to beginning
        zip_buffer.seek(0)
        
        # Get session info for filename
        session_info = sessions[session_id]
        project_name = session_info.get("prompt", "project")[:50]  # Limit length
        # Clean filename (remove special characters)
        clean_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        if not clean_name:
            clean_name = "generated_project"
        
        filename = f"{clean_name}_{session_id[:8]}.zip"
        
        # Return ZIP file as streaming response
        return StreamingResponse(
            io.BytesIO(zip_buffer.getvalue()),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/zip"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP file: {str(e)}")
    finally:
        zip_buffer.close()


