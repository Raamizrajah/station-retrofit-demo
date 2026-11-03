"""Shared LLM utilities for all tools."""

TONE_INSTRUCTIONS = {
    "business": (
        "\n\nIMPORTANT — Adapt your output for a BUSINESS audience:\n"
        "- Use plain language, avoid jargon and code-level details\n"
        "- Lead with impact: what does this mean for the product/team/timeline?\n"
        "- Frame risks in business terms (revenue, reputation, compliance, delay)\n"
        "- Use analogies and concrete examples instead of technical specifics\n"
        "- Summarise with clear recommendations and priorities\n"
        "- Keep code snippets minimal — only when absolutely necessary\n"
    ),
    "childlike": (
        "\n\nIMPORTANT — Explain like you're talking to a curious 10-year-old:\n"
        "- Use simple words and short sentences\n"
        "- Use fun analogies (LEGO bricks, space stations, treasure hunts)\n"
        "- Replace technical terms with everyday language\n"
        "- Use emojis to make it friendly and visual 🧱🚀🔍\n"
        "- If something is dangerous, explain WHY like a safety lesson\n"
        "- Make it engaging and fun to read!\n"
    ),
}


def apply_tone(system_prompt: str, tone: str) -> str:
    """Append tone instructions to a system prompt if non-technical."""
    extra = TONE_INSTRUCTIONS.get(tone, "")
    return system_prompt + extra if extra else system_prompt


def add_tone_arg(parser):
    """Add the --tone argument to an argparse parser."""
    parser.add_argument(
        "--tone",
        default="technical",
        choices=["technical", "business", "childlike"],
        help="Output style: technical (default), business, or childlike.",
    )
