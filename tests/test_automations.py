"""Exercise notification decisions using the actual shipped blueprint templates."""

from pathlib import Path
import re
import tempfile
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml

from igw_google_voice.automations import BLUEPRINT_NAMES, BLUEPRINT_ROOT, main, render_files


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.blueprints = {
            name: yaml.load(text, Loader=BlueprintLoader)
            for path, text in render_files().items()
            if (name := path.name) in BLUEPRINT_NAMES
        }

    def evaluator(self, name, states, *, trigger=False, **variables):
        blueprint = self.blueprints[name]
        env = NativeEnvironment(undefined=StrictUndefined)
        env.tests["match"] = lambda value, pattern: re.match(pattern, str(value)) is not None
        env.globals.update(states=lambda entity: states.get(entity, "unknown"),
                           is_state=lambda entity, value: states.get(entity) == value)
        inputs = blueprint["blueprint"]["input"]
        data = {
            key: inputs.get(value, {}).get("default", value)
            for key, value in blueprint["trigger_variables" if trigger else "variables"].items()
        }
        data.update(variables)
        def evaluate(expression):
            result = env.from_string(expression).render(**data)
            if isinstance(result, bool):
                return result
            self.assertIn(str(result).strip().lower(), ("true", "false"))
            return str(result).strip().lower() == "true"
        return evaluate

    def decisions(self, name, states, **variables):
        blueprint = self.blueprints[name]
        evaluate = self.evaluator(name, states, **variables)
        # The separate HA time condition is checked by HA; these are value/freshness/latch decisions.
        allowed = evaluate(blueprint["conditions"][1]["value_template"])
        if not allowed:
            return []
        return [index for index, branch in enumerate(blueprint["actions"][0]["choose"])
                if evaluate(branch["conditions"])]

    def trigger_matches(self, name, states, **variables):
        evaluate = self.evaluator(name, states, trigger=True, **variables)
        triggers = self.blueprints[name]["triggers"]
        self.assertEqual([item["trigger"] for item in triggers], ["template", "template", "time"])
        for item in triggers[:2]:
            self.assertEqual(item["for"], {"minutes": "stable_minutes"})
        return [evaluate(item["value_template"]) for item in triggers[:2]]

    def battery(self, value, *, fresh="on", latch="off", reserve=20, recovery=25):
        return self.decisions("battery_reserve.yaml", {
            "battery_sensor": value, "freshness_sensor": fresh, "episode_helper": latch,
        }, reserve=reserve, recovery=recovery)

    def test_battery_episode_has_hysteresis_and_no_repeat(self):
        self.assertEqual(self.battery("19"), [0])
        self.assertEqual(self.battery("19", latch="on"), [])
        for value in ("20", "22", "25"):
            self.assertEqual(self.battery(value), [])
            self.assertEqual(self.battery(value, latch="on"), [])
        self.assertEqual(self.battery("26", latch="on"), [1])
        self.assertEqual(self.battery("26"), [])

    def test_invalid_or_stale_battery_does_not_notify(self):
        for value in ("unknown", "unavailable", "nan", "inf", "-1", "101"):
            self.assertEqual(self.battery(value), [])
        for fresh in ("off", "unknown", "unavailable"):
            self.assertEqual(self.battery("10", fresh=fresh), [])
        self.assertEqual(self.battery("10", latch="unavailable"), [])
        self.assertEqual(self.battery("10", reserve=30, recovery=20), [])

    def test_condition_notifies_active_and_recovery_once(self):
        for condition, latch, expected in (("on", "off", [0]), ("on", "on", []),
                                            ("off", "on", [1]), ("off", "off", [])):
            self.assertEqual(self.decisions("energy_condition.yaml", {
                "condition_sensor": condition, "freshness_sensor": "on", "episode_helper": latch,
            }), expected)

    def test_unknown_grid_condition_is_never_a_recovery(self):
        for condition in ("unknown", "unavailable", "0"):
            self.assertEqual(self.decisions("energy_condition.yaml", {
                "condition_sensor": condition, "freshness_sensor": "on", "episode_helper": "on",
            }), [])
        self.assertEqual(self.decisions("energy_condition.yaml", {
            "condition_sensor": "off", "freshness_sensor": "off", "episode_helper": "on",
        }), [])

    def test_battery_hold_requires_fresh_valid_threshold_state_together(self):
        for value, fresh, expected in (
            ("30", "on", [False, True]),
            ("19", "on", [True, False]),
            ("19", "off", [False, False]),
            ("22", "on", [False, False]),
            ("unknown", "on", [False, False]),
            ("unavailable", "on", [False, False]),
            ("nan", "on", [False, False]),
            ("inf", "on", [False, False]),
            ("-1", "on", [False, False]),
            ("101", "on", [False, False]),
        ):
            self.assertEqual(self.trigger_matches("battery_reserve.yaml", {
                "battery_sensor": value, "freshness_sensor": fresh,
            }), expected)
        self.assertEqual(self.trigger_matches("battery_reserve.yaml", {
            "battery_sensor": "10", "freshness_sensor": "on",
        }, reserve=30, recovery=20), [False, False])

    def test_condition_hold_starts_only_when_freshness_and_condition_match(self):
        # Freshness already on cannot run a separate timer while the condition changes.
        for condition, fresh, expected in (
            ("off", "on", [False, True]),
            ("on", "on", [True, False]),
            ("on", "off", [False, False]),
            ("off", "unknown", [False, False]),
            ("unknown", "on", [False, False]),
            ("unavailable", "on", [False, False]),
        ):
            self.assertEqual(self.trigger_matches("energy_condition.yaml", {
                "condition_sensor": condition, "freshness_sensor": fresh,
            }), expected)

    def test_notification_service_is_restricted_and_uses_one_blocking_action(self):
        cases = (
            ("battery_reserve.yaml", {"battery_sensor": "10"}),
            ("energy_condition.yaml", {"condition_sensor": "on"}),
        )
        for name, values in cases:
            states = {**values, "freshness_sensor": "on", "episode_helper": "off"}
            for service in ("persistent_notification.create", "notify.mobile_app_test_phone"):
                self.assertEqual(self.decisions(name, states, notification_service=service), [0])
            for service in ("light.turn_on", "homeassistant.restart", "notify", "notify.",
                            "notify.mobile.app", "notify.Mobile_App", " notify.mobile_app",
                            "notify.mobile_app\n", None, ["notify.mobile_app"]):
                self.assertEqual(self.decisions(name, states, notification_service=service), [])
            blueprint = self.blueprints[name]
            self.assertNotIn("notification_actions", blueprint["blueprint"]["input"])
            for branch in blueprint["actions"][0]["choose"]:
                sequence = branch["sequence"]
                self.assertEqual(sequence[1], {
                    "action": "{{ notification_service }}",
                    "data": {"title": "Home Energy", "message": "{{ energy_notification_message }}"},
                })
                self.assertTrue(sequence[2]["action"].startswith("input_boolean.turn_"))
                self.assertNotIn("continue_on_error", sequence[1])

    def test_renderer_stages_assets_without_enabling_automations(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            self.assertEqual(main(["--output", str(target)]), 0)
            for name in BLUEPRINT_NAMES:
                self.assertTrue((target / BLUEPRINT_ROOT / name).is_file())
            self.assertFalse((target / "automations.yaml").exists())
            self.assertFalse((target / "secrets.yaml").exists())
            self.assertEqual(main(["--output", str(target)]), 1)


if __name__ == "__main__":
    unittest.main()
