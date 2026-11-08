import json
import re
import subprocess

import yaml


class DVCTools:
    def __init__(self, settings):
        self.root = settings.repo_path.resolve()
        self.timeout = settings.tool_timeout

    def command(self, *args):
        # Only internal methods construct commands; user input never becomes a shell program.
        result = subprocess.run(
            list(args), cwd=self.root, capture_output=True, text=True,
            timeout=self.timeout, check=True, shell=False,
        )
        return result.stdout.strip()

    def revision(self, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/~^\-]{0,150}", value):
            raise ValueError("Invalid Git revision")
        return self.command("git", "rev-parse", "--verify", f"{value}^{{commit}}")

    def datasets(self, args):
        files = self.command("git", "ls-files").splitlines()
        result = []
        for name in files:
            if name.endswith(".dvc"):
                metadata = yaml.safe_load((self.root / name).read_text())
                for out in metadata.get("outs", []):
                    result.append({"metadata": name, **out})
        lock = self.root / "dvc.lock"
        if lock.exists():
            for stage, record in yaml.safe_load(lock.read_text()).get("stages", {}).items():
                result.extend({"stage": stage, **out} for out in record.get("outs", []))
        return {"datasets": result}

    def version(self, args):
        commit = self.revision(args.revision)
        files = self.command("git", "ls-tree", "-r", "--name-only", commit).splitlines()
        refs = {}
        for name in files:
            if name.endswith(".dvc") or name == "dvc.lock":
                refs[name] = yaml.safe_load(self.command("git", "show", f"{commit}:{name}"))
        return {"git_commit": commit, "references": refs}

    def compare(self, args):
        left, right = self.revision(args.revision), self.revision(args.other_revision)
        return json.loads(self.command("dvc", "diff", "--json", "--show-hash", left, right))

    def status(self, args):
        return {"changes": json.loads(self.command("dvc", "status", "--json"))}

    def reproduce(self, args):
        commit = self.revision(args.revision)
        return {
            "git_commit": commit,
            "commands": [f"git worktree add ../dataset-reproduction {commit}",
                         "cd ../dataset-reproduction", "dvc pull", "dvc checkout"],
            "note": "Run in a separate worktree with access to the configured DVC remote.",
        }
