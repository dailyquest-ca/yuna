"""No function may read a name nothing ever binds — the rename bug, caught before production.

This exists because of a specific failure on 2026-08-03. A counter was renamed `m4_unknown` ->
`m4_missing` in three places out of four; the fourth read still said `m4_unknown`. Every unit test
passed, the integration suite passed (it stubs the ranking half), and `score` died in production
with `UnboundLocalError` after eleven minutes of real work.

Nothing in the suite could have caught it, because the defect is not behavioural — it is a name
that exists nowhere. So the check is structural, stdlib-only, and runs over every module in `src`.

Deliberately conservative: it walks enclosing scopes, `except ... as`, comprehension and `with`
targets, `global`/`nonlocal`, star-imports and module-level bindings, and only reports a name that
is bound in NONE of them. A lint that cries wolf gets switched off.
"""
import ast
import builtins
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def module_bindings(tree):
    """Everything visible at module level: imports, assignments, defs, classes.

    Only MODULE-LEVEL statements. Walking the whole tree would sweep up every local variable in
    every function and make the check vacuous — which is exactly what the first draft of this file
    did, and why it passed while the bug it was written for sat two directories away.
    """
    out = set()
    for stmt in tree.body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    out.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(node.name)
        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for t in targets:
                for node in ast.walk(t):
                    if isinstance(node, ast.Name):
                        out.add(node.id)
        elif isinstance(stmt, (ast.For, ast.With, ast.Try, ast.If, ast.While)):
            for node in ast.walk(stmt):        # module-level control flow can still bind names
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    out.add(node.id)
    return out


def augmented_targets(scope):
    """Names that only ever appear as `x += ...` targets in this scope.

    `+=` parses as a Store, so a naive binding scan counts it as a definition — but at runtime it
    READS first, and reading an unbound local raises UnboundLocalError. That is precisely the shape
    of the 2026-08-03 failure, so it gets its own case rather than being folded into the rest.
    """
    aug, other = set(), set()
    # ast.walk yields the AugAssign AND its target Name separately, and that Name carries
    # ctx=Store — so the target has to be excluded by identity, or it cancels itself out.
    aug_nodes = {id(n.target) for n in ast.walk(scope)
                 if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)}
    for node in ast.walk(scope):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            aug.add(node.target.id)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if id(node) not in aug_nodes:
                other.add(node.id)
        elif isinstance(node, ast.arg):
            other.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            other.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            other.update(node.names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                other.add(a.asname or a.name.split(".")[0])
    return aug - other


def bound_in(scope):
    """Every name this scope binds, by any means Python offers."""
    out = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)                      # `except E as e`
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
    return out


def undefined_reads(path):
    tree = ast.parse(path.read_text(), str(path))
    visible_at_module = module_bindings(tree) | BUILTINS
    problems = []

    def walk(scope, enclosing):
        visible = enclosing | bound_in(scope)
        where = getattr(scope, "name", "<module>")
        for node in ast.walk(scope):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in visible:
                    problems.append(f"{path.name}:{node.lineno} {where}() reads `{node.id}`, "
                                    f"which nothing binds")
        for name in sorted(augmented_targets(scope)):
            if name not in enclosing:
                node = next(n for n in ast.walk(scope)
                            if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
                            and n.target.id == name)
                problems.append(f"{path.name}:{node.lineno} {where}() does `{name} += ...` but "
                                f"nothing ever initialises `{name}`")
        for child in ast.walk(scope):
            if child is not scope and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, visible)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk(node, visible_at_module)
    return problems


def test_no_module_in_src_reads_a_name_nothing_binds():
    found = []
    for path in sorted(SRC.glob("*.py")):
        found += undefined_reads(path)
    assert not found, ("a name is read that nothing binds — this is the shape of a half-finished "
                       "rename, and it fails in production, not in the tests:\n  "
                       + "\n  ".join(found))
