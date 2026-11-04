"""Run in a verified environment to record installed runtime dependencies."""

from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement

pending = ["aiogram", "redis", "asyncpg", "mutagen", "Pillow", "pydantic-settings"]
found = {}
while pending:
    package = distribution(pending.pop())
    name = package.metadata["Name"]
    if name.lower() in found:
        continue
    found[name.lower()] = (name, package.version)
    for raw in package.requires or []:
        requirement = Requirement(raw)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            pending.append(requirement.name)
Path("requirements.lock").write_text(
    "\n".join(f"{name}=={version}" for name, version in sorted(found.values())) + "\n",
    encoding="utf-8",
)
