"""Foundation tests for the Phase 1 cloud service-deployment scaffold (Task
11.2, ADR-029).

Validates:
- The `docker/` directory carries the expected three Dockerfiles
  (cds-harness, cds-kernel, cds-frontend).
- Each Dockerfile is multi-stage with the agreed builder + runtime base
  images per ADR-029 §"Decision".
- Each runtime stage drops privileges to the `cds` system user (uid 10001)
  for parity with the production hygiene already in the k8s manifests.
- Each runtime stage EXPOSEs the same containerPort declared in the
  matching k8s/cds-*.yaml manifest (8081 / 8082 / 3000).
- Each runtime stage carries an ENTRYPOINT (no shell-form CMD drift).
- The cds-kernel image copies Z3 + cvc5 from the project-local .bin/
  staging area; lean / kimina-related binaries are intentionally NOT
  in the image (kimina is an external REST endpoint addressed via
  $CDS_KIMINA_URL — see ADR-029 §"Why no Lean inside cds-kernel").
- The repo-root .dockerignore excludes the heavy paths (target/,
  node_modules/, .venv/, .git/, .agent/) so the docker build context
  stays trim.
- The Justfile registers the five lifecycle recipes (cloud-build,
  cloud-load, cloud-up, cloud-down, cloud-status, cloud-smoke) plus the
  three image-tag constants.

This is a pure offline test — no docker / podman / kind / kubectl
binaries are needed. Live image build + load + apply + cluster smoke is
an operator workflow gated on those tools (Justfile recipes themselves
exit cleanly with a loud notice on missing tools, mirroring the
ADR-028 precedent for `kind-up` / `dapr-helm-install`).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
JUSTFILE = REPO_ROOT / "Justfile"

HARNESS_DOCKERFILE = DOCKER_DIR / "cds-harness.Dockerfile"
KERNEL_DOCKERFILE = DOCKER_DIR / "cds-kernel.Dockerfile"
FRONTEND_DOCKERFILE = DOCKER_DIR / "cds-frontend.Dockerfile"

EXPECTED_PORTS = {
    "cds-harness": 8081,
    "cds-kernel": 8082,
    "cds-frontend": 3000,
}

# Per ADR-029 §"Decision". Each tuple is (builder_substring, runtime_substring)
# — the assertions look for the substring on a `FROM ...` line, not byte-equal
# match, so version bumps inside the locked family stay green.
EXPECTED_BASE_IMAGES = {
    "cds-harness": ("python:", "python:"),
    "cds-kernel": ("rust:", "debian:"),
    "cds-frontend": ("oven/bun:", "node:"),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _from_lines(text: str) -> list[str]:
    """Return the FROM lines (case-insensitive, ignoring # comments)."""
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.upper().startswith("FROM "):
            lines.append(stripped)
    return lines


def test_docker_directory_exists_and_contains_three_dockerfiles() -> None:
    assert DOCKER_DIR.is_dir(), f"missing {DOCKER_DIR}"
    for path in (HARNESS_DOCKERFILE, KERNEL_DOCKERFILE, FRONTEND_DOCKERFILE):
        assert path.is_file(), f"missing {path}"


def test_each_dockerfile_is_multi_stage() -> None:
    """At least one builder stage + a final runtime stage."""
    for path in (HARNESS_DOCKERFILE, KERNEL_DOCKERFILE, FRONTEND_DOCKERFILE):
        froms = _from_lines(_read(path))
        assert len(froms) >= 2, (
            f"{path.name}: multi-stage build requires >=2 FROM lines, got {len(froms)}"
        )
        assert any("AS builder" in line for line in froms), (
            f"{path.name}: missing `AS builder` stage"
        )
        assert any("AS runtime" in line for line in froms), (
            f"{path.name}: missing `AS runtime` stage"
        )


def test_each_dockerfile_uses_locked_base_images() -> None:
    """Builder + runtime base images match the ADR-029 lock."""
    paths = {
        "cds-harness": HARNESS_DOCKERFILE,
        "cds-kernel": KERNEL_DOCKERFILE,
        "cds-frontend": FRONTEND_DOCKERFILE,
    }
    for app, path in paths.items():
        builder_pin, runtime_pin = EXPECTED_BASE_IMAGES[app]
        froms = _from_lines(_read(path))
        builder_line = next((line for line in froms if "AS builder" in line), None)
        runtime_line = next((line for line in froms if "AS runtime" in line), None)
        assert builder_line is not None, f"{app}: missing builder FROM"
        assert runtime_line is not None, f"{app}: missing runtime FROM"
        assert builder_pin in builder_line, (
            f"{app}: builder base image {builder_line!r} does not contain {builder_pin!r}"
        )
        assert runtime_pin in runtime_line, (
            f"{app}: runtime base image {runtime_line!r} does not contain {runtime_pin!r}"
        )


def test_each_dockerfile_drops_to_non_root_cds_user() -> None:
    """Runtime stage drops privileges to uid 10001 / `cds` user."""
    for path in (HARNESS_DOCKERFILE, KERNEL_DOCKERFILE, FRONTEND_DOCKERFILE):
        text = _read(path)
        assert "USER cds" in text, f"{path.name}: runtime stage must `USER cds`"
        assert "10001" in text, (
            f"{path.name}: cds user must be uid 10001 (parity across the three images)"
        )


def test_each_dockerfile_exposes_matching_k8s_port() -> None:
    """EXPOSE in the runtime stage matches the k8s manifest's containerPort."""
    paths = {
        "cds-harness": HARNESS_DOCKERFILE,
        "cds-kernel": KERNEL_DOCKERFILE,
        "cds-frontend": FRONTEND_DOCKERFILE,
    }
    for app, path in paths.items():
        port = EXPECTED_PORTS[app]
        text = _read(path)
        assert f"EXPOSE {port}" in text, (
            f"{app}: runtime stage missing `EXPOSE {port}` (must mirror "
            f"k8s/{app}.yaml containerPort)"
        )


def test_each_dockerfile_declares_entrypoint() -> None:
    """Exec-form ENTRYPOINT keeps PID 1 well-defined under Kubernetes."""
    for path in (HARNESS_DOCKERFILE, KERNEL_DOCKERFILE, FRONTEND_DOCKERFILE):
        text = _read(path)
        assert "ENTRYPOINT [" in text, (
            f"{path.name}: missing exec-form ENTRYPOINT (avoids shell PID-1 drift)"
        )


def test_cds_kernel_dockerfile_carries_solver_binaries() -> None:
    """Z3 + cvc5 copied from .bin/; lean intentionally absent."""
    text = _read(KERNEL_DOCKERFILE)
    assert "COPY .bin/z3" in text, "cds-kernel: missing COPY .bin/z3"
    assert "COPY .bin/cvc5" in text, "cds-kernel: missing COPY .bin/cvc5"
    assert "COPY .bin/lean" not in text, (
        "cds-kernel: lean must NOT be in the image (Kimina is external; ADR-029)"
    )
    # PATH + per-binary env knobs (parity with self-hosted ADR-020 §5).
    assert "CDS_Z3_PATH=/opt/cds/bin/z3" in text
    assert "CDS_CVC5_PATH=/opt/cds/bin/cvc5" in text


def test_cds_kernel_runtime_includes_libstdcpp() -> None:
    """libstdc++6 + libgomp1 are required for the upstream Z3 / cvc5 binaries."""
    text = _read(KERNEL_DOCKERFILE)
    assert "libstdc++6" in text, (
        "cds-kernel runtime: must apt-get install libstdc++6 (Z3/cvc5 dynamic linkage)"
    )
    assert "libgomp1" in text, (
        "cds-kernel runtime: must apt-get install libgomp1 (Z3 OpenMP linkage)"
    )


def test_cds_harness_dockerfile_uses_uv() -> None:
    """uv is the canonical Python package manager for the project (ADR pre-Phase-0)."""
    text = _read(HARNESS_DOCKERFILE)
    assert "ghcr.io/astral-sh/uv" in text, "cds-harness: must pin uv via ghcr distroless"
    assert "uv sync" in text, "cds-harness: must invoke `uv sync`"
    assert "--no-dev" in text, "cds-harness: runtime venv must be --no-dev"
    assert "--frozen" in text, "cds-harness: must honour uv.lock with --frozen"


def test_cds_frontend_dockerfile_separates_bun_builder_from_node_runtime() -> None:
    """Bun builds (bun.lock fidelity); node runs (sveltejs/kit#15184 risk)."""
    text = _read(FRONTEND_DOCKERFILE)
    assert "bun install --frozen-lockfile" in text, (
        "cds-frontend builder: must `bun install --frozen-lockfile`"
    )
    assert "bun run build" in text, "cds-frontend builder: must `bun run build`"
    assert 'ENTRYPOINT ["node", "build"]' in text, (
        "cds-frontend runtime: must `ENTRYPOINT [\"node\", \"build\"]` (adapter-node)"
    )


def test_dockerignore_excludes_heavy_paths() -> None:
    """Build context stays trim — target/, node_modules/, .venv/, .git/, .agent/."""
    assert DOCKERIGNORE.is_file(), f"missing {DOCKERIGNORE}"
    text = _read(DOCKERIGNORE)
    for needle in (
        ".git",
        ".agent",
        "target",
        "**/node_modules",
        ".venv",
        ".bin/.dapr",
        ".bin/.hfs",
    ):
        assert needle in text, f".dockerignore must exclude {needle!r}"


def test_dockerignore_does_not_exclude_solver_bins() -> None:
    """`.bin/z3` + `.bin/cvc5` must reach the cds-kernel build context."""
    text = _read(DOCKERIGNORE)
    # No literal `.bin/z3` or `.bin/cvc5` line — they must NOT be in the
    # ignore list. We also reject a blanket `.bin` or `.bin/*` line that
    # would silently exclude them.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert stripped not in {".bin", ".bin/", ".bin/*", ".bin/**"}, (
            f".dockerignore line {stripped!r} would exclude .bin/z3 + .bin/cvc5 "
            "from the cds-kernel build context"
        )
        assert stripped not in {".bin/z3", ".bin/cvc5"}, (
            f".dockerignore line {stripped!r} excludes a solver the cds-kernel image needs"
        )


def test_justfile_registers_cloud_lifecycle_recipes() -> None:
    """The five Task 11.2 recipes + the three image-tag constants land in Justfile."""
    text = _read(JUSTFILE)
    for recipe in ("cloud-build:", "cloud-load:", "cloud-up:", "cloud-down:",
                   "cloud-status:", "cloud-smoke:"):
        assert recipe in text, f"Justfile missing recipe: {recipe}"
    for constant in ("CDS_HARNESS_IMAGE", "CDS_KERNEL_IMAGE", "CDS_FRONTEND_IMAGE",
                     "DOCKER_DIR", "DOCKER"):
        assert constant in text, f"Justfile missing constant: {constant}"


def test_justfile_cloud_build_gates_on_docker_and_solvers() -> None:
    """`cloud-build` exits cleanly with a loud notice when docker / solvers are missing."""
    text = _read(JUSTFILE)
    # Reach into the cloud-build recipe block. We assert the gate strings
    # appear; full bash-parsing is overkill here.
    assert 'command -v "{{DOCKER}}"' in text, (
        "cloud-build must probe $DOCKER before invoking it"
    )
    assert ".bin/z3 + .bin/cvc5 missing" in text, (
        "cloud-build must check for .bin/{z3,cvc5} (cds-kernel image dep)"
    )
