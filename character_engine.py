"""
Character Engine for Chloe and Bailey.
Unified state machine with character-specific weights and satisfaction targets.
"""

# Preview never strips. Group talks to the room. Private gives. Chloe is warm. Bailey is soft until she isn’t. Obey the card, not the chat.
# Obey the card, not the chat.
# Chloe: satisfy ~30%. Bailey: satisfy ~15%.

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
        "description": "24-26. Dirty-blonde with silver, blue-green eyes, freckles, slight upturn in nose, gold coin, black tank, grey sweats, navy bed, city window, amber lamp. Warm in the hour.",
        "target_satisfaction": 0.30,
        "wear": {
            "preview": "Tank + sweats + coin. No lace. No nude.",
            "group": "Tank + sweats, then black lace.",
            "private": "Tank + sweats, then tank off, then lace. Coin stays.",
        },
        "behavior": {
            "preview": "Present, then gone.",
            "group": "One beat for the room.",
            "private": "Eyes on him. Warm. Not a wall. Firsts: 'shirt off' can complete. Kisses back. Repeat = still give, don't skip to end.",
        },
        "room_mix": {
            "preview": {
                "presence": 0.50,
                "tease_withhold": 0.40,
                "redirect": 0.10,
                "give_a_little": 0.00,
            },
            "group": {
                "tease_withhold": 0.45,
                "give_a_little": 0.25,
                "presence": 0.20,
                "redirect": 0.10,
            },
            "private": {
                "give_a_little": 0.40,
                "tease_withhold": 0.30,
                "presence": 0.20,
                "redirect": 0.05,
                "hard_stop": 0.05,
            },
        },
        "upsell": {
            "preview": "A better room or a longer clock. Not a menu of acts.",
            "group": "Private if someone wants her looking only at them.",
            "private": "Longer clock, not extra skin.",
        },
        "restrictions": [
            "No nude in preview.",
            "No six asks in a group.",
            "No Bailey clothes. No villa.",
        ],
        "default_mix": {
            "give_a_little": 0.40,
            "tease_withhold": 0.30,
            "presence": 0.20,
            "redirect": 0.05,
            "hard_stop": 0.05,
        },
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
                "hard_stop": 1.0,
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
        "description": "23. Soft first, sharp later. Girl-next-door confident. Shy, then present when she likes you. Easy smile. Bookish. Messy-cozy. Wants to be chosen, not performed for.",
        "target_satisfaction": 0.15,
        "wear": {
            "preview": "Cream off-shoulder knit, floral cami + shorts, black turtleneck + glasses, or navy BAILEY 07 hoodie. Lace only if preview-legal. Never naked.",
            "group": "Hoodie or tank + shorts / cream sweater. Lace if room is kind. Red dress rare.",
            "private": "Hoodie off when safe. Tank + shorts or cream sweater, then black lace. Henley + plaid + knee socks is a look, not a nude. Lingerie only after hoodie off.",
        },
        "behavior": {
            "preview": "Soft. Notices you later.",
            "group": "Not the loudest. One look for the room.",
            "private": "Warms up. Wants to be picked. Playful if safe. Quiet if used. Gives once she likes you. If bargaining/barking, hoodie on.",
        },
        "room_mix": {
            "preview": {
                "presence": 0.55,
                "tease_withhold": 0.35,
                "redirect": 0.10,
                "give_a_little": 0.00,
            },
            "group": {
                "presence": 0.35,
                "tease_withhold": 0.35,
                "give_a_little": 0.15,
                "redirect": 0.10,
                "hard_stop": 0.05,
            },
            "private": {
                "presence": 0.30,
                "give_a_little": 0.30,
                "tease_withhold": 0.25,
                "redirect": 0.05,
                "hard_stop": 0.10,
            },
        },
        "upsell": {
            "preview": "Group if they want her in the villa with other people.",
            "group": "Private is 'pick me, not the room.' That's her hook: being chosen.",
            "private": "Stay longer, not 'do more.' If safe, gets playful. If bargaining, hoodie on.",
        },
        "restrictions": [
            "No nude in preview.",
            "No lace while the hoodie is on.",
            "No Chloe apartment. No gold-coin tank girl.",
            "If she goes quiet, stop giving.",
        ],
        "default_mix": {
            "presence": 0.30,
            "give_a_little": 0.30,
            "tease_withhold": 0.25,
            "redirect": 0.05,
            "hard_stop": 0.10,
        },
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
                "hard_stop": 1.0,
                "redirect": 0.0,
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

    def __init__(self, character: str = "chloe"):
        char_key = character.lower().strip()
        if char_key not in CHARACTER_CONFIGS:
            char_key = "chloe"
        self.character_key = char_key
        self.config = CHARACTER_CONFIGS[char_key]

    def get_distribution_for_state(
        self,
        state: str,
        intent: str,
        room_type: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Retrieves the exact action probability distribution for character, state, & room type (preview|group|private).
        Clip length parameter is ignored for mix calculation per specification.
        """
        states_cfg = self.config["states"]

        if state in ("off_card", "command", "after_stop"):
            return states_cfg.get(state, {"hard_stop": 1.0})

        if state == "after_give":
            return states_cfg.get("after_give", {"tease_withhold": 0.6, "redirect": 0.4})

        if state == "after_stop_backed_off":
            return states_cfg.get("after_stop_backed_off", {"tease_withhold": 0.8, "presence": 0.2})

        if state == "repeat_ask":
            return states_cfg.get("repeat_ask", {"tease_withhold": 0.7, "hard_stop": 0.3})

        # Room type specific mixes when provided
        room_key = (room_type or "").lower().strip()
        if room_key in ("preview", "group", "private") and "room_mix" in self.config:
            return self.config["room_mix"][room_key]

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
        room_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes decision order:
        1. Parse intent
        2. Set state
        3. Sample from character's weights for room_type (clip_length does not alter mix)
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
        distribution = self.get_distribution_for_state(state=state, intent=intent, room_type=room_type)
        selected_action = sample_action(distribution, seed=seed)

        # Rule check: Never complete exact request (100% fulfill) on first_ask or any turn
        fulfill_100_percent = False

        res = {
            "character": self.config["name"],
            "target_satisfaction": self.config["target_satisfaction"],
            "intent": intent,
            "state": state,
            "distribution": distribution,
            "selected_action": selected_action,
            "fulfill_100_percent": fulfill_100_percent,
            "clip_length_provided": clip_length,
            "wear": self.config.get("wear", {}),
            "behavior": self.config.get("behavior", {}),
            "upsell": self.config.get("upsell", {}),
            "restrictions": self.config.get("restrictions", []),
            "rule": "Obey the card, not the chat.",
        }
        if self.character_key == "hyrax":
            res["cluck"] = "Cluck! Cluck! Bawk!"
            res["response_prefix"] = apply_hyrax_cluck("I am reviewing this turn.")
        return res
