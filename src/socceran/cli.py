"""Command-line interface: fetch / update / predict / fixtures / names."""

from __future__ import annotations

import argparse
import logging
import sys

from socceran.config import load_config, season_codes
from socceran.data import fetch_all, fetch_fixtures, load_fixtures, load_matches
from socceran.predict import predict, write_predictions
from socceran.names import load_team_name_map, to_zh, use_chinese_names
from socceran.update import update


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    seasons = season_codes(cfg)
    order = (cfg.get("sources") or {}).get("order") or [
        "football_data",
        "openligadb",
        "england_mirror",
    ]
    print(f"Seasons: {', '.join(seasons)}")
    print(f"Leagues: {', '.join(cfg['leagues'].keys())}")
    print(f"Sources: {' → '.join(order)}")
    paths = fetch_all(cfg, force=args.force)
    print(f"OK: {len(paths)} result file(s) in cache")
    for p in paths:
        print(f"  - {p.name}")
    if not args.skip_fixtures:
        fx = fetch_fixtures(cfg, force=args.force)
        print(f"OK: {len(fx)} fixture file(s)")
        for p in fx:
            print(f"  - {p.name}")
    return 0


def cmd_fixtures(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    leagues = args.league.split(",") if args.league else None
    paths = fetch_fixtures(cfg, force=args.force, leagues=leagues)
    fx = load_fixtures(cfg, leagues=leagues)
    print(f"OK: {len(paths)} fixture file(s); {len(fx)} upcoming rows")
    for p in paths:
        print(f"  - {p.name}")
    if not fx.empty:
        cols = ["date", "league", "home", "away"]
        print(fx[cols].head(15).to_string(index=False))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    elo, model, n = update(cfg, do_fetch=not args.no_fetch, force_fetch=args.force)
    print(
        f"OK: fitted on {n} matches; {len(elo.ratings)} Elo keys; "
        f"{len(model.attack)} attack ratings"
    )
    print(f"  Elo → {cfg['paths']['elo_state']}")
    print(f"  Poisson → {cfg['paths']['poisson_state']}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    matches = load_matches(cfg)
    if matches.empty:
        print(
            "No matches loaded. Run `socceran fetch` then `socceran update` first.",
            file=sys.stderr,
        )
        return 1
    df = predict(cfg, matches=matches, mode=args.mode)
    csv_path, json_path = write_predictions(df, cfg)
    print(f"OK: {len(df)} predictions")
    print(f"  CSV  → {csv_path}")
    print(f"  JSON → {json_path}")
    if not df.empty:
        cols = ["league", "home", "away"]
        if use_chinese_names(cfg) and "home_zh" in df.columns:
            cols = ["league", "home", "home_zh", "away", "away_zh"]
        cols += ["kind", "p_home", "p_draw", "p_away", "xg_home", "xg_away"]
        cols = [c for c in cols if c in df.columns]
        print(df[cols].head(10).to_string(index=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    matches = load_matches(cfg)
    print(f"matches cached: {len(matches)}")
    if not matches.empty:
        print(f"date range: {matches['date'].min()} → {matches['date'].max()}")
        print(matches.groupby("league").size().rename("n").to_string())
        if "source" in matches.columns:
            print("by source:")
            print(matches.groupby("source").size().rename("n").to_string())
    fx = load_fixtures(cfg)
    print(f"upcoming fixtures: {len(fx)}")
    if not fx.empty:
        print(fx.groupby("league").size().rename("n").to_string())
    return 0


def cmd_names(args: argparse.Namespace) -> int:
    """List Chinese team-name mapping coverage."""
    m = load_team_name_map()
    zh_set = sorted(set(m.values()))
    print(f"aliases: {len(m)}  unique_zh: {len(zh_set)}")
    if args.list:
        by_zh: dict[str, list[str]] = {}
        for eng, zh in m.items():
            by_zh.setdefault(zh, []).append(eng)
        for zh in sorted(by_zh.keys()):
            aliases = ", ".join(sorted(by_zh[zh], key=str.casefold))
            print(f"{zh}: {aliases}")
    if args.query:
        print(f"{args.query!r} → {to_zh(args.query)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="socceran", description="Poisson + Elo football baseline")
    p.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="Download results (primary + fallbacks) and fixtures")
    f.add_argument("--force", action="store_true", help="Re-download even if cached")
    f.add_argument(
        "--skip-fixtures",
        action="store_true",
        help="Only fetch finished results, skip upcoming schedule",
    )
    f.set_defaults(func=cmd_fetch)

    fx = sub.add_parser("fixtures", help="Refresh upcoming OpenLigaDB fixtures only")
    fx.add_argument("--force", action="store_true", help="Re-download even if cached")
    fx.add_argument(
        "--league",
        default=None,
        help="Comma-separated league codes (default: all configured)",
    )
    fx.set_defaults(func=cmd_fixtures)

    u = sub.add_parser("update", help="Fetch (optional) + fit Elo + Poisson")
    u.add_argument("--no-fetch", action="store_true", help="Skip download step")
    u.add_argument("--force", action="store_true", help="Force re-download")
    u.set_defaults(func=cmd_update)

    pr = sub.add_parser("predict", help="Write predictions CSV/JSON under out/")
    pr.add_argument(
        "--mode",
        choices=("recent", "hypothetical", "upcoming"),
        default="recent",
        help=(
            "recent=prefer upcoming fixtures else latest matches; "
            "upcoming=fixtures only (fallback recent); "
            "hypothetical=each team as home vs last opp (if no fixtures)"
        ),
    )
    pr.set_defaults(func=cmd_predict)

    s = sub.add_parser("status", help="Show cached match / fixture stats")
    s.set_defaults(func=cmd_status)

    n = sub.add_parser("names", help="Chinese team-name mapping")
    n.add_argument("--list", action="store_true", help="Print full alias → 中文 coverage")
    n.add_argument("-q", "--query", default=None, help="Translate one team name")
    n.set_defaults(func=cmd_names)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
