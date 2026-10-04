import ast
import os
import hashlib
from typing import Dict, Any, List

def analyze_script(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {}

    has_argparse = False
    has_hydra = False
    args = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "argparse":
                    has_argparse = True
                if alias.name == "hydra":
                    has_hydra = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "argparse":
                has_argparse = True
            if node.module == "hydra":
                has_hydra = True
        
        # simple heuristic for add_argument
        if isinstance(node, ast.Call) and getattr(getattr(node, 'func', None), 'attr', None) == 'add_argument':
            if node.args and isinstance(node.args[0], ast.Constant):
                args.append(node.args[0].value)

    return {
        "has_argparse": has_argparse,
        "has_hydra": has_hydra,
        "arguments": args
    }

def index_repository(repo_path: str) -> dict:
    entry_scripts = []
    argparse_interfaces = {}
    yaml_configs = []
    readme_commands = []
    config_files = []
    uses_hydra = False
    dependencies = []
    
    # Calculate a simple hash
    hasher = hashlib.sha256()

    for root, _, files in os.walk(repo_path):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, repo_path)
            hasher.update(rel_path.encode('utf-8'))
            
            if file.endswith(".py"):
                analysis = analyze_script(full_path)
                if analysis.get("has_argparse") or analysis.get("has_hydra") or "main" in file:
                    entry_scripts.append(rel_path)
                    if analysis.get("has_hydra"):
                        uses_hydra = True
                    if analysis.get("arguments"):
                        argparse_interfaces[rel_path] = analysis["arguments"]
                        
            elif file.endswith(".yaml") or file.endswith(".yml"):
                yaml_configs.append(rel_path)
                config_files.append(rel_path)
                
            elif file.lower().startswith("readme"):
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    # Simple heuristic: lines starting with python
                    for line in content.split("\n"):
                        if line.strip().startswith("python "):
                            readme_commands.append(line.strip())
                            
            elif file == "requirements.txt" or file == "environment.yml" or file == "pyproject.toml":
                dependencies.append(rel_path)

    repo_date = None
    if os.path.exists(os.path.join(repo_path, ".git")):
        import subprocess
        try:
            result = subprocess.check_output(
                ["git", "log", "-1", "--format=%cI"],
                cwd=repo_path,
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            if result:
                repo_date = result
        except Exception:
            pass

    return {
        "repo_hash": hasher.hexdigest(),
        "repository_date": repo_date,
        "entry_scripts": entry_scripts,
        "argparse_interfaces": argparse_interfaces,
        "yaml_configs": yaml_configs,
        "readme_commands": readme_commands,
        "dependencies": dependencies,
        "config_files": config_files,
        "uses_hydra": uses_hydra
    }
