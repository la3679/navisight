"""A deterministic provider that calls no network and needs no key.

It exists for three reasons, in order of importance:

1. **The agent's behaviour has to be assertable.** A test that runs against a
   real model asserts that the model behaved, not that NaviSight did. Against
   this provider, the loop, the tool validation, the bounds, the evidence
   record, and the error paths are all exactly reproducible.
2. Development and demos work offline, with no key and no spend.
3. It is the honest default. With no provider configured the copilot reports
   "not configured"; with this one it says plainly that a deterministic stub is
   answering, so nobody mistakes it for a model.

It is a **stub, not a small model**. It matches keywords, calls the obvious
tool, and reports what came back. It never paraphrases, never interprets, and
never produces a number the tools did not.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.provider import Completion, Message, ToolCall

NAME = "mock"


def _last_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _already_called(messages: list[Message]) -> set[str]:
    return {
        call.name
        for message in messages
        if message.role == "assistant"
        for call in message.tool_calls
    }


def _tool_results(messages: list[Message]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for message in messages:
        if message.role != "tool":
            continue
        try:
            results.append(json.loads(message.content))
        except json.JSONDecodeError:
            results.append({"raw": message.content})
    return results


#: Question shape -> the tool that answers it. Order matters: the first match
#: wins, so more specific patterns come first.
ROUTES: tuple[tuple[re.Pattern[str], str, dict[str, Any]], ...] = (
    (re.compile(r"\b(\d{9})\b"), "get_vessel_details", {}),
    (re.compile(r"\btrack|route|path|voyage\b", re.I), "get_vessel_track_summary", {}),
    (re.compile(r"\bnear|around|within .* of\b", re.I), "find_vessels_near_location", {}),
    (re.compile(r"\bport\b", re.I), "find_ports", {}),
    (re.compile(r"\bbusiest|most active|most frequent\b", re.I), "get_most_active_vessels", {}),
    (re.compile(r"\bspeed|moving|stationary|moored\b", re.I), "get_speed_distribution", {}),
    (
        re.compile(r"\btype|cargo|tanker|composition|fleet\b", re.I),
        "get_vessel_type_distribution",
        {},
    ),
    (re.compile(r"\btraffic|busy|hour|over time|per hour\b", re.I), "get_traffic_summary", {}),
)


class MockProvider:
    """A scripted provider. See the module docstring for why it exists."""

    name = NAME

    def __init__(self, model: str = "deterministic-stub") -> None:
        self.model = model

    async def complete(self, messages: list[Message], *, tools: list[dict[str, Any]]) -> Completion:
        available = {tool["name"] for tool in tools}
        question = _last_user_text(messages)
        called = _already_called(messages)

        # Step 1: always establish what the archive actually holds. Answering
        # anything about "the data" without knowing its window is the mistake
        # this provider exists to make impossible to ship.
        if "get_dataset_overview" not in called and "get_dataset_overview" in available:
            return Completion(
                content="",
                tool_calls=(ToolCall(id="call-1", name="get_dataset_overview", arguments={}),),
            )

        # Step 2: one topical tool, chosen by keyword.
        for pattern, name, extra in ROUTES:
            if name in called or name not in available:
                continue
            match = pattern.search(question)
            if not match:
                continue
            arguments = dict(extra)
            if name in {"get_vessel_details", "get_vessel_track_summary"}:
                digits = re.search(r"\b\d{9}\b", question)
                if digits is None:
                    # No MMSI in the question: find the vessel by name first.
                    if "find_vessel" in called or "find_vessel" not in available:
                        continue
                    return Completion(
                        content="",
                        tool_calls=(
                            ToolCall(
                                id="call-find",
                                name="find_vessel",
                                arguments={"query": question[:64]},
                            ),
                        ),
                    )
                arguments["mmsi"] = digits.group(0)
            if name == "find_vessels_near_location":
                coordinates = re.findall(r"-?\d+\.\d+", question)
                if len(coordinates) < 2:
                    continue
                arguments["longitude"] = float(coordinates[0])
                arguments["latitude"] = float(coordinates[1])
            return Completion(
                content="",
                tool_calls=(ToolCall(id=f"call-{name}", name=name, arguments=arguments),),
            )

        # Step 3: report what the tools returned. No paraphrase, no arithmetic.
        results = _tool_results(messages)
        overview = next((r for r in results if "positionReports" in r), None)
        lines: list[str] = []
        if overview:
            lines.append(
                f"The archive holds {overview['positionReports']:,} position reports from "
                f"{overview['distinctVessels']:,} distinct vessels, covering "
                f"{overview['coverageStart']} to {overview['coverageEnd']}."
            )
        for result in results:
            if result is overview:
                continue
            lines.append(_describe(result))

        lines.append(
            "This answer was produced by NaviSight's deterministic offline provider, "
            "which reports tool results verbatim and does not reason about them. "
            "Configure an LLM provider for a real analysis."
        )
        payload = {
            "answer": " ".join(line for line in lines if line),
            "claims": [{"text": line, "kind": "observed"} for line in lines[:-1] if line],
            "limitations": (
                "The deterministic provider selects one tool by keyword and reports its "
                "result. It does not combine evidence or answer multi-step questions."
            ),
        }
        return Completion(content=json.dumps(payload))


def _describe(result: dict[str, Any]) -> str:
    """One sentence per tool result, using only values the tool returned."""
    if "matchCount" in result:
        names = ", ".join(
            f"{match['name'] or match['mmsi']} (MMSI {match['mmsi']})"
            for match in result.get("matches", [])[:5]
        )
        return (
            f"Vessel search returned {result['matchCount']} match(es): {names}."
            if result["matchCount"]
            else "Vessel search returned no matches in the archive."
        )
    if "vessel" in result and "latestObservation" in result:
        vessel = result["vessel"]
        latest = result["latestObservation"]
        return (
            f"{vessel['name'] or vessel['mmsi']} ({vessel['vesselType']}) was last observed "
            f"at {latest['timestamp']} at {latest['latitude']}, {latest['longitude']}, "
            f"reporting {latest['speedOverGroundKnots']} knots."
        )
    if "observationCount" in result and "boundingBox" in result:
        box = result["boundingBox"]
        return (
            f"MMSI {result['mmsi']} has {result['observationCount']:,} observations between "
            f"{result['firstObservationAt']} and {result['lastObservationAt']}, within "
            f"{box['south']}..{box['north']} latitude and {box['west']}..{box['east']} longitude."
        )
    if "vesselCount" in result:
        return (
            f"{result['vesselCount']} vessel(s) had their latest observation within "
            f"{result['radiusKm']} km of {result['centre']['latitude']}, "
            f"{result['centre']['longitude']}."
        )
    if "totalObservations" in result and "buckets" in result:
        busiest = max(result["buckets"], key=lambda b: b["observations"], default=None)
        if busiest is None:
            return "The traffic summary returned no buckets."
        return (
            f"Across {len(result['buckets'])} {result['interval']} buckets the busiest was "
            f"{busiest['bucket']} with {busiest['observations']:,} position reports."
        )
    if "categories" in result:
        top = result["categories"][0] if result["categories"] else None
        return (
            f"The largest category is {top['label']} with {top['count']:,} of "
            f"{result['total']:,} ({result['basis']})."
            if top
            else "The distribution returned no categories."
        )
    if "buckets" in result and "total" in result:
        top = max(result["buckets"], key=lambda b: b["count"], default=None)
        return (
            f"The largest speed band is '{top['label']}' with {top['count']:,} of "
            f"{result['total']:,} observations."
            if top
            else "The speed distribution returned no buckets."
        )
    if "vessels" in result and result.get("vessels") and "observations" in result["vessels"][0]:
        top = result["vessels"][0]
        return (
            f"The most frequently reporting vessel is {top['name'] or top['mmsi']} with "
            f"{top['observations']:,} observations."
        )
    if "ports" in result:
        return (
            f"The port gazetteer returned {len(result['ports'])} port(s)."
            if result["ports"]
            else "No ports matched in the loaded gazetteer."
        )
    return "A tool returned a result with no summary rule in the deterministic provider."
