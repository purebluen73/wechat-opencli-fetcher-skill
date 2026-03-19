---
name: wechat-opencli-fetcher
description: Search, resolve, and fetch WeChat official account articles via opencli plus WeSpy, turning Sogou Weixin results into retry-safe markdown/json corpora. Use when the user asks to scrape a 公众号, batch download recent WeChat articles, fetch `mp.weixin.qq.com` posts through the Chrome login session, or build a reusable local corpus from Sogou Weixin search results.
---

# Wechat Opencli Fetcher

## Overview

Use `scripts/scrape_wechat_articles.py` as the default entrypoint.

The script installs the bundled `sogouwx` opencli templates into `~/.opencli/clis/sogouwx`, searches Sogou Weixin in a real browser, resolves redirect links to the final WeChat article URLs, normalizes `wappoc_appmsgcaptcha` middle pages back to `target_url`, and calls WeSpy to save markdown plus `_info.json`.

## Requirements

- `opencli doctor --live` should already pass.
- Chrome should already be logged into the needed account context.
- WeSpy must be available. If autodiscovery fails, pass `--wespy-python` and `--wespy-wrapper`.
- Use a dedicated `--output-dir` per account or per run family so cache files stay easy to reason about.

## Workflow

1. Choose a broad `--query` and, when possible, an exact `--account-name`.
2. Point `--output-dir` at the corpus directory you want.
3. Run the scraper.
4. Read `_meta/summary.json`, then inspect `_meta/resolve_failures.json` or `_meta/fetch_failures.json` only if counts are non-zero.

### Recent two-year corpus

```bash
python3 scripts/scrape_wechat_articles.py \
  --query "示例公众号" \
  --account-name "示例公众号" \
  --output-dir /absolute/path/to/output \
  --days-back 730
```

### Explicit date window

```bash
python3 scripts/scrape_wechat_articles.py \
  --query "某个公众号" \
  --account-name "某个公众号" \
  --output-dir /absolute/path/to/output \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
```

## Operating Rules

- Do not parallelize `opencli` browser commands. Search and resolve should stay serial.
- Default to cache reuse. Add `--refresh-search` only when search results truly need to be regenerated.
- Treat `resolve_failures.json` and `fetch_failures.json` as expected control files, not immediate fatal errors.
- If the user wants a specific account, always pass exact `--account-name` filtering instead of trusting query text alone.
- Keep the bundled `assets/opencli-clis/sogouwx/*.yaml` as the source of truth for the opencli site definition.

## Resources

- `scripts/scrape_wechat_articles.py`: generic batch scraper.
- `assets/opencli-clis/sogouwx/search.yaml`: browser-backed Sogou Weixin search template.
- `assets/opencli-clis/sogouwx/resolve.yaml`: browser-backed Sogou redirect resolver.
