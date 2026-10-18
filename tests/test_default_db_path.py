"""Default database path resolution, shared by the CLI and the MCP server.

The MCP server reads its path at import time, and the federation layer
spawns `health-memex mcp` from an arbitrary cwd, so each case runs in a
fresh subprocess with a controlled environment and working directory.
"""

import os
import subprocess
import sys

import pytest

PROBE = (
    "import health_memex.cli as c, health_memex.mcp.server as s; "
    "print(c.DEFAULT_DB); print(s.DB_PATH)"
)


def _resolve(tmp_path, **env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in ("HEALTH_MEMEX_DB", "XDG_DATA_HOME")}
    env.update(env_overrides)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    out = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return {"cli": out[0], "mcp": out[1]}


@pytest.fixture(autouse=True)
def _needs_mcp():
    pytest.importorskip("mcp")


def test_mcp_server_defaults_to_xdg_not_cwd(tmp_path):
    """Regression: the server fell back to ./health_memex.db, so a federation
    spawn silently created an empty DB in whatever directory it ran from."""
    paths = _resolve(tmp_path, XDG_DATA_HOME=str(tmp_path / "xdg"))
    expected = str(tmp_path / "xdg" / "health-memex" / "health_memex.db")
    assert paths == {"cli": expected, "mcp": expected}


def test_env_var_overrides_default_everywhere(tmp_path):
    db = str(tmp_path / "chosen.db")
    paths = _resolve(tmp_path, XDG_DATA_HOME=str(tmp_path / "xdg"), HEALTH_MEMEX_DB=db)
    assert paths == {"cli": db, "mcp": db}
