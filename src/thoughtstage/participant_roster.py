"""Deterministic participant aliases for the researcher experiment builder."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from thoughtstage.models import StrictModel

ParticipantNamingTheme = Literal[
    "neutral",
    "trees",
    "mountains",
    "animals",
    "rivers",
    "constellations",
]

ROSTER_GENERATOR_VERSION = "alias-v1"
MAX_GENERATED_PARTICIPANTS = 32

THEME_ALIASES: dict[ParticipantNamingTheme, tuple[str, ...]] = {
    "neutral": tuple(f"Participant {number:02d}" for number in range(1, 33)),
    "trees": (
        "Acacia",
        "Alder",
        "Aspen",
        "Beech",
        "Birch",
        "Cedar",
        "Cypress",
        "Elm",
        "Fir",
        "Hawthorn",
        "Hemlock",
        "Hickory",
        "Juniper",
        "Larch",
        "Linden",
        "Magnolia",
        "Maple",
        "Oak",
        "Olive",
        "Palm",
        "Pine",
        "Poplar",
        "Redwood",
        "Rowan",
        "Sequoia",
        "Spruce",
        "Sycamore",
        "Tamarack",
        "Teak",
        "Walnut",
        "Willow",
        "Yew",
    ),
    "mountains": (
        "Aconcagua",
        "Annapurna",
        "Ararat",
        "Baker",
        "Chimborazo",
        "Cotopaxi",
        "Denali",
        "Elbert",
        "Elbrus",
        "Etna",
        "Everest",
        "Fuji",
        "Grays",
        "Hood",
        "Kilimanjaro",
        "Kosciuszko",
        "Logan",
        "Lhotse",
        "Makalu",
        "Manaslu",
        "Matterhorn",
        "Nanga",
        "Olympus",
        "Puncak",
        "Rainier",
        "Robson",
        "Shasta",
        "Sneffels",
        "Toubkal",
        "Vinson",
        "Whitney",
        "Cook",
    ),
    "animals": (
        "Badger",
        "Bison",
        "Caribou",
        "Crane",
        "Dolphin",
        "Eagle",
        "Falcon",
        "Fox",
        "Gazelle",
        "Gecko",
        "Heron",
        "Ibex",
        "Jaguar",
        "Koala",
        "Lemur",
        "Lynx",
        "Marmot",
        "Narwhal",
        "Orca",
        "Otter",
        "Panda",
        "Puma",
        "Quail",
        "Raven",
        "Seal",
        "Tern",
        "Urial",
        "Viper",
        "Wolf",
        "Wren",
        "Yak",
        "Zebra",
    ),
    "rivers": (
        "Amazon",
        "Amur",
        "Colorado",
        "Columbia",
        "Congo",
        "Danube",
        "Euphrates",
        "Fraser",
        "Ganges",
        "Indus",
        "Loire",
        "Mackenzie",
        "Mekong",
        "Mississippi",
        "Missouri",
        "Murray",
        "Niger",
        "Nile",
        "Orinoco",
        "Parana",
        "Po",
        "Rhine",
        "Seine",
        "Senegal",
        "Tagus",
        "Thames",
        "Tigris",
        "Vistula",
        "Volga",
        "Yangtze",
        "Yukon",
        "Zambezi",
    ),
    "constellations": (
        "Andromeda",
        "Aquila",
        "Aries",
        "Auriga",
        "Bootes",
        "Cassiopeia",
        "Centaurus",
        "Cepheus",
        "Cetus",
        "Columba",
        "Corvus",
        "Cygnus",
        "Delphinus",
        "Draco",
        "Eridanus",
        "Gemini",
        "Hercules",
        "Hydra",
        "Lacerta",
        "Leo",
        "Libra",
        "Lyra",
        "Orion",
        "Pegasus",
        "Perseus",
        "Phoenix",
        "Pisces",
        "Scorpius",
        "Taurus",
        "Ursa",
        "Vela",
        "Virgo",
    ),
}


class ParticipantRosterRequest(StrictModel):
    """A reproducible request for display-name suggestions."""

    count: int = Field(ge=1, le=MAX_GENERATED_PARTICIPANTS)
    theme: ParticipantNamingTheme = "neutral"
    seed: int = 42


class ParticipantAlias(StrictModel):
    """One explicit participant identity suggested to the builder."""

    id: str
    display_name: str


class ParticipantRoster(StrictModel):
    """A deterministic, versioned roster suggestion."""

    generator_version: str
    theme: ParticipantNamingTheme
    seed: int
    participants: tuple[ParticipantAlias, ...]


def _rank(theme: ParticipantNamingTheme, seed: int, alias: str) -> bytes:
    payload = f"{ROSTER_GENERATOR_VERSION}\0{theme}\0{seed}\0{alias}".encode()
    return hashlib.sha256(payload).digest()


def generate_participant_roster(request: ParticipantRosterRequest) -> ParticipantRoster:
    """Return stable aliases; the caller must persist the selected names explicitly."""

    aliases = THEME_ALIASES[request.theme]
    if request.theme != "neutral":
        aliases = tuple(
            sorted(aliases, key=lambda alias: _rank(request.theme, request.seed, alias))
        )
    participants = tuple(
        ParticipantAlias(id=f"agent-{index}", display_name=alias)
        for index, alias in enumerate(aliases[: request.count], start=1)
    )
    return ParticipantRoster(
        generator_version=ROSTER_GENERATOR_VERSION,
        theme=request.theme,
        seed=request.seed,
        participants=participants,
    )
