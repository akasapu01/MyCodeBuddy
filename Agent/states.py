from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

class File(BaseModel):
    file_path:str= Field(description="Path to the file to be created")
    file_purpose:str= Field(description="Purpose of the file created, e.g 'main application logic', 'data processing module', 'data visualization module'")

class Plan(BaseModel):
    name: str=Field(description="The name of the app to be built")
    description: str=Field(description="A one-line description of the app to be built")
    tech_stack: str=Field(description="The tech stack of the app to be built, e.g 'python','javascript', 'flask', etc")
    features: list[str]=Field(description="The list of features that the app can use, e.g 'user-authentication','data visualization', etc")
    files: list[File]=Field(description="The list of files to create, each with a 'file_path' and 'file_purpose'")

class ImplementationTask(BaseModel):
    filepath: str=Field(description="path to the file to be modified")
    task_description:str=Field(description="a detailed description of task to be performed, e.g 'add user authentication', 'implement data processing logic', etc")

class TaskPlan(BaseModel):
    implementation_steps: list[ImplementationTask]=Field(description="The list of steps for implementations of task")
    model_config = ConfigDict(extra="allow")

class CoderState(BaseModel):
    task_plan: TaskPlan = Field(description="The plan for the task to be implemented")
    current_step_idx: int = Field(0, description="The index of the current step in the implementation steps")
    current_file_content: Optional[str] = Field(None, description="The content of the file currently being edited or created")

