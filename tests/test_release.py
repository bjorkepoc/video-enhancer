from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_release_uses_the_hashed_lock_without_build_isolation() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    security_job, release_job = workflow.split("\n  security:\n", 1)[1].split(
        "\n  release:\n", 1
    )

    assert "uv export --locked --no-dev --extra macos --group release" in security_job
    assert "--no-emit-project --format requirements-txt" in security_job
    assert "runs-on: macos-15" in security_job
    assert "pip-audit==2.10.1" in security_job
    assert "bandit==1.9.4" in security_job
    assert "pip freeze" not in security_job
    assert "pip install" not in security_job

    assert (
        "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9"
        in release_job
    )
    assert 'version: "0.11.21"' in release_job
    sync = "uv sync --locked --no-dev --extra macos --group release"
    assert f"{sync} --no-install-project" in release_job
    assert f"{sync} --no-build-isolation" in release_job
    assert release_job.index("Install locked release dependencies") < release_job.index(
        "Import Developer ID certificate"
    )
    assert "python -m build --no-isolation" in release_job
    assert "--prerelease" in release_job
    assert "pip install" not in release_job

    requirements = re.findall(r'"([\w-]+)(?:\[[^]]+\])?[<>=!~]', project)
    lock = (ROOT / "uv.lock").read_text()
    assert set(requirements) <= set(re.findall(r'^name = "([\w-]+)"$', lock, re.MULTILINE))

    artifacts = re.findall(r'^\s*(?:sdist = )?\{ url = .+$', lock, re.MULTILINE)
    assert artifacts and all('hash = "sha256:' in artifact for artifact in artifacts)
