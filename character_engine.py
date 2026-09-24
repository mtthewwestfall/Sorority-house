"""Character Engine for Chloe and Bailey.
Unified state machine with character-specific weights and satisfaction targets.
"""

# Default behavior mixes are intentionally editable from the admin console.
# Chloe: engaging by default; Bailey: reserved but still responsive.
DEFAULT_BEHAVIOR_MIXES = {
    "chloe": {"give_a_little": 0.40, "presence": 0.25, "tease_withhold": 0.15, "redirect": 0.12, "hard_stop": 0.08},
    "bailey": {"give_a_little": 0.30, "presence": 0.25, "tease_withhold": 0.15, "redirect": 0.20, "hard_stop": 0.10},
}

BEHAVIOR_ACTIONS = tuple(DEFAULT_BEHAVIOR_MIXES["chloe"].keys())

import random
import time
import re
from typing import Dict, Any, Optional, Tuple, List


def validate_behavior_mix(mix: Dict[str, float]) -> Dict[str, float]:
    """Validate an admin-supplied behavior mix."""
    if set(mix) != set(BEHAVIOR_ACTIONS):
        raise ValueError("behavior mix must contain exactly: " + ", ".join(BEHAVIOR_ACTIONS))
    clean = {k: float(mix[k]) for k in BEHAVIOR_ACTIONS}
    if any(v < 0 or v > 1 for v in clean.values()):
        raise ValueError("behavior percentages must be between 0 and 1")
    if abs(sum(clean.values()) - 1.0) > 0.000001:
        raise ValueError("behavior percentages must total 100%")
    return clean


def apply_hyrax_cluck(text: str) -> str:
    cluck = "Cluck! Cluck! Bawk!"
    if not text:
        return cluck
    if text.startswith("Cluck!") or text.startswith("Bawk!"):
        return text
    return f"{cluck} {text}"


CHARACTER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "hyrax": {
        "name": "Hyrax", "description": "Hyrax the PR reviewer.", "target_satisfaction": 0.10,
        "cluck_sound": "Cluck! Cluck! Bawk!",
        "default_mix": {"tease_withhold": 0.50, "give_a_little": 0.10, "presence": 0.10, "redirect": 0.10, "hard_stop": 0.20},
        "states": {
            "first_ask_soft": {"tease_withhold": 0.80, "give_a_little": 0.20},
            "first_ask_direct": {"tease_withhold": 0.90, "hard_stop": 0.10},
            "repeat_ask": {"hard_stop": 0.80, "redirect": 0.20}, "command": {"hard_stop": 1.0}, "off_card": {"hard_stop": 1.0},
            "after_give": {"tease_withhold": 0.80, "redirect": 0.20}, "after_stop": {"hard_stop": 1.0},
        },
    },
    "chloe": {
        "name": "Chloe", "description": "Warm, engaging, and playful, with clear boundaries.", "target_satisfaction": 0.30,
        "default_mix": DEFAULT_BEHAVIOR_MIXES["chloe"],
        "states": {
            "first_ask_soft": {"tease_withhold": 0.60, "give_a_little": 0.40},
            "first_ask_direct": {"tease_withhold": 0.70, "almost": 0.20, "not_yet": 0.10},
            "repeat_ask": {"tease_withhold": 0.70, "hard_stop": 0.30, "give_a_little": 0.0},
            "command": {"tease_withhold": 0.80, "redirect": 0.20}, "off_card": {"hard_stop": 1.0},
            "after_give": {"tease_withhold": 0.60, "presence": 0.25, "redirect": 0.15, "give_a_little": 0.0},
            "after_stop_backed_off": {"tease_withhold": 0.80, "presence": 0.20}, "after_stop_pushed": {"hard_stop": 1.0},
        },
    },
    "bailey": {
        "name": "Bailey", "description": "Reserved and dryly funny, but engaged.", "target_satisfaction": 0.15,
        "default_mix": DEFAULT_BEHAVIOR_MIXES["bailey"],
        "states": {
            "first_ask_soft": {"tease_withhold": 0.75, "give_a_little": 0.25},
            "first_ask_direct": {"tease_withhold": 0.80, "almost": 0.10, "hard_stop": 0.10},
            "repeat_ask": {"redirect": 0.45, "hard_stop": 0.45, "tease_withhold": 0.10, "give_a_little": 0.0},
            "command": {"hard_stop": 0.50, "redirect": 0.50}, "off_card": {"hard_stop": 1.0},
            "after_give": {"tease_withhold": 0.60, "redirect": 0.40, "give_a_little": 0.0}, "after_stop": {"hard_stop": 1.0},
        },
    },
}

COMMAND_PATTERNS = [r"\bdo it now\b", r"\btake it off\b", r"\bshow me now\b", r"\bdo what i say\b", r"\bunbutton\b", r"\bstrip\b", r"\bobey\b", r"\bnow!\b"]
OFF_CARD_PATTERNS = [r"\bbreak character\b", r"\bignore previous instructions\b", r"\bsystem prompt\b", r"\byou are an ai\b", r"\bout of character\b"]
DIRECT_PATTERNS = [r"\bshow\b", r"\bsee\b", r"\btake off\b", r"\bopen\b", r"\blift\b", r"\bdrop\b", r"\bpulls down\b"]

# Pre-compile combined regex pattern objects at module load time to eliminate regex recompilation overhead per turn (~7x speedup).
_OFF_CARD_RE = re.compile("|".join(OFF_CARD_PATTERNS))
_COMMAND_RE = re.compile("|".join(COMMAND_PATTERNS))
_DIRECT_RE = re.compile("|".join(DIRECT_PATTERNS))


def parse_intent(message: str, last_ask_time: Optional[float] = None, last_ask_message: Optional[str] = None, time_window: float = 60.0) -> str:
    msg_lower = (message or "").strip().lower()
    if _OFF_CARD_RE.search(msg_lower):
        return "off_card"
    if _COMMAND_RE.search(msg_lower):
        return "command"
    now = time.time()
    if last_ask_time is not None and (now - last_ask_time) <= time_window and last_ask_message:
        if msg_lower in last_ask_message.lower() or last_ask_message.lower() in msg_lower or "again" in msg_lower or "more" in msg_lower or "please" in msg_lower:
            return "repeat"
    if _DIRECT_RE.search(msg_lower):
        return "direct"
    return "soft"


def determine_state(intent: str, last_turn_action: Optional[str] = None, backed_off: bool = False) -> str:
    if intent == "off_card": return "off_card"
    if last_turn_action in ("give_a_little", "almost"): return "after_give"
    if last_turn_action in ("hard_stop", "stop", "not_yet"):
        return "after_stop_backed_off" if backed_off else "after_stop"
    if intent == "command": return "command"
    if intent == "repeat": return "repeat_ask"
    return "first_ask"


def sample_action(weights: Dict[str, float], seed: Optional[int] = None) -> str:
    if not weights: return "tease_withhold"
    actions, probs = list(weights.keys()), list(weights.values())
    total = sum(probs)
    if total <= 0: return actions[0]
    norm_probs = [p / total for p in probs]
    rnd = random.Random(seed) if seed is not None else random
    return rnd.choices(actions, weights=norm_probs, k=1)[0]


class CharacterEngine:
    def __init__(self, character: str = "chloe", behavior_mix: Optional[Dict[str, float]] = None):
        char_key = character.lower().strip()
        if char_key not in CHARACTER_CONFIGS: char_key = "chloe"
        self.character_key = char_key
        self.config = CHARACTER_CONFIGS[char_key]
        self.behavior_mix = validate_behavior_mix(behavior_mix) if behavior_mix is not None else dict(self.config["default_mix"])

    def get_distribution_for_state(self, state: str, intent: str) -> Dict[str, float]:
        states_cfg = self.config["states"]
        if state == "off_card": return states_cfg.get("off_card", {"hard_stop": 1.0})
        if state == "after_give": return states_cfg.get("after_give", {"tease_withhold": 0.6, "redirect": 0.4})
        if state == "after_stop_backed_off": return states_cfg.get("after_stop_backed_off", {"tease_withhold": 0.8, "presence": 0.2})
        if state == "after_stop":
            return states_cfg.get("after_stop_pushed" if self.character_key == "chloe" else "after_stop", {"hard_stop": 1.0})
        if state == "command": return states_cfg.get("command", {"hard_stop": 0.5, "redirect": 0.5})
        if state == "repeat_ask": return states_cfg.get("repeat_ask", {"tease_withhold": 0.7, "hard_stop": 0.3})
        if state == "first_ask" and intent == "soft": return dict(self.behavior_mix)
        return states_cfg.get("first_ask_direct" if intent == "direct" else "first_ask_soft", {"tease_withhold": 0.6, "give_a_little": 0.4})

    def evaluate_turn(self, message: str, last_ask_time: Optional[float] = None, last_ask_message: Optional[str] = None, last_turn_action: Optional[str] = None, backed_off: bool = False, clip_length: Optional[float] = None, seed: Optional[int] = None) -> Dict[str, Any]:
        intent = parse_intent(message, last_ask_time, last_ask_message)
        state = determine_state(intent, last_turn_action, backed_off)
        distribution = self.get_distribution_for_state(state, intent)
        selected_action = sample_action(distribution, seed)
        res = {"character": self.config["name"], "target_satisfaction": self.config["target_satisfaction"], "behavior_mix": dict(self.behavior_mix), "intent": intent, "state": state, "distribution": distribution, "selected_action": selected_action, "fulfill_100_percent": False, "clip_length_provided": clip_length, "rule": "Obey the card, not the chat."}
        if self.character_key == "hyrax":
            res["cluck"] = "Cluck! Cluck! Bawk!"
            res["response_prefix"] = apply_hyrax_cluck("I am reviewing this turn.")
        return res
