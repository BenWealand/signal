from __future__ import annotations


def generate_summary(consensus_claims: list[dict[str, object]]) -> str:
    supported = [claim for claim in consensus_claims if claim["status"] == "supported"]
    disputed = [claim for claim in consensus_claims if claim["status"] in {"disputed", "uncertain"}]
    unique = [claim for claim in consensus_claims if claim["status"] == "unique"]

    parts = []
    if supported:
        lead = supported[0]
        parts.append(
            f"Multiple sources report that {str(lead['claim_text']).rstrip('.').lower()}."
        )
    if len(supported) > 1:
        parts.append(
            "Additional overlapping reporting says "
            + "; ".join(str(claim["claim_text"]).rstrip(".").lower() for claim in supported[1:3])
            + "."
        )
    if disputed:
        parts.append("Some claims remain uncertain and should be labeled before publication.")
    if unique:
        parts.append(f"{len(unique)} claim is currently single-source and should be treated as provisional.")
    return " ".join(parts) or "No supported claims are available yet."

