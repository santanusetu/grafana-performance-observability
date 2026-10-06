"""Load NACL Div A scorecards (one JSON file per season) into Postgres (schema `raw`).

Usage:
    .venv/bin/python ingest/load.py [file.json ...]     # default: every data/*.json

Reads DATABASE_URL (the owner connection) from .env. The load is a full
refresh inside one transaction: either every match lands or none do.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def read_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"')
    return env


def overs_to_balls(overs: str) -> int:
    whole, _, part = str(overs).partition(".")
    return int(whole or 0) * 6 + int(part or 0)


def parse_total(text: str) -> tuple[int, int, int]:
    """'Total (8 wickets, 19.4 overs) (...) 133' -> (runs, wickets, legal_balls)."""
    m = re.search(r"\((\d+) wickets?, ([\d.]+) overs?\)", text)
    if not m:
        raise ValueError(f"unparsed total: {text!r}")
    runs = int(re.search(r"(\d+)\s*$", text).group(1))
    return runs, int(m.group(1)), overs_to_balls(m.group(2))


def parse_extras(text: str) -> tuple[int, int, int, int]:
    m = re.search(r"b (\d+) lb (\d+) w (\d+) nb (\d+)", text)
    if not m:
        raise ValueError(f"unparsed extras: {text!r}")
    return tuple(int(x) for x in m.groups())


def parse_bowling_note(note: str) -> tuple[int, int]:
    """'(1 w)' -> (1, 0); '(0 w2 nb)' -> (0, 2); '' -> (0, 0)."""
    wides = re.search(r"\((\d+)\s*w", note)
    noballs = re.search(r"(\d+)\s*nb", note)
    return (int(wides.group(1)) if wides else 0, int(noballs.group(1)) if noballs else 0)


def dismissal_type(text: str) -> str:
    t = text.strip().lower()
    if not t or t.startswith("not out"):
        return "not_out"
    if t.startswith("retired"):
        return "retired"
    if t.startswith("run out"):
        return "run_out"
    if t.startswith("st "):
        return "stumped"
    if t.startswith("lbw"):
        return "lbw"
    if t.startswith("c&b") or t.startswith("c "):
        return "caught"
    if t.startswith("b "):
        return "bowled"
    return "other"


def clean_player(name: str) -> str:
    return re.sub(r"[†*]", "", name).strip()


def parse_result(result: str, team1: str, team2: str) -> tuple[str | None, str | None, bool, bool]:
    super_over = "super over" in result.lower()
    m = re.search(r"Winner:\s*(.+)$", result)
    if m:
        winner = m.group(1).strip()
        return winner, "won the Super Over", True, super_over
    for team in (team1, team2):
        m = re.search(re.escape(team) + r"\s+(won by .+)$", result)
        if m:
            return team, m.group(1).strip(), False, super_over
    tied = "tie" in result.lower()
    return None, ("tied" if tied else None), tied, super_over


def build_rows(data: dict) -> dict[str, list[tuple]]:
    rows = {k: [] for k in ("matches", "innings", "batting", "bowling", "overs")}
    for m in data["matches"]:
        inns = m["innings"]
        if len(inns) != 2:
            raise ValueError(f"match {m['match_id']}: expected 2 innings, got {len(inns)}")
        t1, t2 = inns[0]["team"], inns[1]["team"]
        winner, margin, tied, super_over = parse_result(m["result"], t1, t2)
        if winner is None and not tied:
            raise ValueError(f"match {m['match_id']}: could not find a winner in {m['result']!r}")
        rows["matches"].append((
            m["match_id"], data["league"], m["stage"],
            datetime.strptime(m["date"], "%m/%d/%Y").date(),
            t1, t2, winner, margin, tied, super_over, m["result"],
        ))

        for no, inn in enumerate(inns, start=1):
            runs, wkts, balls = parse_total(inn["total"])
            b, lb, w, nb = parse_extras(inn["extras"])
            bowling_team = t2 if no == 1 else t1
            rows["innings"].append((m["match_id"], no, inn["team"], bowling_team, runs, wkts, balls, b, lb, w, nb))

            for pos, bat in enumerate(inn["batting"], start=1):
                rows["batting"].append((
                    m["match_id"], no, pos, clean_player(bat["name"]), bat["dismissal"],
                    dismissal_type(bat["dismissal"]), bat["runs"], bat["balls"], bat["fours"], bat["sixes"],
                ))
            for spell, bowl in enumerate(inn["bowling"], start=1):
                wides, noballs = parse_bowling_note(bowl["extras_note"])
                rows["bowling"].append((
                    m["match_id"], no, spell, clean_player(bowl["name"]), overs_to_balls(bowl["overs"]),
                    bowl["maidens"], bowl["dots"], bowl["runs"], bowl["wickets"], wides, noballs,
                ))

            obo = next((o for o in m["over_by_over"] if o["batting_team"] == inn["team"]), None)
            if obo is None:
                raise ValueError(f"match {m['match_id']}: no over-by-over for {inn['team']}")
            prev_wkts = 0
            for over in obo["overs"]:
                cum_runs, cum_wkts = (int(x) for x in over["score"].split("/"))
                rows["overs"].append((
                    m["match_id"], no, over["over"], over["runs"], cum_runs, cum_wkts, cum_wkts - prev_wkts,
                ))
                prev_wkts = cum_wkts
    return rows


INSERTS = {
    "matches": "INSERT INTO raw.matches VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "innings": "INSERT INTO raw.innings VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "batting": "INSERT INTO raw.batting VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "bowling": "INSERT INTO raw.bowling VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "overs": ("INSERT INTO raw.overs (match_id, innings_no, over_no, runs, cum_runs, cum_wickets, wickets) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s)"),
}


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or sorted(DATA_DIR.glob("*.json"))
    env = read_env(ROOT / ".env")
    url = os.environ.get("DATABASE_URL") or env["DATABASE_URL"]

    rows = {k: [] for k in INSERTS}
    for path in paths:
        part = build_rows(json.loads(path.read_text()))
        for k in rows:
            rows[k].extend(part[k])
        print(f"parsed {path.name}: {len(part['matches'])} matches")

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "01_schema.sql").read_text())
        cur.execute("TRUNCATE raw.matches CASCADE")
        for table in ("matches", "innings", "batting", "bowling", "overs"):
            cur.executemany(INSERTS[table], rows[table])
        cur.execute((ROOT / "db" / "02_views.sql").read_text())
        conn.commit()

    print("loaded:", ", ".join(f"{k}={len(v)}" for k, v in rows.items()))


if __name__ == "__main__":
    main()
