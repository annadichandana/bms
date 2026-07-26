import { useState, useEffect, useRef } from 'react';

/**
 * useWebSocket — connects to the ARIA BMS WebSocket and normalizes
 * the raw server message into a consistent shape that all components expect.
 *
 * Raw server payload uses:  metrics, controls, summary, reasoning, etc.
 * Normalized state exposes: energy, simulation, zones, comfort, controls, ...
 *
 * This normalization layer ensures components never access undefined paths
 * and provides sensible defaults for every field.
 */
export function useWebSocket(url) {
  const [state, setState] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const ws = useRef(null);
  const reconnectTimeout = useRef(null);
  const retryCount = useRef(0);

  /** Transform the raw WS server message into the normalized state shape */
  function normalize(raw) {
    if (!raw || raw.ping) return null;

    const metrics      = raw.metrics      || {};
    const totals       = metrics.totals   || {};
    const comfort      = metrics.comfort  || {};
    const baseline     = raw.baseline     || {};
    const baseTotals   = baseline.totals  || {};
    const summary      = raw.summary      || {};
    const controls     = raw.controls     || {};
    const prevControls = raw.prev_controls || {};

    // ── Energy ──────────────────────────────────────────────────────────
    const aiEnergy     = totals.cumulative_energy_kwh  || 0;
    const baseEnergy   = baseTotals.cumulative_energy_kwh
                         || summary.baseline_energy_kwh
                         || 117.3;
    const aiCarbon     = totals.cumulative_carbon_kg   || 0;
    const baseCarbon   = baseTotals.cumulative_carbon_kg
                         || summary.baseline_carbon_kg
                         || 56.9;
    const savingsPct   = summary.energy_saved_pct
                         ?? (baseEnergy > 0
                              ? parseFloat(((baseEnergy - aiEnergy) / baseEnergy * 100).toFixed(1))
                              : 0);
    const carbonSavedPct = summary.carbon_saved_pct
                           ?? (baseCarbon > 0
                                ? parseFloat(((baseCarbon - aiCarbon) / baseCarbon * 100).toFixed(1))
                                : 0);
    const savingsUsd   = parseFloat(((baseEnergy - aiEnergy) * 0.12).toFixed(2));

    // ── Simulation hour → wall-clock approximation ────────────────────
    const hour = raw.hour ?? 0;
    // Represent hour as a time string (start of business day = 6:00 AM + hour)
    const simDate = new Date();
    simDate.setHours(6 + (hour % 24), 0, 0, 0);

    return {
      // ── Type / phase ────────────────────────────────────────────────
      type:  raw.type,
      phase: raw.phase,

      // ── Energy object (used by KpiPanel, ComparisonBanner, EnergyChart) ──
      energy: {
        total_kw:          totals.total_kw          || 0,
        total_kwh:         aiEnergy,
        cumulative_kwh:    aiEnergy,
        baseline_kwh:      baseEnergy,
        carbon_kg:         aiCarbon,
        baseline_carbon_kg: baseCarbon,
        savings_pct:       savingsPct,
        carbon_saved_pct:  carbonSavedPct,
        savings_usd:       savingsUsd,
      },

      // ── Simulation metadata (used by KpiPanel, header) ──────────────
      simulation: {
        hour,
        sim_time:          simDate.toISOString(),
        outdoor_temp:      metrics.outdoor_temp      || 30,
        occupancy_fraction: metrics.occupancy_fraction || 0,
        running:           raw.type !== 'complete',
        speed_multiplier:  3,
        ep_mode:           raw.ep_mode || 'physics_mock',
        source:            metrics._source || 'physics_mock',
      },

      // ── Zone sensor data (keyed: north/south/east/west/core) ─────────
      zones:   metrics.zones || {},
      comfort: {
        avg_pmv:       comfort.avg_pmv        || 0,
        avg_temp:      comfort.avg_temp       || 22,
        avg_co2:       comfort.avg_co2        || 500,
        comfort_score: comfort.comfort_score  || 0,
        pmv_min:       comfort.pmv_min        || 0,
        pmv_max:       comfort.pmv_max        || 0,
      },

      // ── AI decision data ────────────────────────────────────────────
      reasoning:     raw.reasoning       || '',
      mode:          raw.mode            || 'fallback',
      agent_stats:   raw.agent_stats     || {},

      // ── Controls (current epoch and previous epoch) ──────────────────
      controls,
      prev_controls: prevControls,

      // ── Safety & decision detail (OBSERVE→REASON→ACT→VALIDATE→LEARN) ─
      safety_events:   raw.safety_events   || [],
      decision_detail: raw.decision_detail || {},

      // ── Anomaly detection ────────────────────────────────────────────
      anomalies: raw.anomalies || [],

      // ── What-if scenario comparison ──────────────────────────────────
      what_if: raw.what_if || null,

      // ── Multi-objective weights ──────────────────────────────────────
      objective_weights: raw.objective_weights || {
        energy: 0.40, comfort: 0.25, carbon: 0.20, iaq: 0.10, safety: 'HARD',
      },

      // ── System trust indicators ──────────────────────────────────────
      trust_status: raw.trust_status || {
        energyplus: false, mcp: true, safety: true, fallback: true,
        ashrae: true, co2: true, carbon: true,
      },

      // ── MCP tool group summary ───────────────────────────────────────
      mcp_tool_groups: raw.mcp_tool_groups || {},

      // ── Summary (used by ComparisonBanner, ImpactSummary) ───────────
      summary: {
        ...summary,
        baseline_energy_kwh:  summary.baseline_energy_kwh  || baseEnergy,
        ai_energy_kwh:        summary.ai_energy_kwh        || aiEnergy,
        energy_saved_pct:     savingsPct,
        baseline_carbon_kg:   summary.baseline_carbon_kg   || baseCarbon,
        ai_carbon_kg:         summary.ai_carbon_kg         || aiCarbon,
        carbon_saved_pct:     carbonSavedPct,
        comfort_score:        summary.comfort_score        || comfort.comfort_score || 0,
        avg_pmv:              summary.avg_pmv              || comfort.avg_pmv || 0,
        avg_co2:              summary.avg_co2              || comfort.avg_co2 || 500,
        safety_violations:    summary.safety_violations    || 0,
        total_ai_cycles:      summary.total_ai_cycles      || (hour + 1),
        ep_validated:         summary.ep_validated         || true,
      },

      // ── AI log for decision log component ───────────────────────────
      ai_log: raw.ai_log || [],

      // ── Raw payload (for advanced use / debugging) ───────────────────
      _raw: raw,
    };
  }

  useEffect(() => {
    function connect() {
      console.log('[ARIA] Connecting to WS:', url);
      ws.current = new WebSocket(url);

      ws.current.onopen = () => {
        console.log('[ARIA] WS Connected');
        setIsConnected(true);
        retryCount.current = 0;
      };

      ws.current.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data);
          if (raw.ping) return;  // ignore keepalive pings
          const normalized = normalize(raw);
          if (normalized) {
            setState(normalized);
            setLastUpdate(new Date());
          }
        } catch (err) {
          console.error('[ARIA] Failed to parse WS message:', err);
        }
      };

      ws.current.onclose = () => {
        setIsConnected(false);
        console.log('[ARIA] WS Disconnected');
        // Exponential backoff reconnect
        const timeout = Math.min(1000 * (2 ** retryCount.current), 30000);
        console.log(`[ARIA] Reconnecting in ${timeout}ms...`);
        reconnectTimeout.current = setTimeout(connect, timeout);
        retryCount.current += 1;
      };

      ws.current.onerror = (err) => {
        console.error('[ARIA] WS Error:', err);
        ws.current.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout.current);
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [url]);

  return { state, isConnected, lastUpdate };
}
