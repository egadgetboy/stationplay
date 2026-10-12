"""The install files (the audit of 1.34.0): stationplay.yaml and
docker-compose.yml start tapiOca without the internet (the image is
fetched only when it isn't there; each install's update steps fetch it);
the Unraid template runs tapiOca as docker-compose.yml does; and the
README's update steps work in PowerShell, say plainly which steps haven't
been confirmed, and tell installs from before 1.34.0 what to set."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
YAML = ROOT / "stationplay.yaml"
TEMPLATE = ROOT / "unraid" / "stationplay.xml"
README = ROOT / "README.md"


def setting(text: str, name: str) -> str | None:
    """A top-level setting of the stationplay service (no comment)."""
    found = re.search(rf"^    {name}:[ \t]*([^#\n]*?)[ \t]*(?:#.*)?$", text, re.M)
    return found.group(1).strip().strip('"') if found else None


def listed(text: str, name: str) -> list[str]:
    """A setting's list (its "- " lines, comments between them aside), as written."""
    found = re.search(rf"^    {name}:\n((?:      (?:- |#).*\n)+)", text, re.M)
    if not found:
        return []
    return [
        line.split("#")[0].strip()[2:].strip().strip('"')
        for line in found.group(1).splitlines()
        if line.strip().startswith("- ")
    ]


def environment(text: str) -> dict[str, str]:
    found = re.search(r"^    environment:\n((?:(?:      .*)?\n)+?)    \w", text, re.M)
    assert found, "the environment"
    pairs = re.findall(r'^      (\w+): "([^"]*)"', found.group(1), re.M)
    return dict(pairs)


def test_starting_never_needs_the_internet():
    for path in (COMPOSE, YAML):
        text = path.read_text()
        assert setting(text, "image") == "ghcr.io/egadgetboy/tapioca-server:latest", path.name
        # (Fetched only when it isn't there: `always` makes every start ask the registry.)
        assert setting(text, "pull_policy") in (None, "missing"), path.name
        assert "pull_policy: always" not in text, path.name


def test_the_unraid_template_runs_stationplay_as_the_compose_file_does():
    compose = COMPOSE.read_text()
    template = ET.parse(TEMPLATE).getroot()
    extra = (template.findtext("ExtraParams") or "").split()

    def has(*words: str) -> bool:
        return any(extra[n : n + len(words)] == list(words) for n in range(len(extra)))

    assert template.findtext("Repository") == setting(compose, "image")
    assert setting(compose, "restart") == "unless-stopped" and has("--restart", "unless-stopped")
    assert setting(compose, "init") == "true" and has("--init")
    for option in listed(compose, "security_opt"):
        assert has("--security-opt", option), option
    for dropped in listed(compose, "cap_drop"):
        assert has("--cap-drop", dropped), dropped
    for name in ("max-size", "max-file"):
        value = re.search(rf'^        {name}: "([^"]+)"', compose, re.M)
        assert value and has("--log-opt", f"{name}={value.group(1)}"), name
    configs = template.findall("Config")
    ports = {c.get("Target") for c in configs if c.get("Type") == "Port"}
    assert ports == {p.split(":")[1] for p in listed(compose, "ports")}
    variables = {c.get("Target"): c.text or c.get("Default") for c in configs
                 if c.get("Type") == "Variable"}  # fmt: skip
    for name, value in environment(compose).items():
        assert name in variables, name
        if name not in ("STATIONPLAY_INSTALL", "PLEX_URL", "PLEX_TOKEN", "TZ"):
            assert variables[name] == value, name
    assert variables["STATIONPLAY_INSTALL"] == "unraid"
    paths = {c.get("Target"): c.get("Mode") for c in configs if c.get("Type") == "Path"}
    for volume in listed(compose, "volumes"):
        inside = volume.split(":")[1]
        assert paths.get(inside) == ("ro" if volume.endswith(":ro") else "rw"), volume


def updating() -> str:
    text = README.read_text()
    return text[
        text.index("\n## Updating\n") : text.index("\n### Switching to the published image\n")
    ]


def switching() -> str:
    text = README.read_text()
    return text[
        text.index("\n### Switching to the published image\n") : text.index("\n### Rolling back\n")
    ]


def test_the_readme_s_update_steps():
    said = updating()
    # PowerShell (Docker Desktop on Windows) hasn't got &&.
    assert "&&" not in said
    assert "`docker compose up -d --pull always`" in said
    assert "`sudo docker compose up -d --pull always`" in said  # (Synology, over SSH)
    rows = {row.split("|")[1].strip(): row for row in said.splitlines() if row.startswith("| ")}
    for install in ("TrueNAS SCALE", "Synology"):
        assert "haven't been confirmed yet" in rows[install], install
    for install in ("Docker Compose", "Docker Desktop", "Unraid", "docker run"):
        assert "confirmed" not in rows[install], install
    # The update check asks first, and says what GitHub sees.
    assert "GitHub sees your server's internet address" in said
    assert "pull_policy: always" not in README.read_text()


def test_installs_from_before_1_34_0_are_told_what_to_set():
    said = switching()
    # Synology and Unraid were installed with Compose before 1.34.0, over
    # SSH on Synology, with sudo.
    assert 'On Synology, set it to `"synology"`' in said
    assert 'On Unraid, set it to `"compose"`' in said
    assert "`sudo docker compose up -d`" in said
    assert "pull_policy: always" not in said
