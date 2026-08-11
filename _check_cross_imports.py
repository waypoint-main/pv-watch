"""Verify every `from src.X import name` actually finds `name` defined in src/X.py."""
import ast
from pathlib import Path

ROOT = Path(".")


def module_level_names(path: Path) -> set[str]:
    names = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Import,)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def module_path_for(mod: str) -> Path | None:
    # mod like "src.models" or "src"
    parts = mod.split(".")
    if parts[0] != "src":
        return None
    if len(parts) == 1:
        return ROOT / "src" / "__init__.py"
    return ROOT / Path(*parts).with_suffix(".py")


def check_file(path: Path):
    issues = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src"):
            target_path = module_path_for(node.module)
            if target_path is None or not target_path.exists():
                issues.append(f"line {node.lineno}: cannot resolve module '{node.module}'")
                continue
            available = module_level_names(target_path)
            pkg_dir = target_path.parent if target_path.name == "__init__.py" else None
            for alias in node.names:
                if alias.name == "*":
                    continue
                # `from src import submodule` implicitly imports src/submodule.py
                if pkg_dir is not None and (pkg_dir / f"{alias.name}.py").exists():
                    continue
                if alias.name not in available:
                    issues.append(
                        f"line {node.lineno}: '{alias.name}' not found at module level in {target_path} (imported from '{node.module}')"
                    )
    return issues


def main():
    targets = list(ROOT.glob("src/*.py")) + [ROOT / "app.py"] + list(ROOT.glob("pages/*.py")) + list(ROOT.glob("tests/*.py"))
    any_issue = False
    for f in sorted(targets):
        issues = check_file(f)
        if issues:
            any_issue = True
            print(f"--- {f} ---")
            for i in issues:
                print(" ", i)
    if not any_issue:
        print("All cross-module `from src.X import name` references resolved OK.")


if __name__ == "__main__":
    main()
