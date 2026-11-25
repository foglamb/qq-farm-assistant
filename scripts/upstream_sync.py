#!/usr/bin/env python3
"""Fetch upstream and optionally merge it without silently replacing local work."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, text=True, check=check)


def output(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="merge, test and commit; never push or deploy")
    parser.add_argument("--remote", default="upstream")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    target = f"{args.remote}/{args.branch}"

    run("git", "fetch", args.remote, args.branch)
    local = output("git", "rev-parse", "HEAD")
    remote = output("git", "rev-parse", target)
    ahead, behind = output("git", "rev-list", "--left-right", "--count", f"HEAD...{target}").split()
    print(f"local={local}\nupstream={remote}\nahead={ahead} behind={behind}")
    if not args.apply:
        return 0
    if output("git", "status", "--porcelain"):
        print("工作区不干净：先提交或备份当前修改，未执行合并。", file=sys.stderr)
        return 2
    if output("git", "branch", "--show-current") in {"", "main", "master"}:
        print("请在自己的功能分支执行，避免直接改写上游主分支。", file=sys.stderr)
        return 2
    if behind == "0":
        print("已是最新，无需合并。")
        return 0

    # --no-ff prevents a fast-forward from bypassing the test/commit gate.
    merged = run("git", "merge", "--no-ff", "--no-commit", target, check=False)
    if merged.returncode:
        print("上游与定制代码有冲突：保留冲突供人工解决，不覆盖任何一侧。\n"
              "解决后运行 scripts/test-ondemand.sh，再提交；放弃则用 git merge --abort。", file=sys.stderr)
        return 3

    tested = run("sh", "scripts/test-ondemand.sh", check=False)
    if tested.returncode:
        run("git", "merge", "--abort", check=False)
        print("契约测试失败，已取消本次未提交合并；此前定制提交保持不变。", file=sys.stderr)
        return tested.returncode or 1
    run("git", "commit", "-m", f"merge: {target} into on-demand customization")
    print("合并和契约测试通过；未推送、未构建、未重启生产服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
