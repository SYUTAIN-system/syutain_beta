"""
SYUTAINβ V25 モジュール依存関係マッピング+デッドコード検出
設計書準拠: ast解析による依存グラフ生成・循環依存検出・CODE_MAP.md自動生成

Pure Python (ast + stdlib only). No external dependencies.
"""

import ast
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("syutain.dependency_mapper")

BASE_DIR = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"node_modules", "__pycache__", "venv", ".next", ".git", "certs", "logs"}


# ---------------------------------------------------------------------------
#  Utilities
# ---------------------------------------------------------------------------

def _collect_py_files() -> list[Path]:
    """プロジェクト内の全.pyファイルを収集（除外ディレクトリを尊重）"""
    results = []
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".py"):
                results.append(Path(root) / f)
    return sorted(results)


def _rel(path: Path) -> str:
    """BASE_DIRからの相対パスを返す"""
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def _path_to_module(fp: Path) -> str:
    """ファイルパスをモジュール名に変換"""
    rel = fp.relative_to(BASE_DIR)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")
    return ".".join(parts)


def _safe_parse(path: Path) -> Optional[ast.Module]:
    """Pythonファイルをパース。失敗時はNoneを返す"""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning(f"ast解析失敗: {path} — {e}")
        return None


def _attr_chain(node: ast.Attribute) -> str:
    """ドット付き属性を再構成 (例: app.get)"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
#  1. map_dependencies()
# ---------------------------------------------------------------------------

async def map_dependencies() -> dict[str, dict[str, Any]]:
    """
    全.pyファイルをパースし依存グラフを生成。
    Returns:
      { relative_path: {
            imports: [str, ...],
            functions: [(name, lineno), ...],
            classes: [(name, lineno), ...],
            line_count: int,
            docstring: str | None,
            decorators: {func_name: [decorator_names]},
        }
      }
    """
    graph: dict[str, dict[str, Any]] = {}
    for path in _collect_py_files():
        tree = _safe_parse(path)
        if tree is None:
            continue

        imports: list[str] = []
        functions: list[tuple[str, int]] = []
        classes: list[tuple[str, int]] = []
        decorators: dict[str, list[str]] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append((node.name, node.lineno))
                deco_names = []
                for d in node.decorator_list:
                    if isinstance(d, ast.Name):
                        deco_names.append(d.id)
                    elif isinstance(d, ast.Attribute):
                        deco_names.append(_attr_chain(d))
                    elif isinstance(d, ast.Call):
                        if isinstance(d.func, ast.Name):
                            deco_names.append(d.func.id)
                        elif isinstance(d.func, ast.Attribute):
                            deco_names.append(_attr_chain(d.func))
                if deco_names:
                    decorators[node.name] = deco_names

            if isinstance(node, ast.ClassDef):
                classes.append((node.name, node.lineno))

        source_text = path.read_text(encoding="utf-8", errors="replace")
        line_count = source_text.count("\n") + 1
        docstring = ast.get_docstring(tree)

        graph[_rel(path)] = {
            "imports": imports,
            "functions": functions,
            "classes": classes,
            "line_count": line_count,
            "docstring": docstring,
            "decorators": decorators,
        }

    return graph


# ---------------------------------------------------------------------------
#  Dead code detection helpers
# ---------------------------------------------------------------------------

def _collect_all_names_used(tree: ast.Module) -> set[str]:
    """全Name/Attribute参照を収集（呼び出し、参照、文字列参照含む）"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for word in node.value.split():
                cleaned = word.strip("\"'(),:")
                if cleaned.isidentifier():
                    names.add(cleaned)
    return names


# Endpoint/job/event decorators — these functions are alive by definition
_ALIVE_DECORATORS = {
    "app.get", "app.post", "app.put", "app.delete", "app.patch",
    "app.websocket", "app.on_event", "router.get", "router.post",
    "router.put", "router.delete", "router.patch", "router.websocket",
    "app.route", "router.route",
    "bot.event", "bot.command", "commands.command",
    "tasks.loop",
    "staticmethod", "classmethod", "property", "abstractmethod",
}

# 絶対にフラグしない関数名
_ALIVE_NAMES = {
    "__init__", "__main__", "main", "setup", "teardown",
    "__enter__", "__exit__", "__aenter__", "__aexit__",
    "__repr__", "__str__", "__len__", "__getitem__", "__setitem__",
    "__delitem__", "__iter__", "__next__", "__call__", "__hash__",
    "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__bool__", "__contains__", "__add__", "__sub__", "__mul__",
    "__truediv__", "__floordiv__", "__mod__", "__pow__",
    "on_ready", "on_message", "on_member_join", "on_error",
    "lifespan",
}


# ---------------------------------------------------------------------------
#  2. find_dead_code()
# ---------------------------------------------------------------------------

async def find_dead_code() -> list[dict[str, Any]]:
    """
    定義されているが一度もインポート・呼び出しされていない関数を検出。
    Returns list of {file, function_name, line_number, reason}.
    """
    files = _collect_py_files()

    # Parse all files
    trees: dict[str, ast.Module] = {}
    for path in files:
        tree = _safe_parse(path)
        if tree is not None:
            trees[_rel(path)] = tree

    # Collect all import names across the project
    all_import_names: set[str] = set()
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    all_import_names.add(alias.asname or alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    all_import_names.add(alias.asname or alias.name)

    # Collect definitions with decorator info
    definitions: list[dict[str, Any]] = []
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                deco_names = []
                for d in node.decorator_list:
                    if isinstance(d, ast.Name):
                        deco_names.append(d.id)
                    elif isinstance(d, ast.Attribute):
                        deco_names.append(_attr_chain(d))
                    elif isinstance(d, ast.Call):
                        if isinstance(d.func, ast.Name):
                            deco_names.append(d.func.id)
                        elif isinstance(d.func, ast.Attribute):
                            deco_names.append(_attr_chain(d.func))
                definitions.append({
                    "file": rel,
                    "name": node.name,
                    "lineno": node.lineno,
                    "decorators": deco_names,
                })

    # Check each definition
    dead: list[dict[str, Any]] = []
    for defn in definitions:
        name = defn["name"]
        file = defn["file"]

        # Skip magic methods and known-alive names
        if name in _ALIVE_NAMES or (name.startswith("__") and name.endswith("__")):
            continue

        # Skip private helpers in test files
        if "test" in file.lower() and name.startswith("_"):
            continue

        # Skip decorated endpoints / jobs
        if any(d in _ALIVE_DECORATORS for d in defn["decorators"]):
            continue

        # Check if the function is referenced in other files
        used_elsewhere = False
        for other_rel, other_tree in trees.items():
            if other_rel == file:
                # Same file: check if called (not just defined)
                for node in ast.walk(other_tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name) and node.func.id == name:
                            used_elsewhere = True
                            break
                        if isinstance(node.func, ast.Attribute) and node.func.attr == name:
                            used_elsewhere = True
                            break
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        if name in node.value:
                            used_elsewhere = True
                            break
                if used_elsewhere:
                    break
                continue

            # Other files: check if name appears in usages
            other_names = _collect_all_names_used(other_tree)
            if name in other_names:
                used_elsewhere = True
                break

        if not used_elsewhere:
            if name in all_import_names:
                continue
            dead.append({
                "file": file,
                "function_name": name,
                "line_number": defn["lineno"],
                "reason": "Defined but never called or imported elsewhere",
            })

    return dead


# ---------------------------------------------------------------------------
#  3. check_circular_imports()
# ---------------------------------------------------------------------------

def _resolve_import_to_module(import_str: str) -> Optional[str]:
    """
    インポート文字列をプロジェクト相対モジュールパスに解決。
    例: 'tools.llm_router.choose_best_model_v6' -> 'tools/llm_router.py'
    """
    parts = import_str.split(".")
    for length in range(len(parts), 0, -1):
        candidate = "/".join(parts[:length]) + ".py"
        if (BASE_DIR / candidate).exists():
            return candidate
        candidate_pkg = "/".join(parts[:length]) + "/__init__.py"
        if (BASE_DIR / candidate_pkg).exists():
            return "/".join(parts[:length]) + "/__init__.py"
    return None


async def check_circular_imports() -> list[list[str]]:
    """
    インポート文から有向グラフを構築し、DFSで循環を検出。
    Returns list of cycles (each cycle is a list of module paths).
    """
    files = _collect_py_files()

    adj: dict[str, set[str]] = defaultdict(set)
    all_modules: set[str] = set()

    for path in files:
        tree = _safe_parse(path)
        if tree is None:
            continue
        source = _rel(path)
        all_modules.add(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _resolve_import_to_module(alias.name)
                    if target and target != source:
                        adj[source].add(target)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                target = _resolve_import_to_module(module)
                if target and target != source:
                    adj[source].add(target)

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {m: WHITE for m in all_modules}
    cycles: list[list[str]] = []

    def dfs(u: str, path: list[str]):
        color[u] = GRAY
        path.append(u)
        for v in adj.get(u, set()):
            if v not in color:
                continue
            if color[v] == GRAY:
                idx = path.index(v)
                cycle = path[idx:] + [v]
                min_idx = cycle.index(min(cycle[:-1]))
                normalized = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                cycle_set = frozenset(normalized[:-1])
                if not any(frozenset(c[:-1]) == cycle_set for c in cycles):
                    cycles.append(normalized)
            elif color[v] == WHITE:
                dfs(v, path)
        path.pop()
        color[u] = BLACK

    for m in sorted(all_modules):
        if color[m] == WHITE:
            dfs(m, [])

    return cycles


# ---------------------------------------------------------------------------
#  4. generate_code_map()
# ---------------------------------------------------------------------------

async def generate_code_map() -> str:
    """CODE_MAP.mdを自動生成してBASE_DIRに保存。内容を返す。"""
    deps = await map_dependencies()
    dead = await find_dead_code()
    cycles = await check_circular_imports()

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S JST")

    lines: list[str] = []
    lines.append("# SYUTAINβ Code Map")
    lines.append("")
    lines.append(f"**Auto-generated by dependency_mapper.py**  ")
    lines.append(f"**Last updated:** {now}  ")
    lines.append(f"**Total files:** {len(deps)}  ")
    total_lines = sum(v["line_count"] for v in deps.values())
    lines.append(f"**Total lines:** {total_lines:,}  ")
    lines.append("")

    # Directory structure
    lines.append("## Directory Structure")
    lines.append("")
    dir_stats: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0})
    for path, info in deps.items():
        d = str(Path(path).parent) if "/" in path else "."
        dir_stats[d]["files"] += 1
        dir_stats[d]["lines"] += info["line_count"]

    lines.append("| Directory | Files | Lines |")
    lines.append("|-----------|------:|------:|")
    for d in sorted(dir_stats.keys()):
        s = dir_stats[d]
        lines.append(f"| `{d}/` | {s['files']} | {s['lines']:,} |")
    lines.append("")

    # Module details
    lines.append("## Modules")
    lines.append("")
    all_dirs = sorted(set(str(Path(p).parent) for p in deps.keys()))
    for d in all_dirs:
        dir_files = {p: v for p, v in deps.items()
                     if str(Path(p).parent) == d or (d == "." and "/" not in p)}
        if not dir_files:
            continue
        lines.append(f"### `{d}/`")
        lines.append("")
        for path in sorted(dir_files.keys()):
            info = dir_files[path]
            fname = Path(path).name
            lines.append(f"#### `{fname}` ({info['line_count']} lines)")
            if info["docstring"]:
                first_line = info["docstring"].split("\n")[0].strip()
                lines.append(f"*{first_line}*")
            lines.append("")
            if info["classes"]:
                lines.append(f"**Classes:** {', '.join(c[0] for c in info['classes'])}")
            if info["functions"]:
                fn_names = [f[0] for f in info["functions"] if not f[0].startswith("_")]
                if fn_names:
                    lines.append(f"**Functions:** {', '.join(fn_names[:15])}")
                    if len(fn_names) > 15:
                        lines.append(f"  _(+{len(fn_names) - 15} more)_")
            if info["imports"]:
                internal = [i for i in info["imports"]
                            if any(i.startswith(p) for p in
                                   ("tools.", "agents.", "brain_alpha.", "bots.",
                                    "config.", "strategy.", "mcp_servers.", "scripts."))]
                if internal:
                    lines.append(f"**Internal deps:** {', '.join(sorted(set(internal)))}")
            lines.append("")

    # Dependency graph
    lines.append("## Dependency Graph (Internal)")
    lines.append("")
    lines.append("```")
    for path in sorted(deps.keys()):
        info = deps[path]
        internal = sorted(set(
            i for i in info["imports"]
            if any(i.startswith(p) for p in
                   ("tools.", "agents.", "brain_alpha.", "bots.",
                    "config.", "strategy.", "mcp_servers.", "scripts."))
        ))
        if internal:
            lines.append(f"{path}")
            for imp in internal:
                lines.append(f"  -> {imp}")
    lines.append("```")
    lines.append("")

    # Dead code
    lines.append(f"## Dead Code Warnings ({len(dead)} found)")
    lines.append("")
    if dead:
        lines.append("| File | Function | Line | Reason |")
        lines.append("|------|----------|-----:|--------|")
        for d in sorted(dead, key=lambda x: (x["file"], x["line_number"])):
            lines.append(
                f"| `{d['file']}` | `{d['function_name']}` "
                f"| {d['line_number']} | {d['reason']} |"
            )
    else:
        lines.append("No dead code detected.")
    lines.append("")

    # Circular imports
    lines.append(f"## Circular Import Warnings ({len(cycles)} found)")
    lines.append("")
    if cycles:
        for i, cycle in enumerate(cycles, 1):
            lines.append(f"{i}. `{'` -> `'.join(cycle)}`")
    else:
        lines.append("No circular imports detected.")
    lines.append("")

    content = "\n".join(lines)
    output_path = BASE_DIR / "CODE_MAP.md"
    output_path.write_text(content, encoding="utf-8")
    logger.info(f"CODE_MAP.md生成完了: {len(deps)}モジュール, {total_lines:,}行")

    try:
        from tools.event_logger import log_event
        await log_event(
            "system.code_map_generated", "system",
            {
                "total_modules": len(deps),
                "total_lines": total_lines,
                "dead_code_count": len(dead),
                "circular_imports": len(cycles),
            },
        )
    except Exception:
        pass

    return content


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

async def _main():
    print("=" * 60)
    print("SYUTAINβ Dependency Mapper & Dead Code Detector")
    print("=" * 60)
    print()

    t0 = time.monotonic()

    print("[1/4] Mapping dependencies...")
    deps = await map_dependencies()
    total_lines = sum(v["line_count"] for v in deps.values())
    total_funcs = sum(len(v["functions"]) for v in deps.values())
    total_classes = sum(len(v["classes"]) for v in deps.values())
    print(f"  Modules mapped: {len(deps)}")
    print(f"  Total lines: {total_lines:,}")
    print(f"  Total functions: {total_funcs}")
    print(f"  Total classes: {total_classes}")
    print()

    print("[2/4] Finding dead code...")
    dead = await find_dead_code()
    print(f"  Dead code candidates: {len(dead)}")
    for d in dead[:20]:
        print(f"    {d['file']}:{d['line_number']}  {d['function_name']}()")
    if len(dead) > 20:
        print(f"    ... and {len(dead) - 20} more")
    print()

    print("[3/4] Checking circular imports...")
    cycles = await check_circular_imports()
    print(f"  Circular imports: {len(cycles)}")
    for c in cycles[:10]:
        print(f"    {'  ->  '.join(c)}")
    print()

    print("[4/4] Generating CODE_MAP.md...")
    await generate_code_map()
    print(f"  Saved to {BASE_DIR / 'CODE_MAP.md'}")

    elapsed = time.monotonic() - t0
    print()
    print(f"Done in {elapsed:.2f}s")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
