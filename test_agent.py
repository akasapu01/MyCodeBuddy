#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Set up environment
from dotenv import load_dotenv
load_dotenv()

# Import and test the agent
try:
    from Agent.graph import agent
    print("✓ Agent imported successfully")
    
    # Test with a simple prompt
    result = agent.invoke(
        {"user_prompt": "Create a simple hello world Python script"},
        {"recursion_limit": 10}
    )
    
    print("✓ Agent executed successfully")
    print(f"Result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
    
    # Check if files were created
    import pathlib
    generated_dir = pathlib.Path("generated_project")
    if generated_dir.exists():
        files = list(generated_dir.rglob("*"))
        print(f"✓ Generated {len(files)} files in generated_project/")
        for file in files[:5]:  # Show first 5 files
            print(f"  - {file}")
    else:
        print("⚠ No generated_project directory found")
        
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
