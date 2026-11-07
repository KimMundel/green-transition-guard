"""Passive Cisco IOS XR optics status assessment, for offline research.

No device I/O, control commands, state transition counts, or safety authorization.
A CLI status snapshot is a device report, not an authenticated physical ledger.
The documented example is IOS XR 26.3.1 on selected NCS 540/5500 models.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


MAX_INPUT_BYTES = 1_048_576
MAX_FIELD_LENGTH = 256
KNOWN_MODELS = frozenset({
    "NCS-57C3-MOD-SYS",  # NCS 5500 guide
    "N540-24Z8Q2C-SYS",  # NCS 540 guide
    "N540-ACC-SYS", "N540X-ACC-SYS",  # N540(X)-ACC-SYS family
})
SOURCE_NCS_540 = (
    "https://www.cisco.com/c/en/us/td/docs/iosxr/ncs5xx/interfaces/26xx/"
    "b-interfaces-hardware-component-cg-26xx-ncs540/config-controllers.html"
)
SOURCE_NCS_5500 = (
    "https://www.cisco.com/c/en/us/td/docs/iosxr/ncs5500/interfaces/26xx/"
    "configuration/guide/b-interfaces-hardware-component-cg-ncs5500-26xx/"
    "configuring-controllers.html"
)
FIELDS = (
    "Controller State", "Transport Admin State", "Laser State", "Power Mode",
    "PID", "Serial Number",
)


class UnsupportedOpticsObservation(ValueError):
    """The caller-supplied status excerpt cannot be interpreted consistently."""


@dataclass(frozen=True)
class OpticsObservation:
    device_id: str
    energy_object_id: str
    location: str
    platform_model: str
    software_release: str
    sample_sequence: int
    part_id: str
    serial: str
    controller_state: str
    transport_admin_state: str
    laser_state: str
    power_mode: str
    reported_mode: str  # 'high', 'low', or 'ambiguous'; never physical proof
    matches_documented_platform_release: bool


@dataclass(frozen=True)
class OpticsAssessment:
    reason: str
    reported_mode_changed: bool | None
    quarantine: bool = True
    safe_to_dispatch: bool = False
    proven_physical_edges: int | None = None

    def __post_init__(self) -> None:
        if not self.quarantine or self.safe_to_dispatch or self.proven_physical_edges is not None:
            raise ValueError("offline snapshots must never authorize a physical operation")


def _identity(value: str, name: str) -> str:
    if (not isinstance(value, str) or not value or value.strip() != value or
            len(value) > MAX_FIELD_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(f"invalid {name}")
    return value


def _exact_field(lines: list[str], field: str) -> str:
    # A single-field match prevents a duplicate or a second pasted device
    # output from silently replacing the first reading.
    pattern = re.compile(r"^[ \t]*" + re.escape(field) + r"[ \t]*:[ \t]*(.*?)[ \t]*$")
    found = [m.group(1).strip() for line in lines if (m := pattern.fullmatch(line))]
    if len(found) != 1 or not found[0] or len(found[0]) > MAX_FIELD_LENGTH:
        raise UnsupportedOpticsObservation(f"missing, duplicate or oversized {field}")
    return found[0]


def _reported_mode(fields: dict[str, str]) -> str:
    observed = (
        fields["Controller State"], fields["Transport Admin State"],
        fields["Laser State"], fields["Power Mode"],
    )
    if observed == ("Up", "In Service", "On", "High"):
        return "high"
    if observed == ("Administratively Down", "Out Of Service", "Off", "Low"):
        return "low"
    return "ambiguous"


def parse_cisco_optics_status(
    raw: str, *, device_id: str, energy_object_id: str,
    location: str, platform_model: str, software_release: str,
    sample_sequence: int,
) -> OpticsObservation:
    """Parse *one* saved `show controllers optics R/S/I/P` text excerpt.

    Device IDs, platform/version labels and the CLI text are caller assertions;
    their consistency alone never makes an observation trustworthy. This
    function has no network, CLI, file-writing, or actuator capability.
    """
    for name, value in (
        ("device_id", device_id), ("energy_object_id", energy_object_id),
        ("location", location), ("platform_model", platform_model),
        ("software_release", software_release),
    ):
        _identity(value, name)
    if type(sample_sequence) is not int or sample_sequence < 0:
        raise ValueError("invalid sample_sequence")
    if re.fullmatch(r"[0-9]+/[0-9]+/[0-9]+/[0-9]+", location) is None:
        raise ValueError("invalid optics location")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", software_release):
        raise ValueError("invalid software release")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        raise UnsupportedOpticsObservation("optics output must be bounded UTF-8 text")
    lines = raw.splitlines()
    command = re.compile(r"\bshow controllers optics ([0-9]+/[0-9]+/[0-9]+/[0-9]+)\b")
    command_locations = [m.group(1) for line in lines if (m := command.search(line))]
    if len(command_locations) != 1 or command_locations[0] != location:
        raise UnsupportedOpticsObservation("missing, conflicting or duplicate optics command location")
    fields = {name: _exact_field(lines, name) for name in FIELDS}
    return OpticsObservation(
        device_id=device_id, energy_object_id=energy_object_id,
        location=location, platform_model=platform_model,
        software_release=software_release, sample_sequence=sample_sequence,
        part_id=_identity(fields["PID"], "PID"),
        serial=_identity(fields["Serial Number"], "Serial Number"),
        controller_state=fields["Controller State"],
        transport_admin_state=fields["Transport Admin State"],
        laser_state=fields["Laser State"], power_mode=fields["Power Mode"],
        reported_mode=_reported_mode(fields),
        matches_documented_platform_release=(
            platform_model in KNOWN_MODELS and software_release == "26.3.1"
        ),
    )


def assess_cisco_optics_pair(
    previous: OpticsObservation, current: OpticsObservation,
) -> OpticsAssessment:
    """Compare two snapshots without inferring a physical transition count.

    A status change is evidence of changed *reports*. Identical end states
    may conceal an arbitrary number of intermediate laser/power cycles.
    Quarantine remains mandatory for every outcome.
    """
    if not isinstance(previous, OpticsObservation) or not isinstance(current, OpticsObservation):
        raise TypeError("OpticsObservation values required")
    if (
        previous.device_id != current.device_id or
        previous.energy_object_id != current.energy_object_id or
        previous.location != current.location or
        previous.part_id != current.part_id or
        previous.serial != current.serial or
        previous.platform_model != current.platform_model or
        previous.software_release != current.software_release
    ):
        return OpticsAssessment("source-or-component-mismatch", None)
    if current.sample_sequence <= previous.sample_sequence:
        return OpticsAssessment("stale-or-repeated-sample", None)
    if previous.reported_mode == "ambiguous" or current.reported_mode == "ambiguous":
        return OpticsAssessment("unknown-or-conflicting-status", None)
    if not previous.matches_documented_platform_release or not current.matches_documented_platform_release:
        return OpticsAssessment("platform-or-release-not-verified", None)
    changed = previous.reported_mode != current.reported_mode
    return OpticsAssessment(
        "reported-state-change-without-edge-proof" if changed else
        "same-reported-state-may-hide-cycles",
        changed,
    )
