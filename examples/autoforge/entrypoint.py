#!/usr/bin/env python3
"""
AutoForge Skill Entrypoint — Standard I/O Contract

Input:  input/request.json
Output: output/result.json

Commands:
  - init: Initialize a new project
  - plan: Generate a spec from requirements (uses sessions_spawn)
  - build: Execute the build (uses sessions_spawn for each task)
  - status: Check project status
  - help: Show available commands

This wrapper enables OpenClaw to invoke AutoForge uniformly.
LLM calls are delegated to OpenClaw sub-agents via sessions_spawn.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
VENDOR_DIR = SKILL_DIR / "vendor"
INPUT_DIR = SKILL_DIR / "input"
OUTPUT_DIR = SKILL_DIR / "output"
PROJECTS_DIR = SKILL_DIR / "projects"

# Add vendor to Python path so we can import AutoForge modules
sys.path.insert(0, str(VENDOR_DIR))


def load_request() -> dict:
    """Load the input request."""
    request_file = INPUT_DIR / "request.json"
    if not request_file.exists():
        return {"command": "help", "args": {}}
    return json.loads(request_file.read_text())


def save_result(result: dict):
    """Save the output result."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result_file = OUTPUT_DIR / "result.json"
    result_file.write_text(json.dumps(result, indent=2))
    print(f"Result written to: {result_file}")


def sessions_spawn(task: str, label: str, timeout: int = 300) -> dict:
    """
    Request an OpenClaw sub-agent to handle LLM work.
    
    Skills cannot directly spawn sub-agents - they must return a "pending"
    status with the required action, and the orchestrating agent (OpenClaw)
    will execute the sessions_spawn call.
    
    Returns:
        dict with status="pending" and the action for the orchestrator
    """
    # Skills run in sandbox without direct access to sessions_spawn.
    # Return the action for the orchestrating agent to execute.
    return {
        "status": "pending",
        "note": "Sub-agent required - orchestrator should execute sessions_spawn",
        "action": {
            "tool": "sessions_spawn",
            "params": {
                "task": task,
                "label": label,
                "runTimeoutSeconds": timeout
            }
        }
    }


def cmd_help(args: dict) -> dict:
    """Show available commands."""
    return {
        "status": "ok",
        "summary": "AutoForge Skill - Available Commands",
        "commands": {
            "init": {
                "description": "Initialize a new project",
                "args": {
                    "name": "Project name (required)",
                    "path": "Project directory (optional)"
                }
            },
            "plan": {
                "description": "Generate a detailed spec from requirements",
                "args": {
                    "project": "Project name (required)",
                    "requirements": "Natural language requirements (required)"
                },
                "note": "Uses sessions_spawn for LLM planning"
            },
            "build": {
                "description": "Execute the build with sub-agents",
                "args": {
                    "project": "Project name (required)",
                    "feature": "Specific feature to build (optional)"
                },
                "note": "Spawns sub-agents for each task"
            },
            "status": {
                "description": "Check project status",
                "args": {
                    "project": "Project name (optional, lists all if omitted)"
                }
            }
        },
        "artifacts": []
    }


def cmd_init(args: dict) -> dict:
    """Initialize a new project."""
    name = args.get("name")
    if not name:
        return {"status": "error", "summary": "Project name is required", "artifacts": []}
    
    project_path = args.get("path") or str(PROJECTS_DIR / name)
    project_dir = Path(project_path)
    
    # Create project structure
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "prompts").mkdir(exist_ok=True)
    (project_dir / ".autoforge").mkdir(exist_ok=True)
    (project_dir / "src").mkdir(exist_ok=True)
    
    # Create spec template
    spec_file = project_dir / "prompts" / "app_spec.txt"
    if not spec_file.exists():
        spec_file.write_text(f"""<project_specification>
# Project: {name}

## Overview
[Describe what this project does]

## Features
- [ ] Feature 1
- [ ] Feature 2

## Technical Requirements
[List technical requirements]

</project_specification>
""")
    
    # Create tasks file
    tasks_file = project_dir / ".autoforge" / "tasks.json"
    if not tasks_file.exists():
        tasks_file.write_text(json.dumps({"tasks": [], "completed": []}, indent=2))
    
    return {
        "status": "ok",
        "summary": f"Initialized project '{name}'",
        "project_path": str(project_dir),
        "artifacts": [
            {"type": "directory", "path": str(project_dir)},
            {"type": "file", "path": str(spec_file)},
            {"type": "file", "path": str(tasks_file)}
        ],
        "next_steps": [
            "Run 'plan' with your requirements to generate a detailed spec",
            "Run 'build' to start building with sub-agents"
        ]
    }


def cmd_plan(args: dict) -> dict:
    """Generate a detailed spec from requirements using sessions_spawn."""
    project = args.get("project")
    requirements = args.get("requirements")
    
    if not project:
        return {"status": "error", "summary": "Project name is required", "artifacts": []}
    if not requirements:
        return {"status": "error", "summary": "Requirements are required", "artifacts": []}
    
    project_dir = PROJECTS_DIR / project
    if not project_dir.exists():
        return {"status": "error", "summary": f"Project '{project}' not found. Run 'init' first.", "artifacts": []}
    
    spec_file = project_dir / "prompts" / "app_spec.txt"
    tasks_file = project_dir / ".autoforge" / "tasks.json"
    
    # Build the planning prompt
    planning_prompt = f"""You are a technical architect. Create a detailed project specification and task breakdown.

PROJECT: {project}

REQUIREMENTS:
{requirements}

Please provide:

1. **Project Specification** (in <project_specification> tags):
   - Clear project overview
   - Detailed feature list with acceptance criteria
   - Technical stack recommendations
   - Architecture decisions

2. **Task Breakdown** (as JSON):
   Return a JSON object with this structure:
   {{
     "tasks": [
       {{
         "id": "task-1",
         "name": "Setup project structure",
         "description": "Initialize the project with required dependencies",
         "dependencies": [],
         "estimated_complexity": "low|medium|high"
       }}
     ]
   }}

Be specific and actionable. Each task should be completable by a focused coding agent.
"""

    # Spawn a sub-agent to do the planning
    spawn_result = sessions_spawn(
        task=planning_prompt,
        label=f"autoforge-plan-{project}",
        timeout=300
    )
    
    if spawn_result.get("status") == "pending":
        # OpenClaw CLI not available - return the manual action
        return {
            "status": "pending",
            "summary": "Planning requires OpenClaw sub-agent",
            "action_required": spawn_result["action"],
            "artifacts": []
        }
    
    if spawn_result.get("status") == "error":
        return {
            "status": "error", 
            "summary": f"Planning failed: {spawn_result.get('error')}",
            "artifacts": []
        }
    
    # Parse the response
    output = spawn_result.get("output", "")
    
    # Extract spec (between <project_specification> tags)
    import re
    spec_match = re.search(r'<project_specification>(.*?)</project_specification>', output, re.DOTALL)
    if spec_match:
        spec_content = f"<project_specification>{spec_match.group(1)}</project_specification>"
        spec_file.write_text(spec_content)
    
    # Extract tasks JSON
    tasks_match = re.search(r'\{[\s\S]*"tasks"[\s\S]*\}', output)
    if tasks_match:
        try:
            tasks_data = json.loads(tasks_match.group())
            tasks_file.write_text(json.dumps(tasks_data, indent=2))
        except json.JSONDecodeError:
            pass
    
    return {
        "status": "ok",
        "summary": f"Generated plan for '{project}'",
        "artifacts": [
            {"type": "file", "path": str(spec_file)},
            {"type": "file", "path": str(tasks_file)}
        ],
        "sub_agent_result": spawn_result
    }


def cmd_build(args: dict) -> dict:
    """Execute the build using sessions_spawn for each task."""
    project = args.get("project")
    feature = args.get("feature")
    
    if not project:
        return {"status": "error", "summary": "Project name is required", "artifacts": []}
    
    project_dir = PROJECTS_DIR / project
    if not project_dir.exists():
        return {"status": "error", "summary": f"Project '{project}' not found", "artifacts": []}
    
    tasks_file = project_dir / ".autoforge" / "tasks.json"
    spec_file = project_dir / "prompts" / "app_spec.txt"
    
    if not tasks_file.exists():
        return {"status": "error", "summary": "No tasks found. Run 'plan' first.", "artifacts": []}
    
    # Load tasks
    tasks_data = json.loads(tasks_file.read_text())
    tasks = tasks_data.get("tasks", [])
    completed = tasks_data.get("completed", [])
    
    if not tasks:
        return {"status": "error", "summary": "No tasks defined. Run 'plan' first.", "artifacts": []}
    
    # Load spec for context
    spec_content = spec_file.read_text() if spec_file.exists() else ""
    
    # Filter tasks if feature specified
    if feature:
        tasks = [t for t in tasks if feature.lower() in t.get("name", "").lower() 
                 or feature.lower() in t.get("description", "").lower()]
    
    # Find next incomplete task
    pending_tasks = [t for t in tasks if t.get("id") not in completed]
    
    if not pending_tasks:
        return {
            "status": "ok",
            "summary": f"All tasks completed for '{project}'!",
            "completed": len(completed),
            "total": len(tasks),
            "artifacts": []
        }
    
    # Build the next task
    task = pending_tasks[0]
    
    build_prompt = f"""You are a coding agent. Implement the following task.

PROJECT: {project}
WORKING DIRECTORY: {project_dir}

SPECIFICATION:
{spec_content[:2000]}

CURRENT TASK:
ID: {task.get('id')}
Name: {task.get('name')}
Description: {task.get('description')}

Dependencies: {task.get('dependencies', [])}

Please:
1. Implement this task completely
2. Create/modify the necessary files
3. Write tests if applicable
4. Provide a summary of changes made

Be thorough and production-ready.
"""

    # Spawn a sub-agent to do the work
    spawn_result = sessions_spawn(
        task=build_prompt,
        label=f"autoforge-build-{project}-{task.get('id')}",
        timeout=600
    )
    
    if spawn_result.get("status") == "pending":
        return {
            "status": "pending",
            "summary": f"Build task '{task.get('name')}' requires OpenClaw sub-agent",
            "task": task,
            "action_required": spawn_result["action"],
            "artifacts": []
        }
    
    if spawn_result.get("status") == "error":
        return {
            "status": "error",
            "summary": f"Build failed: {spawn_result.get('error')}",
            "task": task,
            "artifacts": []
        }
    
    # Mark task as completed
    completed.append(task.get("id"))
    tasks_data["completed"] = completed
    tasks_file.write_text(json.dumps(tasks_data, indent=2))
    
    return {
        "status": "ok",
        "summary": f"Completed task: {task.get('name')}",
        "task": task,
        "progress": {
            "completed": len(completed),
            "total": len(tasks),
            "remaining": len(pending_tasks) - 1
        },
        "artifacts": [],
        "sub_agent_result": spawn_result,
        "next": pending_tasks[1] if len(pending_tasks) > 1 else None
    }


def cmd_status(args: dict) -> dict:
    """Check project status."""
    project = args.get("project")
    
    if not project:
        # List all projects
        if not PROJECTS_DIR.exists():
            return {"status": "ok", "summary": "No projects found", "projects": [], "artifacts": []}
        
        projects = []
        for p in PROJECTS_DIR.iterdir():
            if p.is_dir() and not p.name.startswith('.'):
                tasks_file = p / ".autoforge" / "tasks.json"
                tasks_data = {}
                if tasks_file.exists():
                    try:
                        tasks_data = json.loads(tasks_file.read_text())
                    except:
                        pass
                
                projects.append({
                    "name": p.name,
                    "path": str(p),
                    "has_spec": (p / "prompts" / "app_spec.txt").exists(),
                    "tasks": len(tasks_data.get("tasks", [])),
                    "completed": len(tasks_data.get("completed", []))
                })
        
        return {
            "status": "ok",
            "summary": f"Found {len(projects)} project(s)",
            "projects": projects,
            "artifacts": []
        }
    
    # Status for specific project
    project_dir = PROJECTS_DIR / project
    if not project_dir.exists():
        return {"status": "error", "summary": f"Project '{project}' not found", "artifacts": []}
    
    spec_file = project_dir / "prompts" / "app_spec.txt"
    tasks_file = project_dir / ".autoforge" / "tasks.json"
    
    tasks_data = {}
    if tasks_file.exists():
        try:
            tasks_data = json.loads(tasks_file.read_text())
        except:
            pass
    
    tasks = tasks_data.get("tasks", [])
    completed = tasks_data.get("completed", [])
    
    return {
        "status": "ok",
        "summary": f"Project '{project}' status",
        "project": {
            "name": project,
            "path": str(project_dir),
            "has_spec": spec_file.exists(),
            "tasks": {
                "total": len(tasks),
                "completed": len(completed),
                "pending": len([t for t in tasks if t.get("id") not in completed])
            }
        },
        "pending_tasks": [t for t in tasks if t.get("id") not in completed][:5],
        "artifacts": []
    }


COMMANDS = {
    "help": cmd_help,
    "init": cmd_init,
    "plan": cmd_plan,
    "build": cmd_build,
    "status": cmd_status,
}


def main():
    request = load_request()
    command = request.get("command", "help")
    args = request.get("args", {})
    
    print(f"Skill: autoforge")
    print(f"Command: {command}")
    print(f"Args: {json.dumps(args)}")
    
    if command in COMMANDS:
        result = COMMANDS[command](args)
    else:
        result = {
            "status": "error",
            "summary": f"Unknown command: {command}",
            "available_commands": list(COMMANDS.keys()),
            "artifacts": []
        }
    
    result.setdefault("command", command)
    result.setdefault("artifacts", [])
    
    save_result(result)
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
