# WeChat OpenCLI Fetcher Skill

Reusable skill package for scraping WeChat official account articles with `opencli` plus WeSpy.

## What it does

- Search Sogou Weixin in a real Chrome session through `opencli`
- Resolve redirect links to the real `mp.weixin.qq.com` article URL
- Normalize `wappoc_appmsgcaptcha` middle pages back to `target_url`
- Fetch article markdown and `_info.json` through WeSpy
- Reuse `_meta` caches so resume runs do not restart from page 1 every time
- Log resolve and fetch failures without aborting the whole batch

## Repository layout

- `wechat-opencli-fetcher/`: installable skill folder for Codex or Claude
- `wechat-opencli-fetcher/scripts/scrape_wechat_articles.py`: main entrypoint
- `wechat-opencli-fetcher/assets/opencli-clis/sogouwx/`: bundled opencli site templates

## Requirements

- `opencli` installed and `opencli doctor --live` passing
- Chrome already logged in
- WeSpy available locally

## Quick start

```bash
python3 wechat-opencli-fetcher/scripts/scrape_wechat_articles.py \
  --query "示例公众号" \
  --account-name "示例公众号" \
  --output-dir /absolute/path/to/output \
  --days-back 730
```

The script writes markdown files, `_info.json`, and `_meta/summary.json` into the target output directory.

## Install as a local skill

Codex:

```bash
ln -s /absolute/path/to/repo/wechat-opencli-fetcher ~/.codex/skills/wechat-opencli-fetcher
```

Claude:

```bash
ln -s /absolute/path/to/repo/wechat-opencli-fetcher ~/.claude/skills/wechat-opencli-fetcher
```

## Notes

- Keep `opencli` commands serial. Browser-backed search and resolve are intentionally not parallelized.
- Use a dedicated output directory per account or corpus.
- Add `--refresh-search` only when you truly need to rebuild Sogou search results.
