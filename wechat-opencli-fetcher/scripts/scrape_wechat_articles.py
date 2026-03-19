#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo


SH_TZ = ZoneInfo("Asia/Shanghai")
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SOGOUWX_ASSETS_DIR = SKILL_DIR / "assets" / "opencli-clis" / "sogouwx"
DEFAULT_OPENCLI = shutil.which("opencli") or "/opt/homebrew/bin/opencli"
DEFAULT_WESPY_PY_CANDIDATES = [
    Path.home() / "Documents/QNSZ/project/WeSpy/.venv/bin/python",
]
DEFAULT_WESPY_WRAPPER_CANDIDATES = [
    Path.home() / ".codex/skills/wespy-fetcher/scripts/wespy_cli.py",
    Path.home() / ".claude/skills/wespy-fetcher/scripts/wespy_cli.py",
]


@dataclass
class RunConfig:
    query: str
    account_name: str | None
    start_date: date
    end_date: date
    max_pages: int
    page_limit: int
    resolve_sleep: float
    fetch_sleep: float
    resolve_retries: int
    fetch_retries: int
    skip_fetch: bool
    refresh_search: bool
    opencli_bin: str
    wespy_python: Path
    wespy_wrapper: Path
    output_dir: Path
    site_name: str


def run_json_command(cmd: list[str]) -> list[dict]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    stdout = proc.stdout.strip()
    if not stdout:
        return []
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"JSON parse failed for command: {' '.join(cmd)}\nSTDOUT:\n{stdout}\nSTDERR:\n{proc.stderr}"
        ) from exc
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    raise RuntimeError(f"Unexpected JSON payload type: {type(payload).__name__}")


def run_plain_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def first_existing_path(candidates: Iterable[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_existing_path(label: str, explicit: str | None, env_name: str, candidates: Iterable[Path]) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"{label} not found: {path}")
        return path
    env_raw = None
    try:
        import os

        env_raw = os.environ.get(env_name)
    except Exception:  # noqa: BLE001
        env_raw = None
    if env_raw:
        path = Path(env_raw).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"{label} from {env_name} not found: {path}")
        return path
    discovered = first_existing_path(candidates)
    if discovered is None:
        raise RuntimeError(
            f"{label} not found. Pass --{label.replace('_', '-')} or set {env_name}."
        )
    return discovered.resolve()


def ensure_opencli_site_installed(site_name: str) -> None:
    if not SOGOUWX_ASSETS_DIR.exists():
        raise RuntimeError(f"Missing local opencli assets: {SOGOUWX_ASSETS_DIR}")
    target_dir = Path.home() / ".opencli" / "clis" / site_name
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(SOGOUWX_ASSETS_DIR.glob("*.yaml")):
        target = target_dir / source.name
        if target.exists() and target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"):
            continue
        shutil.copy2(source, target)


def ensure_output_dirs(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = output_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, meta_dir


def save_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_publish_dt(item: dict) -> datetime | None:
    ts = item.get("publish_ts")
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=SH_TZ)


def collect_search_results(config: RunConfig) -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    query_encoded = quote(config.query, safe="")
    for page in range(1, config.max_pages + 1):
        cmd = [
            config.opencli_bin,
            config.site_name,
            "search",
            "--query_encoded",
            query_encoded,
            "--page",
            str(page),
            "--limit",
            str(config.page_limit),
            "-f",
            "json",
        ]
        rows = run_json_command(cmd)
        if not rows:
            break
        new_count = 0
        for row in rows:
            sogou_url = row.get("sogou_url")
            if not sogou_url or sogou_url in seen_urls:
                continue
            seen_urls.add(sogou_url)
            row["page"] = page
            row["query"] = config.query
            results.append(row)
            new_count += 1
        if new_count == 0:
            break
    return results


def filter_candidates(items: Iterable[dict], *, account_name: str | None, start_date: date, end_date: date) -> list[dict]:
    filtered: list[dict] = []
    for item in items:
        account = (item.get("account") or "").strip()
        if account_name and account != account_name:
            continue
        publish_dt = parse_publish_dt(item)
        if publish_dt is None:
            continue
        publish_date = publish_dt.date()
        if start_date <= publish_date <= end_date:
            item["publish_date_shanghai"] = publish_date.isoformat()
            filtered.append(item)
    filtered.sort(key=lambda row: int(row["publish_ts"]), reverse=True)
    return filtered


def normalize_final_url(final_url: str) -> tuple[str, bool]:
    parsed = urlparse(final_url)
    if parsed.path != "/mp/wappoc_appmsgcaptcha":
        return final_url, False
    target_url = parse_qs(parsed.query).get("target_url", [""])[0]
    if not target_url:
        return final_url, False
    return target_url, True


def resolve_one(config: RunConfig, sogou_url: str) -> dict:
    cmd = [config.opencli_bin, config.site_name, "resolve", "--url", sogou_url, "-f", "json"]
    rows = run_json_command(cmd)
    if not rows:
        raise RuntimeError(f"No resolve output for URL: {sogou_url}")
    row = rows[0]
    final_url = row.get("final_url", "")
    host = row.get("host", "")
    if not final_url or host != "mp.weixin.qq.com":
        raise RuntimeError(f"Resolve did not land on mp.weixin.qq.com for URL: {sogou_url}\n{row}")
    normalized_url, normalized = normalize_final_url(final_url)
    row["final_url"] = normalized_url
    row["normalized_from_captcha"] = normalized
    return row


def fetch_one(config: RunConfig, final_url: str, output_dir: Path) -> None:
    cmd = [
        str(config.wespy_python),
        str(config.wespy_wrapper),
        final_url,
        "-o",
        str(output_dir),
        "--json",
    ]
    run_plain_command(cmd)


def retry_call(func, *, attempts: int, sleep_seconds: float, label: str) -> dict | None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"    {label} attempt {attempt}/{attempts} failed: {exc}", flush=True)
            if attempt < attempts:
                time.sleep(max(sleep_seconds * attempt, 1.0))
    if last_error is not None:
        raise last_error
    return None


def resolve_date_range(*, days_back: int, start_date_raw: str | None, end_date_raw: str | None) -> tuple[date, date]:
    today = datetime.now(SH_TZ).date()
    start_date = date.fromisoformat(start_date_raw) if start_date_raw else today - timedelta(days=days_back)
    end_date = date.fromisoformat(end_date_raw) if end_date_raw else today
    if start_date > end_date:
        raise RuntimeError(f"start_date {start_date} is after end_date {end_date}")
    return start_date, end_date


def main() -> int:
    parser = argparse.ArgumentParser(description="Search, resolve, and fetch WeChat official account articles.")
    parser.add_argument("--query", required=True, help="Search query used on Sogou Weixin.")
    parser.add_argument(
        "--account-name",
        help="Exact account name to keep. If omitted, keep every article returned by the query.",
    )
    parser.add_argument("--output-dir", required=True, help="Directory used to store markdown, info json, and _meta.")
    parser.add_argument("--days-back", type=int, default=730, help="How many days back to keep when start date is omitted.")
    parser.add_argument("--start-date", help="Inclusive start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Inclusive end date in YYYY-MM-DD.")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--page-limit", type=int, default=10)
    parser.add_argument("--resolve-sleep", type=float, default=1.0)
    parser.add_argument("--fetch-sleep", type=float, default=0.5)
    parser.add_argument("--resolve-retries", type=int, default=3)
    parser.add_argument("--fetch-retries", type=int, default=2)
    parser.add_argument("--refresh-search", action="store_true", help="Ignore cached search/candidate files and search again.")
    parser.add_argument("--skip-fetch", action="store_true", help="Stop after resolving final article URLs.")
    parser.add_argument("--site-name", default="sogouwx", help="Installed opencli site name used for search/resolve.")
    parser.add_argument("--opencli-bin", default=DEFAULT_OPENCLI, help="Path to opencli binary.")
    parser.add_argument("--wespy-python", help="Path to WeSpy virtualenv python.")
    parser.add_argument("--wespy-wrapper", help="Path to wespy_cli.py wrapper.")
    args = parser.parse_args()

    start_date, end_date = resolve_date_range(
        days_back=args.days_back,
        start_date_raw=args.start_date,
        end_date_raw=args.end_date,
    )
    wespy_python = resolve_existing_path(
        "wespy_python",
        args.wespy_python,
        "WESPY_PYTHON",
        DEFAULT_WESPY_PY_CANDIDATES,
    )
    wespy_wrapper = resolve_existing_path(
        "wespy_wrapper",
        args.wespy_wrapper,
        "WESPY_WRAPPER",
        DEFAULT_WESPY_WRAPPER_CANDIDATES,
    )
    opencli_bin = Path(args.opencli_bin).expanduser().resolve()
    if not opencli_bin.exists():
        raise RuntimeError(f"opencli binary not found: {opencli_bin}")

    ensure_opencli_site_installed(args.site_name)

    config = RunConfig(
        query=args.query,
        account_name=args.account_name,
        start_date=start_date,
        end_date=end_date,
        max_pages=args.max_pages,
        page_limit=args.page_limit,
        resolve_sleep=args.resolve_sleep,
        fetch_sleep=args.fetch_sleep,
        resolve_retries=args.resolve_retries,
        fetch_retries=args.fetch_retries,
        skip_fetch=args.skip_fetch,
        refresh_search=args.refresh_search,
        opencli_bin=str(opencli_bin),
        wespy_python=wespy_python,
        wespy_wrapper=wespy_wrapper,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        site_name=args.site_name,
    )

    output_dir, meta_dir = ensure_output_dirs(config.output_dir)
    raw_search_path = meta_dir / "search_results_raw.json"
    candidates_path = meta_dir / "candidates.json"
    resolved_path = meta_dir / "resolved_articles.json"
    fetch_log_path = meta_dir / "fetch_log.json"
    resolve_failures_path = meta_dir / "resolve_failures.json"
    fetch_failures_path = meta_dir / "fetch_failures.json"

    if config.refresh_search or not raw_search_path.exists():
        raw_search = collect_search_results(config)
        save_json(raw_search_path, raw_search)
    else:
        raw_search = load_json(raw_search_path, [])
        if not isinstance(raw_search, list):
            raise RuntimeError(f"Cached search results are not a list: {raw_search_path}")

    if config.refresh_search or not candidates_path.exists():
        candidates = filter_candidates(
            raw_search,
            account_name=config.account_name,
            start_date=config.start_date,
            end_date=config.end_date,
        )
        save_json(candidates_path, candidates)
    else:
        candidates = load_json(candidates_path, [])
        if not isinstance(candidates, list):
            raise RuntimeError(f"Cached candidates are not a list: {candidates_path}")

    resolved_cache: dict[str, dict] = {
        item["sogou_url"]: item
        for item in load_json(resolved_path, [])
        if isinstance(item, dict) and item.get("sogou_url")
    }
    fetch_cache: dict[str, dict] = {
        item["final_url"]: item
        for item in load_json(fetch_log_path, [])
        if isinstance(item, dict) and item.get("final_url")
    }
    resolve_failures: dict[str, dict] = {
        item["sogou_url"]: item
        for item in load_json(resolve_failures_path, [])
        if isinstance(item, dict) and item.get("sogou_url")
    }
    fetch_failures: dict[str, dict] = {
        item["final_url"]: item
        for item in load_json(fetch_failures_path, [])
        if isinstance(item, dict) and item.get("final_url")
    }

    fetch_rows: list[dict] = list(fetch_cache.values())

    for idx, item in enumerate(candidates, start=1):
        sogou_url = item["sogou_url"]
        publish_ts = int(item["publish_ts"])
        publish_dt = datetime.fromtimestamp(publish_ts, tz=SH_TZ).isoformat()
        print(f"[{idx}/{len(candidates)}] resolving {item['title']} ({publish_dt})", flush=True)

        resolved_entry = resolved_cache.get(sogou_url)
        if resolved_entry is None:
            try:
                resolve_row = retry_call(
                    lambda: resolve_one(config, sogou_url),
                    attempts=config.resolve_retries,
                    sleep_seconds=max(config.resolve_sleep, 1.0),
                    label="resolve",
                )
            except Exception as exc:  # noqa: BLE001
                failure_entry = {
                    "title_from_search": item["title"],
                    "account": item.get("account"),
                    "publish_ts": publish_ts,
                    "publish_time_shanghai": publish_dt,
                    "sogou_url": sogou_url,
                    "failed_at_shanghai": datetime.now(SH_TZ).isoformat(),
                    "error": str(exc),
                }
                resolve_failures[sogou_url] = failure_entry
                save_json(resolve_failures_path, list(resolve_failures.values()))
                time.sleep(max(config.resolve_sleep, 1.0))
                continue

            if resolve_row is None:
                continue

            resolved_entry = {
                "query": config.query,
                "title_from_search": item["title"],
                "account": item.get("account"),
                "publish_ts": publish_ts,
                "publish_time_shanghai": publish_dt,
                "sogou_url": sogou_url,
                "final_url": resolve_row["final_url"],
                "host": resolve_row["host"],
                "body_preview": resolve_row.get("body_preview", ""),
                "normalized_from_captcha": resolve_row.get("normalized_from_captcha", False),
                "page": item.get("page"),
            }
            resolved_cache[sogou_url] = resolved_entry
            save_json(resolved_path, list(resolved_cache.values()))
            time.sleep(config.resolve_sleep)

        final_url = resolved_entry["final_url"]
        if config.skip_fetch or final_url in fetch_cache:
            continue

        print(f"    fetching {final_url}", flush=True)
        try:
            retry_call(
                lambda: fetch_one(config, final_url, output_dir) or {"final_url": final_url},
                attempts=config.fetch_retries,
                sleep_seconds=max(config.fetch_sleep, 1.0),
                label="fetch",
            )
        except Exception as exc:  # noqa: BLE001
            failure_entry = {
                "title_from_search": item["title"],
                "publish_time_shanghai": publish_dt,
                "final_url": final_url,
                "failed_at_shanghai": datetime.now(SH_TZ).isoformat(),
                "error": str(exc),
            }
            fetch_failures[final_url] = failure_entry
            save_json(fetch_failures_path, list(fetch_failures.values()))
            time.sleep(max(config.fetch_sleep, 1.0))
            continue

        fetch_entry = {
            "query": config.query,
            "title_from_search": item["title"],
            "publish_time_shanghai": publish_dt,
            "final_url": final_url,
            "fetched_at_shanghai": datetime.now(SH_TZ).isoformat(),
        }
        fetch_cache[final_url] = fetch_entry
        fetch_rows = list(fetch_cache.values())
        save_json(fetch_log_path, fetch_rows)
        time.sleep(config.fetch_sleep)

    save_json(resolved_path, list(resolved_cache.values()))
    save_json(fetch_log_path, fetch_rows)
    save_json(resolve_failures_path, list(resolve_failures.values()))
    save_json(fetch_failures_path, list(fetch_failures.values()))

    summary = {
        "query": config.query,
        "account_name": config.account_name,
        "search_result_count": len(raw_search),
        "candidate_count": len(candidates),
        "resolved_count": len(resolved_cache),
        "resolve_failed_count": len(resolve_failures),
        "fetched_count": len(fetch_cache),
        "fetch_failed_count": len(fetch_failures),
        "start_date": config.start_date.isoformat(),
        "end_date": config.end_date.isoformat(),
        "output_dir": str(output_dir),
        "generated_at_shanghai": datetime.now(SH_TZ).isoformat(),
    }
    save_json(meta_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
