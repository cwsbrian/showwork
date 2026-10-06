#!/usr/bin/env python3
"""Supply Showwork routing context for Claude's UserPromptSubmit event."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("Expected a hook event object")
        if event.get("hook_event_name") != "UserPromptSubmit":
            return 0
        template = (ROOT / "instructions" / "automatic.md").read_text(encoding="utf-8")
        context = template.replace("{{SKILLS_ROOT}}", str(ROOT / "skills"))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": context,
        }}, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        print(f"Showwork automatic routing could not load: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
