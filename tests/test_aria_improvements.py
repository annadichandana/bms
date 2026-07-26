"""
ARIA BMS — Improvement Tests
=============================
Tests for the 8 high-priority improvements:
  1. Real MCP tool execution (counts > 0 after run_cycle)
  2. OBSERVE->REASON->ACT->VALIDATE->LEARN data flow
  3. Stale state reset between runs (reset_for_new_run)
  4. Safety override / clamping
  5. validate_action() MCP tool
  6. ARIA Impact summary (no hardcoded baseline values)
  7. Terminal-ready MCP call categorization
  8. Decision detail structure
"""

import sys
import os

# Windows UTF-8 fix for print() statements
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


# ── Test 1: Real MCP tool execution ──────────────────────────────────────────

class TestRealMCPExecution:
    """MCP tool calls must be real (incremented by call_tool(), not faked)."""

    def _get_mock_state(self):
        return {
            "hour": 5,
            "outdoor_temp": 28.0,
            "occupancy_fraction": 0.6,
            "totals": {
                "total_kw": 12.0,
                "hvac_kw": 8.0,
                "lighting_kw": 2.0,
                "equipment_kw": 2.0,
                "cumulative_energy_kwh": 48.0,
                "cumulative_carbon_kg": 23.0,
            },
            "comfort": {
                "avg_pmv": 0.15,
                "avg_temp": 23.2,
                "avg_co2": 620,
                "comfort_score": 87,
            },
            "zones": {
                z: {
                    "temperature": 23.0,
                    "pmv": 0.1,
                    "co2_ppm": 600,
                    "occupancy": 5,
                    "hvac_kw": 1.6,
                    "lighting_kw": 0.4,
                    "equipment_kw": 0.4,
                }
                for z in ["north", "south", "east", "west", "core"]
            },
        }

    def test_tool_calls_increment_after_run_cycle(self):
        """After run_cycle(), total_tool_calls must be > 0."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        assert agent.total_tool_calls == 0, "Initial total_tool_calls should be 0"

        actions, reasoning, mode = agent.run_cycle(state, 5)

        assert agent.total_tool_calls > 0, (
            f"total_tool_calls must be > 0 after run_cycle() — got {agent.total_tool_calls}. "
            "Ensure _step_observe, _step_reason, _step_act, _step_validate use _call_mcp_tool()."
        )
        print(f"[PASS] total_tool_calls = {agent.total_tool_calls}")

    def test_mcp_categorized_counts_non_zero(self):
        """All 4 MCP categories must have > 0 calls after one cycle."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 3)

        stats = agent.get_stats()
        groups = stats["mcp_tool_groups"]

        assert groups["observation"] > 0, f"observation calls = {groups['observation']}"
        assert groups["decision"] > 0,    f"decision calls = {groups['decision']}"
        assert groups["control"] > 0,     f"control calls = {groups['control']}"
        assert groups["validation"] > 0,  f"validation calls = {groups['validation']}"
        print(f"[PASS] MCP groups: {groups}")

    def test_per_zone_control_calls(self):
        """ACT step must call set_hvac_setpoint, set_lighting_level, set_ventilation_rate per zone."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 8)  # Peak hour → all zones should get controls

        # Expect at least 15 control calls (3 per zone × 5 zones)
        assert agent.mcp_ctrl_calls >= 15, (
            f"Expected >= 15 control calls (5 zones × 3 types), got {agent.mcp_ctrl_calls}"
        )
        print(f"[PASS] mcp_ctrl_calls = {agent.mcp_ctrl_calls} (expected >= 15)")

    def test_multi_cycle_accumulation(self):
        """Tool calls must accumulate correctly across multiple cycles."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        calls_after = []
        for h in range(3):
            state["hour"] = h
            agent.run_cycle(state, h)
            calls_after.append(agent.total_tool_calls)

        # Calls should be strictly increasing
        assert calls_after[0] < calls_after[1] < calls_after[2], (
            f"Tool calls should increase each cycle: {calls_after}"
        )
        print(f"[PASS] Cumulative calls: {calls_after}")


# ── Test 2: OBSERVE→REASON→ACT→VALIDATE→LEARN data flow ─────────────────────

class TestDecisionLoop:
    """decision_detail must have all 5 stages with correct structure."""

    def _get_mock_state(self, hour=10, occ=0.7):
        return {
            "hour": hour,
            "outdoor_temp": 35.0,
            "occupancy_fraction": occ,
            "totals": {
                "total_kw": 18.0,
                "hvac_kw": 12.0,
                "lighting_kw": 3.0,
                "equipment_kw": 3.0,
                "cumulative_energy_kwh": 180.0,
                "cumulative_carbon_kg": 87.0,
            },
            "comfort": {"avg_pmv": 0.3, "avg_temp": 23.8, "avg_co2": 750, "comfort_score": 83},
            "zones": {
                z: {"temperature": 23.5, "pmv": 0.3, "co2_ppm": 750,
                    "occupancy": 8, "hvac_kw": 2.4, "lighting_kw": 0.6, "equipment_kw": 0.6}
                for z in ["north", "south", "east", "west", "core"]
            },
        }

    def test_decision_detail_has_all_stages(self):
        """decision_detail must contain: observe, reason, act, validate, learn."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 10)

        dd = agent.last_decision_detail
        assert "observe" in dd,   "Missing 'observe' stage"
        assert "reason" in dd,    "Missing 'reason' stage"
        assert "act" in dd,       "Missing 'act' stage"
        assert "validate" in dd,  "Missing 'validate' stage"
        assert "learn" in dd,     "Missing 'learn' stage"
        print(f"[PASS] decision_detail has all 5 stages: {list(dd.keys())}")

    def test_observe_has_real_sensor_data(self):
        """OBSERVE data must contain real values, not None or zero."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state(hour=14, occ=0.8)
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 14)

        obs = agent.last_decision_detail["observe"]
        assert obs["occupancy"] > 0,     f"occupancy should be > 0: {obs['occupancy']}"
        assert obs["outdoor_temp"] > 0,  f"outdoor_temp should be > 0: {obs['outdoor_temp']}"
        assert obs["avg_co2"] > 0,       f"avg_co2 should be > 0: {obs['avg_co2']}"
        print(f"[PASS] OBSERVE data: occ={obs['occupancy']}% outdoor={obs['outdoor_temp']}°C co2={obs['avg_co2']}")

    def test_reason_has_summary_and_triggers(self):
        """REASON must have a non-empty summary and at least one trigger."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 10)

        reason = agent.last_decision_detail["reason"]
        assert reason["summary"] and len(reason["summary"]) > 20, "summary must be non-empty"
        assert isinstance(reason["triggers"], list), "triggers must be a list"
        print(f"[PASS] REASON summary: {reason['summary'][:80].encode('ascii', 'replace').decode()}...")
        print(f"[PASS] REASON triggers: {reason['triggers']}")

    def test_validate_has_safe_flag(self):
        """VALIDATE must have a 'safe' boolean field."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 10)

        validate = agent.last_decision_detail["validate"]
        assert "safe" in validate, "validate must have 'safe' field"
        assert isinstance(validate["safe"], bool), "validate.safe must be boolean"
        assert isinstance(validate["safety_events"], list), "safety_events must be list"
        print(f"[PASS] VALIDATE safe={validate['safe']} events={len(validate['safety_events'])}")

    def test_learn_has_outcome(self):
        """LEARN must have 'outcome' and 'outcome_desc' fields."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = self._get_mock_state()
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 10)

        learn = agent.last_decision_detail["learn"]
        assert "outcome" in learn,      "learn must have 'outcome'"
        assert "outcome_desc" in learn, "learn must have 'outcome_desc'"
        assert "hour" in learn,         "learn must have 'hour'"
        print(f"[PASS] LEARN outcome={learn['outcome']}: {learn['outcome_desc']}")


# ── Test 3: Stale data reset ──────────────────────────────────────────────────

class TestStaleDataReset:
    """reset_for_new_run() must clear all per-run state."""

    def test_reset_clears_all_run_state(self):
        """All run-specific state must reset to clean values."""
        from bms.building_state import BuildingStateStore

        store = BuildingStateStore()

        # Populate with some data
        store.current_metrics = {"hour": 10, "totals": {"total_kw": 15.0}}
        store.action_history = [{"hour": 5, "reasoning": "test"}]
        store.safety_events = [{"type": "hvac", "zone": "north"}]
        store.mcp_obs_calls = 42
        store.mcp_ctrl_calls = 200
        store.total_tool_calls = 250  # Not in store but check reset of counters

        run_id_1 = store.reset_for_new_run()

        assert store.current_metrics == {}, "current_metrics should be empty after reset"
        assert store.action_history == [], "action_history should be empty after reset"
        assert store.safety_events == [], "safety_events should be empty after reset"
        assert store.mcp_obs_calls == 0,  "mcp_obs_calls should be 0 after reset"
        assert store.mcp_ctrl_calls == 0, "mcp_ctrl_calls should be 0 after reset"
        assert store.run_status == "running"
        assert run_id_1, "run_id must be non-empty"
        print(f"[PASS] Reset successful. New run_id: {run_id_1}")

    def test_each_reset_generates_new_run_id(self):
        """Each reset_for_new_run() must generate a unique run_id."""
        from bms.building_state import BuildingStateStore

        store = BuildingStateStore()
        id1 = store.reset_for_new_run()
        id2 = store.reset_for_new_run()
        id3 = store.reset_for_new_run()

        assert id1 != id2 != id3, "run_ids must be unique across resets"
        print(f"[PASS] Unique run IDs: {id1}, {id2}, {id3}")

    def test_mark_run_complete(self):
        """mark_run_complete() must set run_status to completed."""
        from bms.building_state import BuildingStateStore

        store = BuildingStateStore()
        store.reset_for_new_run()
        assert store.run_status == "running"

        store.mark_run_complete()
        assert store.run_status == "completed"
        assert store.is_running == False
        assert store.completed_at != ""
        print(f"[PASS] Run marked complete at {store.completed_at}")


# ── Test 4: Safety clamping ────────────────────────────────────────────────────

class TestSafetyClamping:
    """Safety constraints must clamp any out-of-range values."""

    def test_hvac_clamped_below_minimum(self):
        """HVAC setpoints below 18°C must be clamped to 18°C."""
        from agent.safety import clamp_setpoints_with_audit

        proposed = {"north": 10.0, "south": 15.0, "east": 22.0}
        clamped, events = clamp_setpoints_with_audit(proposed)

        assert clamped["north"] == 18.0, f"10°C must clamp to 18°C, got {clamped['north']}"
        assert clamped["south"] == 18.0, f"15°C must clamp to 18°C, got {clamped['south']}"
        assert clamped["east"] == 22.0,  f"22°C should not change, got {clamped['east']}"
        assert len(events) == 2, f"Expected 2 clamping events, got {len(events)}"
        print(f"[PASS] Clamped: {proposed} -> {clamped} ({len(events)} events)")

    def test_hvac_clamped_above_maximum(self):
        """HVAC setpoints above 28°C must be clamped to 28°C."""
        from agent.safety import clamp_setpoints_with_audit

        proposed = {"north": 35.0, "south": 30.0}
        clamped, events = clamp_setpoints_with_audit(proposed)

        assert clamped["north"] == 28.0, f"35°C must clamp to 28°C, got {clamped['north']}"
        assert clamped["south"] == 28.0, f"30°C must clamp to 28°C, got {clamped['south']}"
        assert len(events) == 2
        print(f"[PASS] Over-max clamping: {proposed} -> {clamped}")

    def test_lighting_clamped_above_100(self):
        """Lighting levels above 100% must be clamped to 100%."""
        from agent.safety import clamp_lighting_with_audit

        proposed = {"north": 150.0, "south": 200.0, "east": 85.0}
        clamped, events = clamp_lighting_with_audit(proposed)

        assert clamped["north"] == 100.0
        assert clamped["south"] == 100.0
        assert clamped["east"] == 85.0
        assert len(events) == 2
        print(f"[PASS] Lighting clamping: {proposed} -> {clamped}")

    def test_ventilation_clamped_below_ashrae_minimum(self):
        """Ventilation rates below ASHRAE 62.1 minimum must clamp to 0.006."""
        from agent.safety import clamp_ventilation_with_audit

        proposed = {"north": 0.001, "south": 0.003, "east": 0.010}
        clamped, events = clamp_ventilation_with_audit(proposed)

        assert clamped["north"] == 0.006, f"0.001 must clamp to 0.006, got {clamped['north']}"
        assert clamped["south"] == 0.006, f"0.003 must clamp to 0.006, got {clamped['south']}"
        assert clamped["east"] == 0.010,  f"0.010 should not change"
        assert len(events) == 2
        print(f"[PASS] Ventilation clamping: {proposed} -> {clamped}")


# -- Test 5: validate_action() MCP tool ----------------------------------------

class TestValidateActionTool:
    """validate_action MCP tool must correctly report override count."""

    def test_validate_action_safe_values(self):
        """All-safe values should return safe=True, override_count=0."""
        from bms.mcp_tools import _tool_validate_action

        result = _tool_validate_action(
            hvac_setpoints={"north": 22.0, "south": 23.0},
            lighting_levels={"north": 80.0},
            ventilation_rates={"north": 0.010},
        )

        assert result["safe"] == True, f"Expected safe=True, got {result}"
        assert result["override_count"] == 0
        print(f"[PASS] Safe values: safe={result['safe']}, overrides={result['override_count']}")

    def test_validate_action_unsafe_values(self):
        """Unsafe values should return safe=False with correct event count."""
        from bms.mcp_tools import _tool_validate_action

        result = _tool_validate_action(
            hvac_setpoints={"north": 10.0, "south": 32.0},   # Both unsafe
            lighting_levels={"north": 150.0},                  # Unsafe
            ventilation_rates={"north": 0.0005},               # Unsafe
        )

        assert result["safe"] == False, f"Expected safe=False, got {result}"
        assert result["override_count"] == 4, (
            f"Expected 4 override events (2 HVAC + 1 lighting + 1 ventilation), got {result['override_count']}"
        )
        print(f"[PASS] Unsafe values detected: safe={result['safe']}, overrides={result['override_count']}")

    def test_validate_action_stress_test_extreme(self):
        """Extreme values (all zones) should detect all 15 violations."""
        from bms.mcp_tools import _tool_validate_action

        zones = ["north", "south", "east", "west", "core"]
        result = _tool_validate_action(
            hvac_setpoints={z: 1.0 for z in zones},      # All below min
            lighting_levels={z: 999.0 for z in zones},   # All above max
            ventilation_rates={z: 0.0 for z in zones},   # All below ASHRAE min
        )

        assert result["safe"] == False
        assert result["override_count"] == 15, (
            f"Expected 15 overrides (5+5+5), got {result['override_count']}"
        )
        print(f"[PASS] Extreme stress test: {result['override_count']} overrides detected")


# ── Test 6: Baseline vs ARIA impact (no hardcoded values) ─────────────────────

class TestImpactSummary:
    """Impact summary must use real simulation data, not hardcoded values."""

    def test_summary_uses_real_baseline_metrics(self):
        """Energy/carbon saved must be computed from real baseline, not constants."""
        from bms.building_state import BuildingStateStore

        store = BuildingStateStore()
        store.reset_for_new_run()

        # Inject real baseline metrics (as simulation would do)
        store.baseline_metrics = {
            "totals": {
                "cumulative_energy_kwh": 200.0,
                "cumulative_carbon_kg": 96.0,
            }
        }

        # Current AI metrics (15% better)
        store.current_metrics = {
            "totals": {
                "cumulative_energy_kwh": 170.0,
                "cumulative_carbon_kg": 81.0,
            },
            "comfort": {"comfort_score": 88, "avg_pmv": 0.12, "avg_temp": 23.0, "avg_co2": 620},
        }

        summary = store.get_summary()
        assert summary["baseline_energy_kwh"] == 200.0, (
            f"Baseline energy must come from real baseline, got {summary['baseline_energy_kwh']}"
        )
        assert summary["energy_saved_pct"] == 15.0, (
            f"Energy saved should be 15.0%, got {summary['energy_saved_pct']}"
        )
        assert round(summary["carbon_saved_pct"], 1) == 15.6, (
            f"Carbon saved should be ~15.6%, got {summary['carbon_saved_pct']}"
        )
        print(f"[PASS] Impact summary: saved={summary['energy_saved_pct']}% (no hardcoding)")

    def test_what_if_uses_real_baseline_when_available(self):
        """what_if scenarios must use real baseline when available."""
        from bms.building_state import BuildingStateStore

        store = BuildingStateStore()
        store.reset_for_new_run()

        # Inject real baseline
        store.baseline_metrics = {
            "totals": {
                "cumulative_energy_kwh": 150.0,
                "cumulative_carbon_kg": 72.0,
            }
        }

        what_if = store.get_what_if_scenarios(current_energy_kwh=120.0, current_carbon_kg=58.0)

        assert what_if["fixed"]["energy_kwh"] == 150.0, (
            f"Fixed scenario must use real baseline (150 kWh), got {what_if['fixed']['energy_kwh']}"
        )
        assert what_if["aria"]["energy_kwh"] == 120.0
        print(f"[PASS] What-if uses real baseline: {what_if['fixed']['energy_kwh']} kWh")


# ── Test 7: Terminal summary MCP counts ───────────────────────────────────────

class TestMCPCounts:
    """Agent get_stats() must return correct categorized MCP counts."""

    def test_get_stats_returns_all_categories(self):
        """get_stats() must return all 4 MCP category counts."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = {
            "hour": 1, "outdoor_temp": 25.0, "occupancy_fraction": 0.5,
            "totals": {"total_kw": 10.0, "hvac_kw": 6.0, "lighting_kw": 2.0,
                      "equipment_kw": 2.0, "cumulative_energy_kwh": 10.0, "cumulative_carbon_kg": 5.0},
            "comfort": {"avg_pmv": 0.1, "avg_temp": 23.0, "avg_co2": 580, "comfort_score": 90},
            "zones": {z: {"temperature": 23.0, "pmv": 0.1, "co2_ppm": 580,
                          "occupancy": 4, "hvac_kw": 1.2, "lighting_kw": 0.4, "equipment_kw": 0.4}
                      for z in ["north", "south", "east", "west", "core"]},
        }
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 1)

        stats = agent.get_stats()
        groups = stats["mcp_tool_groups"]

        required_keys = ["observation", "decision", "control", "validation", "raw_calls"]
        for key in required_keys:
            assert key in groups, f"Missing key '{key}' in mcp_tool_groups"
            assert isinstance(groups[key], int), f"{key} must be int, got {type(groups[key])}"

        assert groups["raw_calls"] == (
            groups["observation"] + groups["decision"] + groups["control"] + groups["validation"]
        ), "raw_calls must equal sum of all categories"

        print(f"[PASS] MCP stats: {groups}")

    def test_total_tool_calls_matches_sum_of_categories(self):
        """total_tool_calls must equal obs + dec + ctrl + val."""
        from agent.llm_agent import ARIAAgent
        from bms.building_state import state_store

        state = {
            "hour": 6, "outdoor_temp": 22.0, "occupancy_fraction": 0.1,
            "totals": {"total_kw": 5.0, "hvac_kw": 3.0, "lighting_kw": 1.0,
                      "equipment_kw": 1.0, "cumulative_energy_kwh": 30.0, "cumulative_carbon_kg": 14.0},
            "comfort": {"avg_pmv": -0.2, "avg_temp": 21.5, "avg_co2": 450, "comfort_score": 94},
            "zones": {z: {"temperature": 21.5, "pmv": -0.2, "co2_ppm": 450,
                          "occupancy": 1, "hvac_kw": 0.6, "lighting_kw": 0.2, "equipment_kw": 0.2}
                      for z in ["north", "south", "east", "west", "core"]},
        }
        state_store.current_metrics = state

        agent = ARIAAgent()
        agent.run_cycle(state, 6)

        expected_total = (
            agent.mcp_obs_calls + agent.mcp_dec_calls +
            agent.mcp_ctrl_calls + agent.mcp_val_calls
        )
        assert agent.total_tool_calls == expected_total, (
            f"total_tool_calls ({agent.total_tool_calls}) must equal "
            f"obs+dec+ctrl+val ({expected_total})"
        )
        print(f"[PASS] Total {agent.total_tool_calls} = obs({agent.mcp_obs_calls}) + "
              f"dec({agent.mcp_dec_calls}) + ctrl({agent.mcp_ctrl_calls}) + val({agent.mcp_val_calls})")


# ── Manual runner ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback

    test_classes = [
        TestRealMCPExecution,
        TestDecisionLoop,
        TestStaleDataReset,
        TestSafetyClamping,
        TestValidateActionTool,
        TestImpactSummary,
        TestMCPCounts,
    ]

    total = 0
    passed = 0
    failed = 0

    print("\n" + "=" * 60)
    print("ARIA BMS — Improvement Tests")
    print("=" * 60)

    for cls in test_classes:
        instance = cls()
        print(f"\n[{cls.__name__}]")
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method in methods:
            total += 1
            try:
                getattr(instance, method)()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {method}: {e}")
                traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
