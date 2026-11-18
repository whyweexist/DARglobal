"""Docker build context must not assume optional empty directories exist."""
from pathlib import Path


def test_optional_evaluations_do_not_block_docker_build():
    project = Path(__file__).resolve().parents[2]
    dockerfile = (project / "Dockerfile.api").read_text()
    assert "COPY evaluations " not in dockerfile
    assert "RUN mkdir -p /app/evaluations/retrieval" in dockerfile


def test_all_local_copy_sources_exist():
    project = Path(__file__).resolve().parents[2]
    for name in ("Dockerfile.api", "Dockerfile.frontend"):
        contents = (project / name).read_text()
        for line in contents.splitlines():
            if not line.startswith("COPY ") or "--from=" in line:
                continue
            source = line.split()[1]
            assert (project / source).exists(), f"{name}: missing source {source}"


def test_cpu_torch_wheels_enforced_for_x86_64_docker():
    project = Path(__file__).resolve().parents[2]
    dockerfile = (project / "Dockerfile.api").read_text()
    pyproject = (project / "backend/pyproject.toml").read_text()
    assert "UV_TORCH_BACKEND=cpu" in dockerfile
    assert "torch.version.cuda is None" in dockerfile
    assert "torch>=2.5,<3" in pyproject
    assert 'url = "https://download.pytorch.org/whl/cpu"' in pyproject
    assert "platform_machine == 'x86_64'" in pyproject


def test_ci_uses_cpu_torch_dependency_resolution():
    project = Path(__file__).resolve().parents[2]
    ci = (project / ".github/workflows/ci.yml").read_text()
    assert "uv pip install --system --torch-backend cpu" in ci
