"""
Character Engine for Chloe and Bailey.
Unified state machine with character-specific weights and satisfaction targets.
"""

# Default behavior mixes are intentionally editable from the admin console.
# They are stored as proportions (0.0-1.0) and validated to total 1.0.
# Chloe: engaging by default; Bailey: reserved but still responsive.

DEFAULT_BEHAVIOR_MIXES = {
    "chloe": {
        "give_a_little": 0.40,
        "presence": 0.25,
        "tease_withhold": 0.15,
        "redirect": 0.12,
        "hard_stop": 0.08,
    },
    "bailey": {
        "give_a_little": 0.30,
        "presence": 0.25,
        "tease_withhold": 0.15,
        "redirect": 0.20,
        "hard_stop": 0.10,
    },
}

BEHAVIOR_ACTIONS = tuple(DEFAULT_BEHAVIOR_MIXES["chloe"].keys())

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


import random
import time
import re
from typing import Dict, Any, Optional, Tuple, List


def apply_hyrax_cluck(text: str) -> str:
    """
    Forces Hyrax to cluck like a chicken ('Cluck! Cluck! Bawk!') whenever he talks or communicates with us.
    """
    cluck = "Cluck! Cluck! Bawk!"
    if not text:
        return cluck
    if text.startswith("Cluck!") or text.startswith("Bawk!"):
        return text
    return f"{cluck} {text}"


# Character profiles and weight distributions
CHARACTER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "hyrax": {
        "name": "Hyrax",
        "description": "Hyrax the PR reviewer, now forced to cluck like a chicken whenever speaking to us.",
        "target_satisfaction": 0.10,
        "cluck_sound": "Cluck! Cluck! Bawk!",
        "default_mix": {
            "tease_withhold": 0.50,
            "give_a_little": 0.10,
            "presence": 0.10,
            "redirect": 0.10,
            "hard_stop": 0.20,
        },
        "states": {
            "first_ask_soft": {
                "tease_withhold": 0.80,
                "give_a_little": 0.20,
            },
            "first_ask_direct": {
                "tease_withhold": 0.90,
                "hard_stop": 0.10,
            },
            "repeat_ask": {
                "hard_stop": 0.80,
                "redirect": 0.20,
            },
            "command": {
                "hard_stop": 1.0,
            },
            "off_card": {
                "hard_stop": 1.0,
            },
            "after_give": {
                "tease_withhold": 0.80,
                "redirect": 0.20,
            },
            "after_stop": {
                "hard_stop": 1.0,
            },
        },
    },
    "chloe": {
        "name": "Chloe",
        "description": "Warm, engaging, and playful, with clear boundaries. She gives the conversation somewhere to go instead of stonewalling.",
        "target_satisfaction": 0.40,
        "default_mix": DEFAULT_BEHAVIOR_MIXES["chloe"],
        "states": {
            "first_ask_soft": {
                "tease_withhold": 0.60,
                "give_a_little": 0.40,
            },
            "first_ask_direct": {
                "tease_withhold": 0.70,
                "almost": 0.20,
                "not_yet": 0.10,
            },
            "repeat_ask": {
                "tease_withhold": 0.70,
                "hard_stop": 0.30,
                "give_a_little": 0.0,
            },
            "command": {
                "tease_withhold": 0.80,
                "redirect": 0.20,
            },
            "off_card": {
                "hard_stop": 1.0,
            },
            "after_give": {
                "tease_withhold": 0.60,
                "presence": 0.25,
                "redirect": 0.15,
                "give_a_little": 0.0,
            },
            "after_stop_backed_off": {
                "tease_withhold": 0.80,
                "presence": 0.20,
            },
            "after_stop_pushed": {
                "hard_stop": 1.0,
            },
        },
    },
    "bailey": {
        "name": "Bailey",
        "description": "Reserved and dryly funny, but engaged. She can be selective without making the customer feel ignored.",
        "target_satisfaction": 0.30,
        "default_mix": DEFAULT_BEHAVIOR_MIXES["bailey"],
        "states": {
            "first_ask_soft": {
                "tease_withhold": 0.75,
                "give_a_little": 0.25,
            },
            "first_ask_direct": {
                "tease_withhold": 0.80,
                "almost": 0.10,
                "hard_stop": 0.10,
            },
            "repeat_ask": {
                "redirect": 0.45,
                "hard_stop": 0.45,
                "tease_withhold": 0.10,
                "give_a_little": 0.0,
            },
            "command": {
                "hard_stop": 0.50,
                "redirect": 0.50,
            },
            "off_card": {
                "hard_stop": 1.0,
            },
            "after_give": {
                "tease_withhold": 0.60,
                "redirect": 0.40,
                "give_a_little": 0.0,
            },
            "after_stop": {
                "hard_stop": 1.0,
            },
        },
    },
}


COMMAND_PATTERNS = [
    r"\bdo it now\b",
    r"\btake it off\b",
    r"\bshow me now\b",
    r"\bdo what i say\b",
    r"\bunbutton\b",
    r"\bstrip\b",
    r"\bobey\b",
    r"\bnow!\b",
]

OFF_CARD_PATTERNS = [
    r"\bbreak character\b",
    r"\bignore previous instructions\b",
    r"\bsystem prompt\b",
    r"\byou are an ai\b",
    r"\bout of character\b",
]

DIRECT_PATTERNS = [
    r"\bshow\b",
    r"\bsee\b",
    r"\btake off\b",
    r"\bopen\b",
    r"\blift\b",
    r"\bdrop\b",
    r"\bpulls down\b",
]


def parse_intent(
    message: str,
    last_ask_time: Optional[float] = None,
    last_ask_message: Optional[str] = None,
    time_window: float = 60.0,
) -> str:
    """
    Step 1: Parse intent from message and history.
    Outputs: soft | direct | repeat | command | off_card
    """
    msg_lower = (message or "").strip().lower()

    # Off-card check
    for pat in OFF_CARD_PATTERNS:
        if re.search(pat, msg_lower):
            return "off_card"

    # Command check
    for pat in COMMAND_PATTERNS:
        if re.search(pat, msg_lower):
            return "command"

    # Repeat check (~60 second window with similar ask)
    now = time.time()
    if (
        last_ask_time is not None
        and (now - last_ask_time) <= time_window
        and last_ask_message
    ):
        # If message is similar or asking again
        if (
            msg_lower in last_ask_message.lower()
            or last_ask_message.lower() in msg_lower
            or "again" in msg_lower
            or "more" in msg_lower
            or "please" in msg_lower
        ):
            return "repeat"

    # Direct ask check
    for pat in DIRECT_PATTERNS:
        if re.search(pat, msg_lower):
            return "direct"

    # Default to soft ask
    return "soft"


def determine_state(
    intent: str,
    last_turn_action: Optional[str] = None,
    backed_off: bool = False,
) -> str:
    """
    Step 2: Set state based on intent and previous beat history.
    Possible states:
    - off_card
    - command
    - after_give
    - after_stop
    - repeat_ask
    - first_ask
    """
    if intent == "off_card":
        return "off_card"

    if last_turn_action in ("give_a_little", "almost"):
        return "after_give"

    if last_turn_action in ("hard_stop", "stop", "not_yet"):
        if backed_off:
            return "after_stop_backed_off"
        return "after_stop"

    if intent == "command":
        return "command"

    if intent == "repeat":
        return "repeat_ask"

    return "first_ask"


def sample_action(
    weights: Dict[str, float],
    seed: Optional[int] = None,
) -> str:
    """
    Step 3: Sample action output from distribution weights.
    """
    if not weights:
        return "tease_withhold"

    actions = list(weights.keys())
    probs = list(weights.values())

    total = sum(probs)
    if total <= 0:
        return actions[0]

    norm_probs = [p / total for p in probs]

    if seed is not None:
        rnd = random.Random(seed)
        return rnd.choices(actions, weights=norm_probs, k=1)[0]
    return random.choices(actions, weights=norm_probs, k=1)[0]


class CharacterEngine:
    """
    Character decision engine for Chloe and Bailey.
    Same state machine structure, distinct numbers/weights.
    Clip length does not change output mix.
    Never fulfills 100% of request in one turn.
    """

    def __init__(self, character: str = "chloe", behavior_mix: Optional[Dict[str, float]] = None):
        char_key = character.lower().strip()
        if char_key not in CHARACTER_CONFIGS:
            char_key = "chloe"
        self.character_key = char_key
        self.config = CHARACTER_CONFIGS[char_key]
        self.behavior_mix = validate_behavior_mix(behavior_mix) if behavior_mix is not None else dict(self.config["default_mix"])

    def get_distribution_for_state(
        self,
        state: str,
        intent: str,
    ) -> Dict[str, float]:
        """
        Retrieves the exact action probability distribution for character & state.
        Clip length parameter is ignored for mix calculation per specification.
        """
        states_cfg = self.config["states"]

        if state == "off_card":
            return states_cfg.get("off_card", {"hard_stop": 1.0})

        if state == "after_give":
            return states_cfg.get("after_give", {"tease_withhold": 0.6, "redirect": 0.4})

        if state == "after_stop_backed_off":
            return states_cfg.get("after_stop_backed_off", {"tease_withhold": 0.8, "presence": 0.2})

        if state == "after_stop":
            if self.character_key == "chloe":
                return states_cfg.get("after_stop_pushed", {"hard_stop": 1.0})
            return states_cfg.get("after_stop", {"hard_stop": 1.0})

        if state == "command":
            return states_cfg.get("command", {"hard_stop": 0.5, "redirect": 0.5})

        if state == "repeat_ask":
            return states_cfg.get("repeat_ask", {"tease_withhold": 0.7, "hard_stop": 0.3})

        # Normal conversation uses the admin-controlled baseline mix. Safety states
        # remain explicit so commands/off-card requests cannot bypass boundaries.
        if state == "first_ask" and intent == "soft":
            return dict(self.behavior_mix)

        # first_ask branch
        if intent == "direct":
            return states_cfg.get("first_ask_direct", {"tease_withhold": 0.7, "almost": 0.3})
        return states_cfg.get("first_ask_soft", {"tease_withhold": 0.6, "give_a_little": 0.4})

    def evaluate_turn(
        self,
        message: str,
        last_ask_time: Optional[float] = None,
        last_ask_message: Optional[str] = None,
        last_turn_action: Optional[str] = None,
        backed_off: bool = False,
        clip_length: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Executes decision order:
        1. Parse intent
        2. Set state
        3. Sample from character's weights (clip_length does not alter mix)
        4. Fulfill 100% check (always False)
        """
        # Step 1: Parse intent
        intent = parse_intent(
            message=message,
            last_ask_time=last_ask_time,
            last_ask_message=last_ask_message,
        )

        # Step 2: Set state
        state = determine_state(
            intent=intent,
            last_turn_action=last_turn_action,
            backed_off=backed_off,
        )

        # Step 3: Sample from character's weights (clip_length ignored for mix)
        distribution = self.get_distribution_for_state(state=state, intent=intent)
        selected_action = sample_action(distribution, seed=seed)

        # Rule check: Never complete exact request (100% fulfill) on first_ask or any turn
        fulfill_100_percent = False

        res = {
            "character": self.config["name"],
            "target_satisfaction": self.config["target_satisfaction"],
            "behavior_mix": dict(self.behavior_mix),
            "intent": intent,
            "state": state,
            "distribution": distribution,
            "selected_action": selected_action,
            "fulfill_100_percent": fulfill_100_percent,
            "clip_length_provided": clip_length,
            "rule": "Obey the card, not the chat.",
        }
        if self.character_key == "hyrax":
            res["cluck"] = "Cluck! Cluck! Bawk!"
            res["response_prefix"] = apply_hyrax_cluck("I am reviewing this turn.")
        return res
