"""The install files (the audit of 1.34.0): tapioca-server.yaml and
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
YAML = ROOT / "tapioca-server.yaml"
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
        if name not in ("TAPIOCA_INSTALL", "PLEX_URL", "PLEX_TOKEN", "TZ"):
            assert variables[name] == value, name
    assert variables["TAPIOCA_INSTALL"] == "unraid"
    paths = {c.get("Target"): c.get("Mode") for c in configs if c.get("Type") == "Path"}
    for volume in listed(compose, "volumes"):
        inside = volume.split(":")[1]
        assert paths.get(inside) == ("ro" if volume.endswith(":ro") else "rw"), volume
    # The container's name, as every install's, so the README's `docker logs
    # stationplay` works on Unraid too; and the data folder an Unraid
    # Compose install from before 1.34.0 already uses (the compose file's
    # ./data, in the folder the README gives), so switching to the template
    # never starts an empty server with a new tuner (the audit of 1.34.0).
    assert template.findtext("Name") == setting(compose, "container_name") == "stationplay"
    assert setting(YAML.read_text(), "container_name") == "stationplay"
    assert "./data:/data" in listed(compose, "volumes")
    unraid = README.read_text()
    unraid = unraid[unraid.index("\n### Unraid\n") : unraid.index("\n### Windows and macOS\n")]
    assert "steps in `/mnt/user/appdata/stationplay`" in unraid
    [data] = [c for c in configs if c.get("Target") == "/data"]
    assert data.get("Default") == data.text == "/mnt/user/appdata/stationplay/data"
    assert "/mnt/user/appdata/stationplay/data" in (template.findtext("Requires") or "")
    assert "The data folder is already `/mnt/user/appdata/stationplay/data`" in unraid
    # The Overview still says tapiOca.
    assert "tapiOca" in (template.findtext("Overview") or "")


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


def section(start: str, end: str) -> str:
    text = README.read_text()
    return text[text.index(f"\n{start}\n") : text.index(f"\n{end}\n")]


def test_the_readme_s_rollback_steps_work_in_powershell():
    """Docker Desktop on Windows runs PowerShell, which hasn't got && and
    whose cp and rm don't take -f the same way: the copy and delete have
    PowerShell forms (the audit of 1.34.0)."""
    said = section("### Rolling back", "## Watch your stations")
    assert "&&" not in said
    assert "Copy-Item" in said
    assert "Remove-Item" in said and "-ErrorAction SilentlyContinue" in said
    assert "PowerShell" in said


def test_the_readme_on_building_and_checking_releases():
    """(The audit of 1.34.0.)"""
    building = section("### Building from source", "### Checking a release's signature")
    # Older zips had the old name, and TrueNAS and Synology need sudo.
    assert "`stationplay-<version>.zip`" in building
    assert "sudo docker build" in building
    signing = section("### Checking a release's signature", "### The logo library")
    assert "1.35.0" not in signing and "without one" not in signing
    assert "From 1.34.0 on, every release's zip and its `SHA256SUMS` are signed." in signing
    # The package to make public is the image's.
    assert "the `tapioca-server` package on GitHub must be public" in README.read_text()
    # docker run: the public port only for those who used it.
    switching_ = switching()
    assert "Leave out `-p 3311:3311` and `-e PUBLIC_PORT=3311`" in switching_
    # Older Synology systems have docker-compose, with a hyphen.
    synology = section("### Synology", "### Unraid")
    assert "`docker-compose`" in synology


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
    # The names on the screen: the TrueNAS app and the Synology project
    # are named stationplay, as the install steps say (TrueNAS app names
    # are lowercase only), and so is the container on Unraid's Docker tab.
    assert "open **Apps**, then **stationplay**" in rows["TrueNAS SCALE"]
    assert "choose the stationplay project" in rows["Synology"]
    assert "When **stationplay** shows an update" in rows["Unraid"]
    assert "then tapiOca" not in said and "tapiOca's project" not in said
    assert "open tapiOca in **Apps**" not in said
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
    assert "On TrueNAS, open **Apps**, then **stationplay**, and choose **Edit**." in said
    assert "pull_policy: always" not in said


def test_names_new_in_1_34_0_carry_tapioca_s_name():
    """The install setting and the page's Not now key are new in 1.34.0,
    never released under the old name, so nothing keeps it (the audit of
    1.34.0): the old spellings are gone from every file in the repo."""
    old = ("STATIONPLAY" + "_INSTALL", "stationplay" + ".updateNotNow")
    kinds = {".py", ".js", ".css", ".html", ".md", ".yml", ".yaml", ".xml", ".txt", ".json", ".sh",
             ".toml", ".ini", ""}  # fmt: skip
    found = []
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts
        if any(p in (".git", "__pycache__", "node_modules") for p in parts):
            continue
        if not path.is_file() or path.suffix not in kinds:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found += [f"{path.relative_to(ROOT)}: {name}" for name in old if name in text]
    assert found == []
