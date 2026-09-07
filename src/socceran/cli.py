"""Command-line interface: fetch / update / predict."""

from __future__ import annotations

import argparse
import logging
import sys

from socceran.config import load_config, season_codes
from socceran.data import fetch_all, load_matches
from socceran.predict import predict, write_predictions
from socceran.update import update


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    seasons = season_codes(cfg)
    print(f"Seasons: {', '.join(seasons)}")
    print(f"Leagues: {', '.join(cfg['leagues'].keys())}")
    paths = fetch_all(cfg, force=args.force)
    print(f"OK: {len(paths)} CSV file(s) in cache")
    for p in paths:
        print(f"  - {p.name}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    elo, model, n = update(cfg, do_fetch=not args.no_fetch, force_fetch=args.force)
    print(f"OK: fitted on {n} matches; {len(elo.ratings)} Elo keys; "
          f"{len(model.attack)} attack ratings")
    print(f"  Elo → {cfg['paths']['elo_state']}")
    print(f"  Poisson → {cfg['paths']['poisson_state']}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    matches = load_matches(cfg)
    if matches.empty:
        print("No matches loaded. Run `socceran fetch` then `socceran update` first.", file=sys.stderr)
        return 1
    df = predict(cfg, matches=matches, mode=args.mode)
    csv_path, json_path = write_predictions(df, cfg)
    print(f"OK: {len(df)} predictions")
    print(f"  CSV  → {csv_path}")
    print(f"  JSON → {json_path}")
    if not df.empty:
        print(df[["league", "home", "away", "p_home", "p_draw", "p_away", "xg_home", "xg_away"]]
              .head(10)
              .to_string(index=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    matches = load_matches(cfg)
    print(f"matches cached: {len(matches)}")
    if not matches.empty:
        print(f"date range: {matches['date'].min()} → {matches['date'].max()}")
        print(matches.groupby("league").size().rename("n").to_string())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="socceran", description="Poisson + Elo football baseline")
    p.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="Download football-data.co.uk CSVs")
    f.add_argument("--force", action="store_true", help="Re-download even if cached")
    f.set_defaults(func=cmd_fetch)

    u = sub.add_parser("update", help="Fetch (optional) + fit Elo + Poisson")
    u.add_argument("--no-fetch", action="store_true", help="Skip download step")
    u.add_argument("--force", action="store_true", help="Force re-download")
    u.set_defaults(func=cmd_update)

    pr = sub.add_parser("predict", help="Write predictions CSV/JSON under out/")
    pr.add_argument(
        "--mode",
        choices=("recent", "hypothetical"),
        default="recent",
        help="recent=score latest matches; hypothetical=each team as home vs last opp",
    )
    pr.set_defaults(func=cmd_predict)

    s = sub.add_parser("status", help="Show cached match stats")
    s.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
