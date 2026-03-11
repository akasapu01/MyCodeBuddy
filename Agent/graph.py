from dotenv import load_dotenv

load_dotenv()
from langchain_groq import ChatGroq
from langchain.globals import set_debug, set_verbose
from langgraph.prebuilt import create_react_agent

from .prompts import *
from .states import *
from .tools import *
from .tools import set_event_emitter, init_project_root, emit_event

from langgraph.constants import END
from langgraph.graph import StateGraph
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import SystemMessage, HumanMessage

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)

# For generations that must NEVER call tools:
LLM_NO_TOOLS = llm.bind(tools=[], tool_choice="none")

CODER = llm.bind_tools(
    [read_file, write_file, list_files, get_current_directory],
    tool_choice="auto",
)
set_debug(True)
set_verbose(True)


def run_structured(schema_cls, prompt: str):
    parser = PydanticOutputParser(pydantic_object=schema_cls)
    fmt = parser.get_format_instructions()
    sys = "Return ONLY JSON matching the schema. No prose."
    raw = LLM_NO_TOOLS.invoke([
        SystemMessage(content=sys),
        HumanMessage(content=f"{prompt}\n\n{fmt}")
    ])
    text = raw.content if hasattr(raw, "content") else str(raw)
    return parser.parse(text)


def planner_agent(state: dict) -> dict:
    user_prompt = state["user_prompt"].strip()
    print(f"Planner received: {user_prompt}")
    
    # Emit node start event
    emit_event("node", {"value": "planner", "action": "start"})

    try:
        plan_obj = run_structured(Plan, planner_prompt(user_prompt))
        result = {"plan": plan_obj.model_dump()}
        print(f"Planner created plan: {plan_obj.name} with {len(plan_obj.files)} files")
        
        # Emit node end event
        emit_event("node", {"value": "planner", "action": "end", "success": True})
        
        return result
    except Exception as e:
        print(f"Planner error: {e}")
        
        # Emit node end event with error
        emit_event("node", {"value": "planner", "action": "end", "success": False, "error": str(e)})
        
        return {
            "plan": {"name": "Error", "description": "Failed to create plan", "tech_stack": "unknown", "features": [],
                     "files": []}}


def architect_agent(state: dict) -> dict:
    print(f"Architect received state keys: {list(state.keys())}")
    
    # Emit node start event
    emit_event("node", {"value": "architect", "action": "start"})

    if "plan" not in state:
        emit_event("node", {"value": "architect", "action": "end", "success": False, "error": "No plan found"})
        return {"task_plan": {"implementation_steps": []}}

    plan = Plan(**state["plan"]) if isinstance(state["plan"], dict) else state["plan"]
    print(f"Architect processing plan: {plan.name}")

    try:
        task_plan_obj = run_structured(TaskPlan, architect_prompt(plan))
        out = task_plan_obj.model_dump()
        out["plan"] = plan.model_dump() if hasattr(plan, "model_dump") else plan
        print(f"Architect created task_plan with {len(task_plan_obj.implementation_steps)} steps")
        
        # Emit node end event
        emit_event("node", {"value": "architect", "action": "end", "success": True, "steps": len(task_plan_obj.implementation_steps)})
        
        return {"task_plan": out}
    except Exception as e:
        print(f"Architect error: {e}")
        
        # Emit node end event with error
        emit_event("node", {"value": "architect", "action": "end", "success": False, "error": str(e)})
        
        return {"task_plan": {"implementation_steps": [],
                              "plan": plan.model_dump() if hasattr(plan, "model_dump") else plan}}


def coder_agent(state: dict) -> dict:
    """LangGraph tool-using coder agent that processes one step at a time."""
    print(f"\n=== CODER AGENT ENTRY ===")
    print(f"Coder agent received state keys: {list(state.keys())}")

    # Debug: Print the full state
    if "coder_state" in state:
        print(f"Existing coder_state: {state['coder_state']}")

    # Check if task_plan exists in state, state checking logic to handle the case where the task_plan is in the coder_state
    task_plan_data = None
    if "task_plan" in state:
        task_plan_data = state["task_plan"]
    elif"coder_state" in state and "task_plan" in state["coder_state"]:
        task_plan_data = state["coder_state"]["task_plan"]
    else:
        print("ERROR: No task_plan found in state")
        emit_event("error", {"message": "No task_plan found in state"})
        return {"coder_state": {"current_step_idx": 999, "task_plan": {"implementation_steps": []}}}

    # coder_state reconstruction properly
    coder_state_data = state.get("coder_state")
    if coder_state_data is None:
        print("No existing coder_state, creating new one")
        task_plan = TaskPlan(**task_plan_data) if isinstance(task_plan_data, dict) else task_plan_data
        coder_state = CoderState(task_plan=task_plan, current_step_idx=0)
        print(f"Initialized new coder_state with {len(task_plan.implementation_steps)} steps")
        
        # Emit coder start event
        emit_event("node", {"value": "coder", "action": "start", "total_steps": len(task_plan.implementation_steps)})
    else:
        print(f"Reconstructing coder_state from: {coder_state_data}")
        # The issue was here - we need to properly reconstruct the nested TaskPlan
        if isinstance(coder_state_data, dict):
            # Extract task_plan data and reconstruct it properly
            task_plan_data = coder_state_data.get("task_plan", {})
            if isinstance(task_plan_data, dict):
                task_plan = TaskPlan(**task_plan_data)
            else:
                task_plan = task_plan_data

            coder_state = CoderState(
                task_plan=task_plan,
                current_step_idx=coder_state_data.get("current_step_idx", 0),
                current_file_content=coder_state_data.get("current_file_content")
            )
        else:
            coder_state = coder_state_data

    print(f"Current coder_state: step {coder_state.current_step_idx}")

    steps = coder_state.task_plan.implementation_steps
    print(f"Total implementation steps: {len(steps)}")

    # Check if we're done with all steps
    if coder_state.current_step_idx >= len(steps):
        print("All implementation steps completed!")
        emit_event("node", {"value": "coder", "action": "end", "success": True, "completed_steps": len(steps)})
        emit_event("done", {"message": "All steps completed successfully"})
        return {"coder_state": coder_state.model_dump()}

    # Get current task
    current_task = steps[coder_state.current_step_idx]
    print(f"Processing step {coder_state.current_step_idx + 1}/{len(steps)}: {current_task.task_description}")
    print(f"Target file: {current_task.filepath}")
    
    # Emit step start event
    emit_event("step", {
        "step_index": coder_state.current_step_idx,
        "total_steps": len(steps),
        "filepath": current_task.filepath,
        "description": current_task.task_description
    })

    # TEST: Try writing a simple test file to verify write_file works
    try:
        test_result = write_file("test.txt", "Hello World Test")
        print(f"Test write result: {test_result}")
        test_verify = read_file("test.txt")
        print(f"Test file verification: {len(test_verify)} chars")
    except Exception as test_e:
        print(f"Test file write failed: {test_e}")

    # Read existing file content
    try:
        existing_content = read_file(current_task.filepath)
        print(f"Found existing content in {current_task.filepath}: {len(existing_content)} characters")
    except Exception as e:
        print(f"No existing file {current_task.filepath}: {e}")
        existing_content = ""

    # Prepare prompts
    system_prompt = coder_system_prompt()
    user_prompt = (
        f"Task: {current_task.task_description}\n"
        f"File: {current_task.filepath}\n"
        f"Existing content:\n{existing_content}\n"
        "Use write_file(path, content) to save your changes."
    )

    success = False
    try:
        # Create and invoke react agent
        coder_tools = [read_file, write_file, list_files, get_current_directory]
        react_agent = create_react_agent(llm, coder_tools)

        print(f"Invoking React agent with tools: {[tool.name for tool in coder_tools]}")
        result = react_agent.invoke({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        })

        print(f"React agent result type: {type(result)}")
        print(f"React agent result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")

        # Check if any files were actually written by listing the directory
        try:
            files_after = list_files(".")
            print(f"Files after React agent: {files_after}")
        except:
            print("Could not list files after React agent")

        print(f"React agent completed task for {current_task.filepath}")
        success = True

    except Exception as e:
        print(f"React agent failed for step {coder_state.current_step_idx}: {e}")
        print(f"Exception type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        success = False

    # If react agent failed OR if no file was actually written, try fallback
    try:
        # Check if the file exists after the react agent
        file_exists_after_react = False
        try:
            test_content = read_file(current_task.filepath)
            file_exists_after_react = len(test_content.strip()) > 0
            print(f"File {current_task.filepath} exists after React: {file_exists_after_react}")
        except:
            file_exists_after_react = False
            print(f"File {current_task.filepath} does not exist after React agent")

        if not success or not file_exists_after_react:
            print("React agent didn't create the file, trying fallback...")
            fallback_sys = (
                "You are the CODER. Generate the complete file content for the implementation. "
                "Provide only the code, no explanations or markdown formatting."
            )
            fallback_resp = LLM_NO_TOOLS.invoke([
                SystemMessage(content=fallback_sys),
                HumanMessage(content=user_prompt)
            ])

            print(f"Fallback response length: {len(fallback_resp.content) if fallback_resp.content else 0}")
            print(
                f"Fallback response preview: {fallback_resp.content[:200] if fallback_resp.content else 'No content'}")

            if fallback_resp.content:
                # Clean up the response content (remove markdown if present)
                content = fallback_resp.content.strip()
                if content.startswith('```'):
                    lines = content.split('\n')
                    if lines[0].startswith('```'):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == '```':
                        lines = lines[:-1]
                    content = '\n'.join(lines)

                print(f"Writing fallback content to {current_task.filepath} ({len(content)} chars)")
                write_result = write_file(current_task.filepath, content)
                print(f"Fallback write result: {write_result}")

                # Verify the file was actually written
                try:
                    verify_content = read_file(current_task.filepath)
                    print(f"Verification: File {current_task.filepath} now contains {len(verify_content)} characters")
                except Exception as verify_e:
                    print(f"Could not verify file was written: {verify_e}")
            else:
                print("No content generated in fallback")

    except Exception as fallback_e:
        print(f"Fallback also failed: {fallback_e}")
        import traceback
        print(f"Fallback traceback: {traceback.format_exc()}")

    # Increment step index
    coder_state.current_step_idx += 1
    print(f"Incremented step index to: {coder_state.current_step_idx}")
    print(f"Total steps: {len(steps)}")
    
    # Emit step completion event
    emit_event("step_complete", {
        "step_index": coder_state.current_step_idx - 1,
        "total_steps": len(steps),
        "filepath": current_task.filepath,
        "success": True
    })

    # Return the updated coder_state
    result = {"coder_state": coder_state.model_dump()}
    print(f"Returning coder state: current_step_idx = {coder_state.current_step_idx}")
    return result


def should_continue(state: dict):
    """Determine if we should continue coding or end by checking step progress."""
    coder_state = state.get("coder_state")

    print(f"\n=== CONDITIONAL CHECK ===")
    print(f"State keys: {list(state.keys())}")

    if coder_state and isinstance(coder_state, dict):
        current_idx = coder_state.get("current_step_idx", 0)
        task_plan = coder_state.get("task_plan", {})
        implementation_steps = task_plan.get("implementation_steps", [])
        total_steps = len(implementation_steps)

        print(f"Current step index: {current_idx}")
        print(f"Total steps: {total_steps}")
        print(f"Steps completed: {current_idx}/{total_steps}")

        if current_idx >= total_steps:
            print("-> All steps completed, going to END")
            return "END"
        else:
            print(f"-> Still have steps remaining, continuing to coder")
            return "coder"
    else:
        print(f"-> No valid coder_state found, going to END")
        print(f"coder_state type: {type(coder_state)}")
        print(f"coder_state value: {coder_state}")
        return "END"


graph = StateGraph(dict)
graph.add_node("planner", planner_agent)
graph.add_node("architect", architect_agent)
graph.add_node("coder", coder_agent)

graph.add_edge(start_key="planner", end_key="architect")
graph.add_edge(start_key="architect", end_key="coder")
graph.add_conditional_edges(
    "coder",
    should_continue,
    {"END": END, "coder": "coder"}
)
graph.set_entry_point("planner")

agent = graph.compile()

def create_session_agent(session_id: str, event_emitter=None):
    """Create an agent instance for a specific session with event emission."""
    # Set up event emitter and session context
    if event_emitter:
        set_event_emitter(event_emitter, session_id)
    
    # Initialize project root for this session
    project_path = init_project_root(session_id)
    print(f"Project root initialized for session {session_id} at: {project_path}")
    
    # Return the compiled agent (same graph, but tools will use session context)
    return agent

if __name__ == "__main__":
    # Test the session-aware agent
    import uuid
    session_id = str(uuid.uuid4())
    
    # Create a simple event emitter for testing
    def test_emitter(session_id, event):
        print(f"[{session_id}] Event: {event}")
    
    # Create session agent
    session_agent = create_session_agent(session_id, test_emitter)
    
    user_prompt = "Create a simple To-do list Web Application"
    result = session_agent.invoke({"user_prompt": user_prompt},
                                  {"recursion_limit": 100})
    print("Final result:")
    print(result)