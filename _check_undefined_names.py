"""Lightweight static check for likely-undefined names (no pyflakes available).

Not a full scope resolver — approximates a check by unioning:
  - Python builtins
  - module-level names (imports, top-level assigns/def/class, star imports assumed OK)
  - names assigned anywhere in the *same function* (params, assigns, for/with targets,
    except targets, comprehension targets, nested def/class names)
  - names assigned in any *enclosing* function (simple closure approximation)
against every Name(Load) reference found inside each function body.
Flags a name as suspicious only if it's never defined anywhere accessible in the
module (module scope) or in the function/enclosing-function chain.
"""
import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {"__name__", "__file__", "self", "cls"}


def collect_targets(node, out):
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for el in node.elts:
            collect_targets(el, out)
    elif isinstance(node, ast.Starred):
        collect_targets(node.value, out)
    elif isinstance(node, ast.Attribute):
        pass
    elif isinstance(node, ast.Subscript):
        pass


class ModuleLevelCollector(ast.NodeVisitor):
    def __init__(self):
        self.names = set()

    def visit_Import(self, node):
        for alias in node.names:
            self.names.add((alias.asname or alias.name).split(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                self.names.add("*")
            else:
                self.names.add(alias.asname or alias.name)

    def visit_Assign(self, node):
        for t in node.targets:
            collect_targets(t, self.names)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        collect_targets(node.target, self.names)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        collect_targets(node.target, self.names)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)
        # don't recurse into function bodies here

    def visit_AsyncFunctionDef(self, node):
        self.names.add(node.name)

    def visit_ClassDef(self, node):
        self.names.add(node.name)
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.names.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    collect_targets(t, self.names)
        # don't recurse further

    def visit_For(self, node):
        collect_targets(node.target, self.names)
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars:
                collect_targets(item.optional_vars, self.names)
        self.generic_visit(node)


def collect_function_local_names(func_node):
    names = set()
    args = func_node.args
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.add(a.arg)
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)

    class Local(ast.NodeVisitor):
        def visit_Assign(self, node):
            for t in node.targets:
                collect_targets(t, names)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            collect_targets(node.target, names)
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            collect_targets(node.target, names)
            self.generic_visit(node)

        def visit_For(self, node):
            collect_targets(node.target, names)
            self.generic_visit(node)

        def visit_With(self, node):
            for item in node.items:
                if item.optional_vars:
                    collect_targets(item.optional_vars, names)
            self.generic_visit(node)

        def visit_ExceptHandler(self, node):
            if node.name:
                names.add(node.name)
            self.generic_visit(node)

        def visit_comprehension(self, node):
            collect_targets(node.target, names)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            names.add(node.name)
            for a in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs):
                pass  # nested func args are its own scope; skip
            self.generic_visit(node)

        def visit_Lambda(self, node):
            pass  # skip lambda internals

        def visit_Import(self, node):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])

        def visit_ImportFrom(self, node):
            for alias in node.names:
                names.add(alias.asname or alias.name)

        def visit_Global(self, node):
            pass

        def visit_walrus(self, node):
            pass

    Local().visit(func_node)

    # walrus operator targets
    for node in ast.walk(func_node):
        if isinstance(node, ast.NamedExpr):
            collect_targets(node.target, names)

    return names


def check_file(path: Path):
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))

    mod_collector = ModuleLevelCollector()
    mod_collector.visit(tree)
    module_names = mod_collector.names
    star_import = "*" in module_names

    issues = []

    def scan_names_own_scope(node, func_node, available, acc):
        """Walk `node`'s Name(Load) usages WITHOUT descending into nested
        function/lambda scopes (those are checked separately by the caller)."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id not in available and not star_import:
                    acc.append((child.lineno, child.id))
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # nested scope — handled separately
            scan_names_own_scope(child, func_node, available, acc)

    def check_function(func_node, enclosing_locals):
        local_names = collect_function_local_names(func_node)
        available = BUILTINS | module_names | enclosing_locals | local_names
        scan_names_own_scope(func_node, func_node, available, issues)

        # Check lambdas defined directly within this function (their own
        # params + defaults are in scope for their body).
        for node in ast.walk(func_node):
            if isinstance(node, ast.Lambda):
                lambda_names = set()
                a = node.args
                for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
                    lambda_names.add(arg.arg)
                if a.vararg:
                    lambda_names.add(a.vararg.arg)
                if a.kwarg:
                    lambda_names.add(a.kwarg.arg)
                lambda_available = available | lambda_names
                for sub in ast.walk(node.body):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        if sub.id not in lambda_available and not star_import:
                            issues.append((sub.lineno, sub.id))

    # Only check top-level functions and methods (functions inside classes), non-nested duplication avoided
    def walk_defs(node, enclosing_locals=frozenset()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                check_function(child, enclosing_locals)
                new_enclosing = enclosing_locals | collect_function_local_names(child)
                walk_defs(child, new_enclosing)
            elif isinstance(child, ast.ClassDef):
                walk_defs(child, enclosing_locals)
            else:
                walk_defs(child, enclosing_locals)

    walk_defs(tree)

    return issues


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    targets = list(root.glob("src/*.py")) + [root / "app.py"] + list(root.glob("pages/*.py"))
    any_issue = False
    for f in sorted(targets):
        issues = check_file(f)
        if issues:
            any_issue = True
            print(f"--- {f} ---")
            seen = set()
            for lineno, name in sorted(issues):
                key = (lineno, name)
                if key in seen:
                    continue
                seen.add(key)
                print(f"  line {lineno}: possibly undefined name '{name}'")
    if not any_issue:
        print("No obviously undefined names found.")


if __name__ == "__main__":
    main()
