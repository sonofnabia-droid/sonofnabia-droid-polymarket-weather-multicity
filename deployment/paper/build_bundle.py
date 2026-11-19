#!/usr/bin/env python3
"""Build a bounded, PAPER-only source/model archive without touching live state."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(os.environ.get("PAPER_BUNDLE_DIR", "/tmp")).resolve()
MAX_ARCHIVE_BYTES = 1024**3
MIN_FREE_AFTER_BYTES = 8 * 1024**3

CORE_FILES = [
    "requirements.txt", "cassiopeia_live_bot.py", "cassiopeia_entry.py",
    "cassiopeia_predictor.py", "predictor.py", "cassiopeia_backtester.py",
    "cassiopeia_params.py", "cassiopeia_strategy.py", "polymarket_clob.py",
    "polymarket_clob_redeem_patch.py", "clob_sizing.py", "resolution_rules.py",
    "official_resolution.py", "weather.py", "weather_v3.py", "metar.py",
    "v6_filter.py", "v6_breaker.py", "v6_gamma_check.py",
    "trade_ledger.py", "tick_logger.py",
    "opportunity_logger.py", "tg.py", "display.py", "city_groups.py",
    "ask_collector.py", "polymarket_weather_archive.py",
    "wu_key_guard.py", "cities/config.py", "cities/__init__.py",
    "cities_active.txt", "cassiopeia_active_config.json", "icao_coords.json",
    "PAPER_DEPLOYMENT_2026-11-18.md", ".gitignore",
    "deployment/paper/README.md", "deployment/paper/fleet.json",
    "deployment/paper/build_bundle.py", "deployment/paper/launch_fleet.py",
    "deployment/paper/launch_collectors.py", "deployment/paper/pm_books_collector.py",
    "deployment/paper/start_all_paper.sh", "deployment/paper/start_collectors.sh",
]


def launcher_cities(path: str, variable: str, prefix: str) -> list[str]:
    for line in (ROOT / path).read_text().splitlines():
        if line.startswith(variable + "="):
            value = line.split("=", 1)[1].strip().strip('"')
            if value.startswith("${") and ":-" in value:
                value = value.split(":-", 1)[1].split("}", 1)[0]
            if not value or "$" in value:
                raise ValueError(f"Could not resolve {variable} from {path}")
            return [city.strip() for city in value.split(",") if city.strip()]
    raise ValueError(f"Missing {variable} in {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_file_list() -> tuple[dict[str, Path], dict[str, list[str]], dict[str, list[str]], dict]:
    fleet = json.loads((ROOT / "deployment/paper/fleet.json").read_text(encoding="utf-8"))
    city_sets = fleet.get("city_sets", {})
    bots = {bot["id"]: bot for bot in fleet.get("bots", [])}
    cities_a = city_sets.get("all_cities")
    if not isinstance(cities_a, list) or not cities_a or len(set(cities_a)) != len(cities_a):
        raise ValueError("fleet.json city_sets.all_cities vazio ou com duplicados")
    for bot_id in ("A", "B", "C", "D"):
        if bot_id not in bots or bots[bot_id].get("mode") != "paper":
            raise ValueError(f"fleet.json tem configuração PAPER inválida para {bot_id}")
    if "E" not in bots or bots["E"].get("mode") != "real" or bots["E"].get("enabled") or bots["E"].get("launchable") is not False:
        raise ValueError("E/REAL tem de permanecer desativado e não lançável")
    cities_b = launcher_cities("start_paper_v6.sh", "CITIES_B", "B")
    cities_c = launcher_cities("start_andromeda_c.sh", "CITIES_C", "C")
    cities_d = launcher_cities("start_micro_paper.sh", "CITIES_M_PAPER", "D")
    source_scopes = {"A": cities_a, "B": cities_b, "C": cities_c, "D": cities_d}
    scopes = {bot_id: city_sets[bots[bot_id]["city_set"]] for bot_id in ("A", "B", "C", "D")}
    if any(scope != cities_a for scope in scopes.values()):
        raise ValueError("A-D têm de apontar para o mesmo city_set para este pacote all-cities")
    paths: dict[str, Path] = {}

    def include(rel: str, optional: bool = False) -> None:
        path = ROOT / rel
        if not path.is_file():
            if optional:
                return
            raise FileNotFoundError(f"Required bundle file missing: {rel}")
        paths[rel] = path

    for rel in CORE_FILES:
        include(rel)
    for path in sorted((ROOT / "modules").glob("*.py")):
        include(path.relative_to(ROOT).as_posix())

    for city in cities_a:
        include(f"historic/{city}.csv")
        include(f"cities/{city}/strategy_config_{city}.json", optional=True)
        include(f"cities/{city}/{city}_peak_model/lgbm_peak.pkl")
        include(f"cities/{city}/{city}_peak_model/peak_model_config.json")
        include(f"cities/{city}/cassiopeia_rebound_model/lgbm_rebound.pkl")
        include(f"cities/{city}/cassiopeia_rebound_model/rebound_model_config.json")

    # All four deployed PAPER variants observe the same 34-city universe.
    # F1 reports with gate_pass=false remain included and fail closed at runtime.
    for city in cities_a:
        include(f"cities/{city}/v5_quantile_model/f1_report.json")
        include(f"cities/{city}/v5_quantile_model/quantiles.pkl")
        include(f"cities/{city}/v5_quantile_model/atom_classifier.pkl")

    return paths, scopes, source_scopes, fleet


def main() -> int:
    paths, scopes, source_scopes, fleet = build_file_list()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(OUT_DIR)
    if usage.free < MIN_FREE_AFTER_BYTES + 64 * 1024**2:
        raise RuntimeError(
            f"Refusing to build: free disk is {usage.free / 1024**3:.2f} GiB; "
            f"the required reserve is {MIN_FREE_AFTER_BYTES / 1024**3:.0f} GiB plus buffer."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = OUT_DIR / f"cassiopeia-paper-{stamp}.tar.gz"
    if archive.exists():
        raise FileExistsError(archive)
    stage_name = "cassiopeia-paper"
    entries = []
    for rel, path in sorted(paths.items()):
        entries.append({"path": rel, "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "created_utc": stamp,
        "purpose": "paper-only deployment; no secrets, live state, database, or REAL launcher",
        "scopes": scopes,
        "source_scopes": source_scopes,
        "collectors": fleet.get("collectors", {}),
        "fleet_bots": [{"id": b["id"], "mode": b["mode"],
                        "enabled": bool(b.get("enabled")), "host": b.get("host"),
                        "cities": scopes[b["id"]] if b["id"] in scopes else b.get("cities", [])}
                       for b in fleet.get("bots", [])],
        "files": entries,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()

    fd, partial_name = tempfile.mkstemp(prefix=f".{archive.name}.", suffix=".partial", dir=OUT_DIR)
    os.close(fd)
    partial = Path(partial_name)
    try:
        with tarfile.open(partial, mode="w:gz", compresslevel=6) as tar:
            for rel, path in sorted(paths.items()):
                tar.add(path, arcname=f"{stage_name}/{rel}", recursive=False)
            info = tarfile.TarInfo(f"{stage_name}/BUNDLE_MANIFEST.json")
            info.size = len(manifest_bytes)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            import io
            tar.addfile(info, io.BytesIO(manifest_bytes))
        size = partial.stat().st_size
        remaining = shutil.disk_usage(OUT_DIR).free
        if size > MAX_ARCHIVE_BYTES:
            raise RuntimeError(f"Archive exceeded 1 GiB safety cap ({size} bytes).")
        if remaining < MIN_FREE_AFTER_BYTES:
            raise RuntimeError(
                f"Refusing to keep archive: remaining free space would be "
                f"{remaining / 1024**3:.2f} GiB, below the 8 GiB reserve."
            )
        os.replace(partial, archive)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    digest = sha256(archive)
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {archive.name}\n")
    print(json.dumps({
        "archive": str(archive), "size_bytes": archive.stat().st_size,
        "sha256": digest, "file_count": len(entries) + 1,
        "scope_sizes": {key: len(value) for key, value in scopes.items()},
        "free_after_gib": round(shutil.disk_usage(OUT_DIR).free / 1024**3, 2),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
