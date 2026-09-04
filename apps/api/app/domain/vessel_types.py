"""AIS numeric code lookups: ship type, navigational status, and cargo hazard.

Codes come from **ITU-R M.1371** (the AIS message specification), which is what
the NAIS/MarineCadastre "see NAIS specifications" note in the data dictionary
refers to. Nothing here is invented: an unrecognized code renders as
``"Unknown (code 37)"`` rather than being guessed into a plausible category
(SOUL.md §6).

The raw numeric value is always preserved alongside the label so a user can see
exactly what the vessel broadcast.
"""

from __future__ import annotations

from typing import Final, NamedTuple

# ---------------------------------------------------------------------------
# Ship type (ITU-R M.1371 Table 53)
# ---------------------------------------------------------------------------
# Ship type is a two-digit code. The first digit selects a broad family; for
# families 2/4/6/7/8/9 the second digit carries cargo/hazard detail rather than
# a different kind of vessel. Codes 30-39 are individually assigned instead.

_SPECIFIC_TYPES: Final[dict[int, str]] = {
    0: "Not available",
    30: "Fishing",
    31: "Towing",
    32: "Towing (large)",
    33: "Dredging or underwater operations",
    34: "Diving operations",
    35: "Military operations",
    36: "Sailing",
    37: "Pleasure craft",
    50: "Pilot vessel",
    51: "Search and rescue",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution equipment",
    55: "Law enforcement",
    56: "Local vessel",
    57: "Local vessel",
    58: "Medical transport",
    59: "Non-combatant ship",
}

_FAMILIES: Final[dict[int, str]] = {
    2: "Wing in ground",
    4: "High-speed craft",
    6: "Passenger",
    7: "Cargo",
    8: "Tanker",
    9: "Other",
}

# Second digit for the families above (ITU-R M.1371 Table 54).
_HAZARD_SUFFIX: Final[dict[int, str]] = {
    1: "hazardous category A",
    2: "hazardous category B",
    3: "hazardous category C",
    4: "hazardous category D",
}


class VesselTypeInfo(NamedTuple):
    """A resolved ship-type code."""

    code: int | None
    label: str
    family: str
    """Coarse grouping used for map colouring and analytics buckets."""

    is_known: bool


UNKNOWN_FAMILY: Final = "Unknown"


def describe_vessel_type(code: int | None) -> VesselTypeInfo:
    """Resolve an AIS ship-type code to a human label and a coarse family.

    ``None`` means the vessel did not broadcast a type, which is different from
    broadcasting an unrecognized one — both are surfaced honestly.
    """
    if code is None:
        return VesselTypeInfo(None, "Not reported", UNKNOWN_FAMILY, is_known=False)

    if code in _SPECIFIC_TYPES:
        label = _SPECIFIC_TYPES[code]
        family = label if code != 0 else UNKNOWN_FAMILY
        return VesselTypeInfo(code, label, family, is_known=code != 0)

    if 0 <= code <= 99:
        first, second = divmod(code, 10)
        family_of_code = _FAMILIES.get(first)
        if family_of_code is not None:
            suffix = _HAZARD_SUFFIX.get(second)
            label = f"{family_of_code} ({suffix})" if suffix else family_of_code
            return VesselTypeInfo(code, label, family_of_code, is_known=True)

    return VesselTypeInfo(code, f"Unknown (code {code})", UNKNOWN_FAMILY, is_known=False)


def vessel_type_family(code: int | None) -> str:
    """Coarse family for a ship-type code — the analytics/map grouping key."""
    return describe_vessel_type(code).family


#: Stable order for charts and legends, so a family keeps its colour between
#: renders. "Other"/"Unknown" deliberately sort last.
VESSEL_TYPE_FAMILY_ORDER: Final[tuple[str, ...]] = (
    "Cargo",
    "Tanker",
    "Passenger",
    "Fishing",
    "Tug",
    "Towing",
    "Towing (large)",
    "Pleasure craft",
    "Sailing",
    "High-speed craft",
    "Pilot vessel",
    "Search and rescue",
    "Law enforcement",
    "Military operations",
    "Dredging or underwater operations",
    "Diving operations",
    "Port tender",
    "Anti-pollution equipment",
    "Medical transport",
    "Non-combatant ship",
    "Local vessel",
    "Wing in ground",
    "Other",
    UNKNOWN_FAMILY,
)

# ---------------------------------------------------------------------------
# Navigational status (ITU-R M.1371 Table 45)
# ---------------------------------------------------------------------------
# Note code 0. The MarineCadastre data dictionary states a domain of 1-14, but
# the standard defines 0 as "under way using engine" and it is present in the
# source data. See docs/data/AIS_SOURCE_REFERENCE.md.

_NAV_STATUS: Final[dict[int, str]] = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    9: "Reserved (high-speed craft)",
    10: "Reserved (wing in ground)",
    11: "Power-driven vessel towing astern",
    12: "Power-driven vessel pushing ahead or towing alongside",
    13: "Reserved",
    14: "AIS-SART, MOB-AIS or EPIRB-AIS active",
    15: "Undefined",
}


def describe_nav_status(code: int | None) -> str:
    """Human label for an AIS navigational status code."""
    if code is None:
        return "Not reported"
    return _NAV_STATUS.get(code, f"Unknown (code {code})")


def nav_status_codes() -> dict[int, str]:
    """Full status lookup, for API reference endpoints and UI filter menus."""
    return dict(_NAV_STATUS)


def is_stationary_status(code: int | None) -> bool:
    """Whether a status indicates the vessel is not making way.

    Used only as a supporting signal by the loitering heuristic, never on its
    own: status is self-reported and frequently stale (SOUL.md §8 — heuristic
    signals are labelled as such).
    """
    return code in {1, 5, 6}
