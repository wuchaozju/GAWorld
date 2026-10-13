"""Bundle the source runtime and its public assets in wheels and sdists."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from setuptools.command.build_py import build_py


class BuildRuntime(build_py):
    """Preserve the simulator's repository-relative paths in a user workspace."""

    def run(self):
        super().run()
        root = Path(__file__).resolve().parents[2]
        target = Path(self.build_lib) / "gaworld" / "_assets" / "runtime.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        allowed = {
            ".py",
            ".html",
            ".js",
            ".css",
            ".svg",
            ".png",
            ".jpg",
            ".jpeg",
            ".json",
            ".geojson",
            ".md",
            ".csv",
            ".txt",
            ".yaml",
            ".yml",
            ".toml",
            ".ttf",
            ".otf",
            ".woff",
            ".woff2",
        }
        files = [
            root / name
            for name in (
                "generative_city_sim.py",
                "environment.py",
                "dashboard_server.py",
                "distributed_comm_server.py",
            )
        ]
        for folder in ("gaworld", "site", "data", "scripts", "docs"):
            for source in sorted((root / folder).rglob("*")):
                relative = source.relative_to(root)
                if (
                    source.is_file()
                    and not source.is_symlink()
                    and source.suffix in allowed
                    and not any(
                        part.startswith(".") or part in {"__pycache__", "_assets", "node_modules"}
                        for part in relative.parts
                    )
                    and "test" not in source.name
                    and source.name not in {"twin_bindings.json", "moltbook_accounts.json", "news_cache.json"}
                ):
                    files.append(source)
        with ZipFile(target, "w", ZIP_DEFLATED) as archive:
            for source in files:
                archive.write(source, source.relative_to(root).as_posix())

    def get_outputs(self, include_bytecode=1):
        return [
            *super().get_outputs(include_bytecode),
            str(Path(self.build_lib) / "gaworld" / "_assets" / "runtime.zip"),
        ]
