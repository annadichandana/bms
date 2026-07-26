"""
EnergyPlus subprocess runner (32-bit EP + 64-bit Python compatible)
====================================================================
Runs energyplus.exe as a child process and reads hourly results from
eplusout.sql. Used when pyenergyplus cannot load EnergyPlusAPI.dll
(architecture mismatch: x86 EnergyPlus vs x64 Python).
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from simulation.building_sim import (
    ZONES,
    calculate_pmv,
    occupancy_fraction,
    outdoor_temperature,
    _comfort_score,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_IDF = REPO_ROOT / "building_models" / "multi_zone_office.idf"
EP_OUTPUT = REPO_ROOT / "data" / "ep_output"
CARBON_FACTOR = float(__import__("os").environ.get("CARBON_FACTOR_KG_PER_KWH", "0.485"))

# 5ZoneAirCooled zone → BMS zone names (by building geometry)
EP_ZONE_MAP = {
    "SPACE1-1": "south",
    "SPACE2-1": "west",
    "SPACE3-1": "north",
    "SPACE4-1": "east",
    "SPACE5-1": "core",
}

EP_SEARCH_PATHS = [
    Path(r"C:\EnergyPlusV24-1-0"),
    Path(r"C:\EnergyPlusV23-2-0"),
    Path(r"C:\EnergyPlusV23-1-0"),
    Path("/usr/local/EnergyPlus-24-1-0"),
]


def pe_machine(path: Path) -> Optional[str]:
    """Return PE machine type: x64, x86, ARM64."""
    try:
        with open(path, "rb") as f:
            header = f.read(512)
        if header[:2] != b"MZ":
            return None
        pe_off = struct.unpack_from("<I", header, 0x3C)[0]
        with open(path, "rb") as f:
            f.seek(pe_off)
            if f.read(4) != b"PE\x00\x00":
                return None
            machine = struct.unpack("<H", f.read(2))[0]
        return {0x8664: "x64", 0x14C: "x86", 0xAA64: "ARM64"}.get(machine)
    except OSError:
        return None


def python_bits() -> int:
    return struct.calcsize("P") * 8


def pyenergyplus_compatible(ep_dir: Path) -> Tuple[bool, str]:
    """Check if pyenergyplus DLL matches Python architecture."""
    dll = ep_dir / "EnergyPlusAPI.dll"
    if not dll.exists():
        return False, "EnergyPlusAPI.dll not found"
    dll_arch = pe_machine(dll)
    py_arch = "x64" if python_bits() == 64 else "x86"
    if dll_arch != py_arch:
        return False, (
            f"Architecture mismatch: Python is {py_arch} but EnergyPlus DLL is {dll_arch}. "
            f"Use subprocess mode or install {py_arch} EnergyPlus."
        )
    return True, "compatible"


def find_energyplus_dir() -> Optional[Path]:
    import os

    env = os.environ.get("ENERGYPLUS_DIR")
    if env:
        p = Path(env)
        if (p / "energyplus.exe").exists() or (p / "energyplus").exists():
            return p
    for p in EP_SEARCH_PATHS:
        if p.exists() and ((p / "energyplus.exe").exists() or (p / "energyplus").exists()):
            return p
    return None


def find_weather_file(ep_dir: Path) -> Path:
    """Prefer Delhi EPW in repo, then EP install WeatherData."""
    candidates = [
        REPO_ROOT / "building_models" / "IND_Delhi.421820_ISHRAE.epw",
        ep_dir / "WeatherData" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
        ep_dir / "WeatherData" / "USA_CO_Golden-NREL.724666_TMY3.epw",
    ]
    for c in candidates:
        if c.exists():
            return c
    epws = list((REPO_ROOT / "building_models").glob("*.epw"))
    if epws:
        return epws[0]
    raise FileNotFoundError("No EPW weather file found")


def ensure_building_idf(ep_dir: Path) -> Path:
    """
    Ensure building_models/multi_zone_office.idf exists.
    Copies EnergyPlus 5ZoneAirCooled example and patches for 1-day summer run + SQLite.
    """
    BASE_IDF.parent.mkdir(parents=True, exist_ok=True)
    source = ep_dir / "ExampleFiles" / "5ZoneAirCooled.idf"
    if not source.exists():
        raise FileNotFoundError(f"EnergyPlus example IDF not found: {source}")

    if BASE_IDF.exists() and BASE_IDF.stat().st_size > 100_000:
        return BASE_IDF

    text = source.read_text(encoding="utf-8", errors="replace")

    # One summer design day (Jul 15) — fast ~15s run, 24 hourly timesteps
    run_period = (
        "  RunPeriod,\n"
        "    ARIA Summer Day,         !- Name\n"
        "    7,                       !- Begin Month\n"
        "    15,                      !- Begin Day of Month\n"
        "    ,                        !- Begin Year\n"
        "    7,                       !- End Month\n"
        "    15,                      !- End Day of Month\n"
        "    ,                        !- End Year\n"
        "    Tuesday,                 !- Day of Week for Start Day\n"
        "    Yes,                     !- Use Weather File Holidays and Special Days\n"
        "    Yes,                     !- Use Weather File Daylight Saving Period\n"
        "    No,                      !- Apply Weekend Holiday Rule\n"
        "    Yes,                     !- Use Weather File Rain Indicators\n"
        "    Yes;                     !- Use Weather File Snow Indicators\n"
    )
    text = re.sub(
        r"  RunPeriod,[\s\S]*?Yes;\s*\n",
        run_period,
        text,
        count=1,
    )

    if "Output:SQLite" not in text:
        text += (
            "\n  Output:SQLite,\n"
            "    SimpleAndTabular;\n\n"
            "  Output:Variable,*,Zone Air Temperature,hourly;\n"
            "  Output:Variable,*,Zone Air System Sensible Cooling Rate,hourly;\n"
            "  Output:Variable,*,Zone Air System Sensible Heating Rate,hourly;\n"
            "  Output:Variable,*,Zone Lights Electric Power,hourly;\n"
            "  Output:Variable,*,Zone Electric Equipment Electric Power,hourly;\n"
            "  Output:Variable,*,Site Outdoor Air Drybulb Temperature,hourly;\n"
        )

    BASE_IDF.write_text(text, encoding="utf-8")
    logger.info("Prepared building model: %s", BASE_IDF)
    return BASE_IDF


def _controls_hash(controls: dict) -> str:
    payload = str(sorted(
        (k, tuple(sorted(v.items()))) for k, v in controls.items()
    ))
    return hashlib.md5(payload.encode()).hexdigest()[:12]


def _patch_cooling_schedule(idf_text: str, avg_setpoint: float) -> str:
    """Set constant cooling setpoint in Clg-SetP-Sch schedule."""
    sp = max(18.0, min(28.0, avg_setpoint))
    pattern = (
        r"(  Schedule:Compact,\s*\n\s*Clg-SetP-Sch,[\s\S]*?"
        r"Until: 24:00,)[0-9.]+(;\s*\n)"
    )
    replacement = rf"\g<1>{sp:.1f}\2"
    if re.search(pattern, idf_text):
        return re.sub(pattern, replacement, idf_text, count=1)

    # Fallback: append a override schedule block (unused if pattern missing)
    return idf_text


def _patch_lighting_fraction(idf_text: str, lighting_levels: Dict[str, float]) -> str:
    """Scale office light W/area by average lighting level fraction."""
    avg_pct = sum(lighting_levels.get(z, 80.0) for z in ZONES) / len(ZONES)
    fraction = max(0.1, min(1.0, avg_pct / 100.0))
    # OFFICE LIGHTS schedule peak is 1.0 — scale via Schedule:Constant override not trivial;
    # patch Watts/Area on SPACE1-1 Lights as proxy (all zones similar in example)
    def repl(m):
        val = float(m.group(1))
        return f"{val * fraction:.4f}"
    text = re.sub(
        r"(  Lights,\s*\n\s*SPACE1-1 Lights 1,[\s\S]*?Watts/Area,[\s\S]*?\n\s*,[\s\S]*?\n\s*,[\s\S]*?\n\s*)([0-9.]+)(,\s*\n\s*Watts per Person)",
        lambda m: m.group(1) + repl(m) + m.group(3),
        idf_text,
        count=1,
    )
    return text


class EnergyPlusSubprocessRunner:
    """Run EnergyPlus via subprocess and cache hourly real simulation data."""

    def __init__(self):
        self.ep_dir = find_energyplus_dir()
        if not self.ep_dir:
            raise RuntimeError("EnergyPlus installation not found")
        self.ep_exe = self.ep_dir / "energyplus.exe"
        if not self.ep_exe.exists():
            self.ep_exe = self.ep_dir / "energyplus"
        self.idf_path = ensure_building_idf(self.ep_dir)
        self.weather = find_weather_file(self.ep_dir)
        self.work_dir = EP_OUTPUT
        self.hourly_cache: List[dict] = []
        self._cache_hash: Optional[str] = None
        self.total_energy_kwh = 0.0
        self.total_carbon_kg = 0.0
        self._current_hour = -1
        logger.info(
            "EnergyPlus subprocess runner ready (exe=%s, weather=%s)",
            self.ep_exe, self.weather.name,
        )

    def _write_idf(self, controls: dict) -> Path:
        text = self.idf_path.read_text(encoding="utf-8", errors="replace")
        avg_sp = sum(controls.get("hvac_setpoints", {}).values()) / max(1, len(ZONES))
        text = _patch_cooling_schedule(text, avg_sp)
        text = _patch_lighting_fraction(text, controls.get("lighting_levels", {}))
        run_idf = self.work_dir / "run.idf"
        run_idf.write_text(text, encoding="utf-8")
        return run_idf

    def run_simulation(self, controls: dict) -> List[dict]:
        """Run full-day EP simulation and return 24 hourly result dicts."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        run_idf = self._write_idf(controls)

        cmd = [
            str(self.ep_exe),
            "-w", str(self.weather),
            "-d", str(self.work_dir),
            "-r",
            str(run_idf),
        ]
        logger.info("Running EnergyPlus subprocess (1-day simulation)...")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(self.work_dir),
        )
        err_file = self.work_dir / "eplusout.err"
        if result.returncode != 0:
            err_tail = ""
            if err_file.exists():
                lines = err_file.read_text(errors="replace").splitlines()
                err_tail = "\n".join(
                    l for l in lines if "Severe" in l or "Fatal" in l
                )[:500]
            raise RuntimeError(
                f"EnergyPlus failed (exit {result.returncode}). {err_tail}"
            )

        sql_path = self.work_dir / "eplusout.sql"
        if not sql_path.exists():
            raise RuntimeError("EnergyPlus did not produce eplusout.sql")

        hourly = self._parse_sql(sql_path, controls)
        self.hourly_cache = hourly
        self._cache_hash = _controls_hash(controls)
        self.total_energy_kwh = hourly[-1]["totals"]["cumulative_energy_kwh"] if hourly else 0.0
        self.total_carbon_kg = hourly[-1]["totals"]["cumulative_carbon_kg"] if hourly else 0.0
        logger.info(
            "EnergyPlus subprocess complete: %d hours, %.1f kWh total",
            len(hourly), self.total_energy_kwh,
        )
        return hourly

    def _parse_sql(self, sql_path: Path, controls: dict) -> List[dict]:
        """
        Parse EnergyPlus 24.1.0 SQL output.
        Key differences from older EP versions:
          - ReportDataDictionary uses ReportDataDictionaryIndex (not ReportVariableDataDictionaryIndex)
          - ReportData uses TimeIndex (not Time column) + Value (not VariableValue)
          - No hourly meters in ReportMeterDataDictionary — use Chiller Electricity Rate from ReportData
          - Time table: TimeIndex is PK, IntervalType=1 for hourly, Month/Day/Hour columns
          - Zone heating comes from 'SPACE1-1 ZONE COIL' etc., not zone-level variable
          - Lighting/equipment not exported by 5ZoneAirCooled example — use physics model
        """
        conn = sqlite3.connect(sql_path)
        cur = conn.cursor()

        # ── Variable index lookup (ReportDataDictionaryIndex is the PK) ──────────
        def var_index(name: str, key: str = "") -> Optional[int]:
            if key:
                cur.execute(
                    "SELECT ReportDataDictionaryIndex FROM ReportDataDictionary "
                    "WHERE Name=? AND KeyValue=? AND ReportingFrequency='Hourly'",
                    (name, key),
                )
            else:
                cur.execute(
                    "SELECT ReportDataDictionaryIndex FROM ReportDataDictionary "
                    "WHERE Name=? AND ReportingFrequency='Hourly' LIMIT 1",
                    (name,),
                )
            row = cur.fetchone()
            return row[0] if row else None

        # ── Map EP zones to their zone coil names ────────────────────────────────
        EP_ZONE_TO_COIL = {
            "SPACE1-1": "SPACE1-1 ZONE COIL",
            "SPACE2-1": "SPACE2-1 ZONE COIL",
            "SPACE3-1": "SPACE3-1 ZONE COIL",
            "SPACE4-1": "SPACE4-1 ZONE COIL",
            "SPACE5-1": "SPACE5-1 ZONE COIL",
        }

        # Build zone-level indices
        temp_idx = {}
        cool_idx = {}
        heat_idx = {}
        for ep_zone, bms_zone in EP_ZONE_MAP.items():
            temp_idx[bms_zone] = var_index("Zone Air Temperature", ep_zone)
            cool_idx[bms_zone] = var_index("Zone Air System Sensible Cooling Rate", ep_zone)
            heat_idx[bms_zone] = var_index("Heating Coil Heating Rate", EP_ZONE_TO_COIL[ep_zone])

        outdoor_idx = var_index("Site Outdoor Air Drybulb Temperature", "Environment")
        chiller_idx = var_index("Chiller Electricity Rate", "CENTRAL CHILLER")

        # ── Get the 24 hourly TimeIndex values for July 15 ───────────────────────
        cur.execute(
            "SELECT TimeIndex, Hour FROM Time "
            "WHERE IntervalType=1 AND Month=7 AND Day=15 "
            "ORDER BY Hour"
        )
        time_rows = cur.fetchall()
        if not time_rows:
            # Fallback: first 24 hourly rows in the dataset
            cur.execute(
                "SELECT TimeIndex, Hour FROM Time "
                "WHERE IntervalType=1 "
                "ORDER BY TimeIndex LIMIT 24"
            )
            time_rows = cur.fetchall()

        # ── Load series: TimeIndex → value ───────────────────────────────────────
        def series(idx: Optional[int]) -> Dict[int, float]:
            if idx is None:
                return {}
            cur.execute(
                "SELECT TimeIndex, Value FROM ReportData "
                "WHERE ReportDataDictionaryIndex=? ORDER BY TimeIndex",
                (idx,),
            )
            return {t: v for t, v in cur.fetchall()}

        temp_series    = {z: series(temp_idx[z]) for z in ZONES}
        cool_series    = {z: series(cool_idx[z]) for z in ZONES}
        heat_series    = {z: series(heat_idx[z]) for z in ZONES}
        outdoor_series = series(outdoor_idx)
        chiller_series = series(chiller_idx)
        conn.close()

        # Physics-based lighting + equipment (5ZoneAirCooled doesn't export these hourly)
        from simulation.building_sim import (
            MAX_OCCUPANCY, CO2_AMBIENT,
            ZONE_AREA, MAX_LIGHTING_DENSITY, EQUIPMENT_DENSITY,
        )

        hourly: List[dict] = []
        cum_energy = 0.0
        cum_carbon = 0.0

        for hour_idx, (time_idx, ep_hour) in enumerate(time_rows[:24]):
            # EP hours are 1–24; map to 0–23 for physics model
            hour = float(ep_hour - 1)
            occ_frac = occupancy_fraction(hour)
            t_out = outdoor_series.get(time_idx, outdoor_temperature(hour))

            zone_results = {}
            total_hvac_kw  = 0.0
            total_light_kw = 0.0
            total_equip_kw = 0.0

            for z in ZONES:
                temp   = temp_series[z].get(time_idx, 22.0)
                cool_w = max(0.0, cool_series[z].get(time_idx, 0.0))
                heat_w = max(0.0, heat_series[z].get(time_idx, 0.0))
                # Convert thermal loads to electricity: cooling COP=3.2, heating COP=1
                hvac_kw = cool_w / (3.2 * 1000.0) + heat_w / 1000.0

                light_pct = controls.get("lighting_levels", {}).get(z, 80.0) / 100.0
                light_kw  = ZONE_AREA[z] * MAX_LIGHTING_DENSITY * light_pct / 1000.0
                equip_kw  = ZONE_AREA[z] * EQUIPMENT_DENSITY * occ_frac / 1000.0

                pmv = calculate_pmv(temp)
                occ = max(0, int(MAX_OCCUPANCY[z] * occ_frac))
                vent = controls.get("ventilation_rates", {}).get(z, 0.01)
                co2_ss = CO2_AMBIENT + (occ * 3500) / max(0.1, vent * max(1, occ) * 3600)
                co2 = min(2500.0, co2_ss)

                zone_results[z] = {
                    "temperature":  round(temp, 2),
                    "pmv":          pmv,
                    "co2_ppm":      round(co2, 1),
                    "occupancy":    occ,
                    "hvac_kw":      round(hvac_kw, 3),
                    "lighting_kw":  round(light_kw, 3),
                    "equipment_kw": round(equip_kw, 3),
                }
                total_hvac_kw  += hvac_kw
                total_light_kw += light_kw
                total_equip_kw += equip_kw

            # Use chiller electricity (whole-building HVAC signal) if available
            chiller_kw = chiller_series.get(time_idx, 0.0) / 1000.0
            energy_kwh = (
                chiller_kw + total_light_kw + total_equip_kw
                if chiller_kw > 0
                else total_hvac_kw + total_light_kw + total_equip_kw
            )

            carbon_kg   = energy_kwh * CARBON_FACTOR
            cum_energy += energy_kwh
            cum_carbon += carbon_kg

            avg_temp = round(sum(zone_results[z]["temperature"] for z in ZONES) / len(ZONES), 2)
            avg_pmv  = round(sum(zone_results[z]["pmv"]         for z in ZONES) / len(ZONES), 2)
            avg_co2  = round(sum(zone_results[z]["co2_ppm"]     for z in ZONES) / len(ZONES), 1)

            hourly.append({
                "hour":              hour,
                "outdoor_temp":      round(t_out, 1),
                "occupancy_fraction": round(occ_frac, 2),
                "zones":             zone_results,
                "totals": {
                    "hvac_kw":               round(total_hvac_kw, 2),
                    "lighting_kw":           round(total_light_kw, 2),
                    "equipment_kw":          round(total_equip_kw, 2),
                    "total_kw":              round(total_hvac_kw + total_light_kw + total_equip_kw, 2),
                    "energy_kwh":            round(energy_kwh, 2),
                    "carbon_kg":             round(carbon_kg, 3),
                    "cumulative_energy_kwh": round(cum_energy, 2),
                    "cumulative_carbon_kg":  round(cum_carbon, 3),
                },
                "comfort": {
                    "avg_temp":      avg_temp,
                    "avg_pmv":       avg_pmv,
                    "avg_co2":       avg_co2,
                    "comfort_score": _comfort_score(avg_pmv, avg_co2),
                },
                "_source": "energyplus",
            })

        return hourly

    def step(self, hour: float, controls: dict) -> dict:
        """Return real EP data for the given hour; re-run when controls change."""
        h = int(hour)
        chash = _controls_hash(controls)
        if chash != self._cache_hash or not self.hourly_cache:
            self.run_simulation(controls)

        if h >= len(self.hourly_cache):
            h = len(self.hourly_cache) - 1
        result = dict(self.hourly_cache[h])
        result["hour"] = hour
        # Update cumulative totals to match step position
        self.total_energy_kwh = self.hourly_cache[h]["totals"]["cumulative_energy_kwh"]
        self.total_carbon_kg = self.hourly_cache[h]["totals"]["cumulative_carbon_kg"]
        return result

    def reset(self):
        self.hourly_cache = []
        self._cache_hash = None
        self.total_energy_kwh = 0.0
        self.total_carbon_kg = 0.0
        self._current_hour = -1
