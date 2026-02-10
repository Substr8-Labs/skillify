#!/usr/bin/env python3
"""
Repo Skill Generator — Transform any repository into an OpenClaw skill.

Usage:
    python generate.py https://github.com/org/repo
    python generate.py /path/to/local/repo
    python generate.py https://github.com/org/repo --output ./skills/my-skill

Features:
    - Clones or reads repo
    - Analyzes structure (README, package.json, pyproject.toml, etc.)
    - Detects project type and key files
    - Generates SKILL.md with proper frontmatter
    - Extracts key docs into references/
    - Outputs ready-to-use skill directory
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

# ============================================================================
# Project Type Detection
# ============================================================================

PROJECT_SIGNATURES = {
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
    "node": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "go": ["go.mod", "go.sum"],
    "ruby": ["Gemfile", "Gemfile.lock", "*.gemspec"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "dotnet": ["*.csproj", "*.sln", "*.fsproj"],
    "terraform": ["*.tf", "terraform.tfstate"],
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    "k8s": ["*.yaml", "*.yml"],  # Will check for kind: Deployment etc.
}

DOC_FILES = [
    "README.md", "README.rst", "README.txt", "README",
    "CONTRIBUTING.md", "CONTRIBUTING.rst",
    "ARCHITECTURE.md", "DESIGN.md",
    "API.md", "API.rst",
    "CHANGELOG.md", "CHANGELOG.rst", "CHANGELOG",
    "docs/README.md", "docs/index.md",
]

CONFIG_FILES = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg"],
    "node": ["package.json", "tsconfig.json"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
}


def detect_project_type(repo_path: Path) -> list[str]:
    """Detect project type(s) from file signatures."""
    types = []
    files = set(f.name for f in repo_path.rglob("*") if f.is_file())
    
    for proj_type, signatures in PROJECT_SIGNATURES.items():
        for sig in signatures:
            if "*" in sig:
                # Glob pattern
                pattern = sig.replace("*", "")
                if any(f.endswith(pattern) for f in files):
                    types.append(proj_type)
                    break
            elif sig in files:
                types.append(proj_type)
                break
    
    return list(set(types)) or ["generic"]


def get_project_metadata(repo_path: Path, project_types: list[str]) -> dict:
    """Extract metadata from project config files."""
    metadata = {
        "name": repo_path.name,
        "description": "",
        "version": "",
        "scripts": {},
        "dependencies": [],
    }
    
    # Try package.json
    pkg_json = repo_path / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            metadata["name"] = pkg.get("name", metadata["name"])
            metadata["description"] = pkg.get("description", "")
            metadata["version"] = pkg.get("version", "")
            metadata["scripts"] = pkg.get("scripts", {})
            metadata["dependencies"] = list(pkg.get("dependencies", {}).keys())
        except (json.JSONDecodeError, IOError):
            pass
    
    # Try pyproject.toml
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib
            with open(pyproject, "rb") as f:
                pyproj = tomllib.load(f)
            project = pyproj.get("project", {})
            metadata["name"] = project.get("name", metadata["name"])
            metadata["description"] = project.get("description", "")
            metadata["version"] = project.get("version", "")
            metadata["dependencies"] = project.get("dependencies", [])
        except (ImportError, IOError):
            # tomllib not available (Python < 3.11), try regex
            try:
                content = pyproject.read_text()
                name_match = re.search(r'name\s*=\s*"([^"]+)"', content)
                desc_match = re.search(r'description\s*=\s*"([^"]+)"', content)
                if name_match:
                    metadata["name"] = name_match.group(1)
                if desc_match:
                    metadata["description"] = desc_match.group(1)
            except IOError:
                pass
    
    # Try Cargo.toml
    cargo = repo_path / "Cargo.toml"
    if cargo.exists():
        try:
            content = cargo.read_text()
            name_match = re.search(r'name\s*=\s*"([^"]+)"', content)
            desc_match = re.search(r'description\s*=\s*"([^"]+)"', content)
            if name_match:
                metadata["name"] = name_match.group(1)
            if desc_match:
                metadata["description"] = desc_match.group(1)
        except IOError:
            pass
    
    return metadata


def get_readme_content(repo_path: Path) -> str:
    """Get README content."""
    for readme_name in ["README.md", "README.rst", "README.txt", "README"]:
        readme = repo_path / readme_name
        if readme.exists():
            try:
                return readme.read_text()[:10000]  # Limit size
            except IOError:
                pass
    return ""


def get_directory_tree(repo_path: Path, max_depth: int = 3, max_files: int = 50) -> str:
    """Generate a directory tree string."""
    lines = []
    file_count = 0
    
    def walk(path: Path, prefix: str = "", depth: int = 0):
        nonlocal file_count
        if depth > max_depth or file_count > max_files:
            return
        
        # Skip hidden and common ignore dirs
        ignore = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", 
                  "target", "dist", "build", ".next", ".cache", "coverage"}
        
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        
        for i, entry in enumerate(entries):
            if entry.name in ignore or entry.name.startswith("."):
                continue
            
            file_count += 1
            if file_count > max_files:
                lines.append(f"{prefix}...")
                return
            
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                walk(entry, prefix + extension, depth + 1)
    
    walk(repo_path)
    return "\n".join(lines)


def extract_key_files(repo_path: Path) -> dict[str, str]:
    """Extract content of key documentation files."""
    key_files = {}
    
    for doc_file in DOC_FILES:
        file_path = repo_path / doc_file
        if file_path.exists():
            try:
                content = file_path.read_text()
                if len(content) < 50000:  # Skip very large files
                    key_files[doc_file] = content
            except IOError:
                pass
    
    return key_files


def detect_entry_points(repo_path: Path, project_types: list[str]) -> list[str]:
    """Detect common entry points and commands."""
    entry_points = []
    
    # Check for common executables
    for name in ["main.py", "app.py", "cli.py", "index.js", "main.rs", "main.go"]:
        if (repo_path / name).exists() or (repo_path / "src" / name).exists():
            entry_points.append(name)
    
    # Check Makefile targets
    makefile = repo_path / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text()
            targets = re.findall(r"^([a-zA-Z_][a-zA-Z0-9_-]*):", content, re.MULTILINE)
            for target in targets[:10]:  # Limit
                if target not in ["all", "clean", "install", "test", "build"]:
                    entry_points.append(f"make {target}")
                else:
                    entry_points.insert(0, f"make {target}")
        except IOError:
            pass
    
    # Check package.json scripts
    pkg_json = repo_path / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            for script in pkg.get("scripts", {}).keys():
                entry_points.append(f"npm run {script}")
        except (json.JSONDecodeError, IOError):
            pass
    
    return entry_points[:15]  # Limit


# ============================================================================
# SKILL.md Generation
# ============================================================================

def generate_skill_md(
    repo_path: Path,
    project_types: list[str],
    metadata: dict,
    entry_points: list[str],
    tree: str,
    readme: str,
) -> str:
    """Generate SKILL.md content."""
    
    name = metadata["name"].replace("_", "-").lower()
    description = metadata["description"] or f"Work with the {metadata['name']} codebase."
    
    # Build trigger phrases
    triggers = [
        f"working on {name}",
        f"navigate {name}",
        f"build {name}",
        f"debug {name}",
        f"{name} codebase",
    ]
    
    # Infer what the project does from README
    purpose = ""
    if readme:
        # Try to extract first meaningful paragraph
        paragraphs = readme.split("\n\n")
        for p in paragraphs:
            p = p.strip()
            if len(p) > 50 and not p.startswith("#") and not p.startswith("```"):
                purpose = p[:500]
                break
    
    # Build the SKILL.md
    skill_md = f'''---
name: {name}
description: {description} Use when {", ".join(triggers[:3])}.
---

# {metadata["name"]}

{purpose if purpose else f"Codebase skill for {metadata['name']}."}

## Project Type

{", ".join(project_types)}

## Directory Structure

```
{tree}
```

## Quick Start

'''

    # Add entry points
    if entry_points:
        skill_md += "### Common Commands\n\n"
        for ep in entry_points[:8]:
            skill_md += f"```bash\n{ep}\n```\n\n"
    
    # Add setup instructions based on project type
    if "python" in project_types:
        skill_md += """### Python Setup

```bash
cd {{skill_dir}}
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

"""
    
    if "node" in project_types:
        skill_md += """### Node.js Setup

```bash
cd {{skill_dir}}
npm install
```

"""
    
    if "rust" in project_types:
        skill_md += """### Rust Setup

```bash
cd {{skill_dir}}
cargo build
```

"""

    # Add references section
    skill_md += """## References

See `references/` for detailed documentation:

"""
    
    for doc in DOC_FILES[:5]:
        doc_name = Path(doc).stem.upper()
        skill_md += f"- [{doc_name}](references/{Path(doc).name})\n"
    
    # Add key files section
    skill_md += """
## Key Files

| File | Purpose |
|------|---------|
"""
    
    key_patterns = [
        ("src/main.*", "Application entry point"),
        ("src/lib.*", "Library exports"),
        ("src/index.*", "Module entry"),
        ("config/*", "Configuration"),
        ("tests/*", "Test suite"),
    ]
    
    for pattern, purpose in key_patterns:
        matches = list(repo_path.glob(pattern))
        if matches:
            skill_md += f"| `{pattern}` | {purpose} |\n"
    
    return skill_md


# ============================================================================
# Main Generator
# ============================================================================

def clone_repo(url: str, target: Path) -> bool:
    """Clone a git repository."""
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(target)],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error cloning repo: {e.stderr.decode()}", file=sys.stderr)
        return False


def generate_skill(
    source: str,
    output_dir: Optional[Path] = None,
    keep_clone: bool = False,
) -> Path:
    """Generate a skill from a repository."""
    
    # Determine if source is URL or local path
    is_url = source.startswith("http://") or source.startswith("https://") or source.startswith("git@")
    
    if is_url:
        # Clone to temp directory
        temp_dir = tempfile.mkdtemp(prefix="repo-skill-gen-")
        repo_path = Path(temp_dir) / "repo"
        print(f"Cloning {source}...")
        if not clone_repo(source, repo_path):
            raise RuntimeError(f"Failed to clone {source}")
    else:
        repo_path = Path(source).resolve()
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository not found: {source}")
        temp_dir = None
    
    try:
        print(f"Analyzing {repo_path.name}...")
        
        # Detect project type
        project_types = detect_project_type(repo_path)
        print(f"  Detected types: {', '.join(project_types)}")
        
        # Get metadata
        metadata = get_project_metadata(repo_path, project_types)
        print(f"  Project name: {metadata['name']}")
        
        # Get README
        readme = get_readme_content(repo_path)
        
        # Get directory tree
        tree = get_directory_tree(repo_path)
        
        # Detect entry points
        entry_points = detect_entry_points(repo_path, project_types)
        print(f"  Found {len(entry_points)} entry points")
        
        # Extract key files
        key_files = extract_key_files(repo_path)
        print(f"  Found {len(key_files)} documentation files")
        
        # Determine output directory
        skill_name = metadata["name"].replace("_", "-").lower()
        if output_dir:
            skill_path = Path(output_dir)
        else:
            skill_path = Path.cwd() / "skills" / skill_name
        
        skill_path.mkdir(parents=True, exist_ok=True)
        
        # Generate SKILL.md
        print(f"Generating skill at {skill_path}...")
        skill_md = generate_skill_md(
            repo_path, project_types, metadata, entry_points, tree, readme
        )
        (skill_path / "SKILL.md").write_text(skill_md)
        
        # Create references directory
        refs_path = skill_path / "references"
        refs_path.mkdir(exist_ok=True)
        
        for doc_file, content in key_files.items():
            ref_name = Path(doc_file).name
            (refs_path / ref_name).write_text(content)
        
        # Create scripts directory with placeholder
        scripts_path = skill_path / "scripts"
        scripts_path.mkdir(exist_ok=True)
        (scripts_path / ".gitkeep").touch()
        
        print(f"\n✅ Skill generated at: {skill_path}")
        print(f"   - SKILL.md")
        print(f"   - references/ ({len(key_files)} files)")
        print(f"   - scripts/")
        
        return skill_path
        
    finally:
        # Cleanup temp directory
        if temp_dir and not keep_clone:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate an OpenClaw skill from a repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python generate.py https://github.com/org/repo
    python generate.py /path/to/local/repo
    python generate.py https://github.com/org/repo --output ./skills/my-skill
    python generate.py . --output ./my-project-skill
        """,
    )
    parser.add_argument(
        "source",
        help="Repository URL or local path",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output directory for the skill (default: ./skills/<repo-name>)",
    )
    parser.add_argument(
        "--keep-clone",
        action="store_true",
        help="Keep the cloned repository (for URLs)",
    )
    
    args = parser.parse_args()
    
    try:
        skill_path = generate_skill(args.source, args.output, args.keep_clone)
        print(f"\nNext steps:")
        print(f"  1. Review and edit {skill_path}/SKILL.md")
        print(f"  2. Add any custom scripts to {skill_path}/scripts/")
        print(f"  3. Symlink to workspace: ln -s {skill_path} ~/.openclaw/workspace/skills/")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
