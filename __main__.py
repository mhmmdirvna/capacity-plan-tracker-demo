"""Command line: python -m cptracker <command>

  login                 buka Edge profil bot ke MPM untuk login SSO sekali
  master <file.xlsx>    validasi lalu aktifkan master data baru (berlaku mulai run berikutnya)
  run                   satu run: baca msForm + MPM, hitung status ke staging
  publish               publish run terakhir ke dashboard
  scheduled             dipanggil Task Scheduler tiap interval: run, lalu publish bila sudah jamnya
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
from datetime import datetime

from .config import load_config
from .master_data import MasterDataError, load_master_data
from .pipeline import publish, run_once
from .scraper import MpmScraper
from .store import Store


def _now(cfg) -> datetime:
    return datetime.now(cfg.tz)


def _master(cfg, store):
    path = store.active_master_path()
    if not path:
        sys.exit("Belum ada master data aktif. Jalankan: python -m cptracker master <file.xlsx>")
    return load_master_data(cfg.root / path if not path.startswith("/") else path)


def cmd_master(cfg, store, args):
    now = _now(cfg)
    try:
        md = load_master_data(args.file)
    except MasterDataError as exc:
        store.add_error(store.start_run("master", now), "E-MASTER",
                        f"Master data ditolak: {len(exc.errors)} error. Master data lama tetap dipakai.", now)
        print(f"DITOLAK ({len(exc.errors)} error):")
        for e in exc.errors:
            print(" -", e)
        return 1
    with open(args.file, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    target_dir = cfg.root / "data" / "master_versions"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{now:%Y%m%d_%H%M%S}_{digest[:8]}.xlsx"
    shutil.copy2(args.file, target)
    summary = f"{len(md.apps)} aplikasi ({len(md.live_apps())} Live), {len(md.templates)} departemen"
    store.add_master_version(now, args.by, digest, str(target.relative_to(cfg.root)), summary)
    print("Lolos validasi:", summary)
    for w in md.warnings:
        print(" ! peringatan:", w)
    return 0


def cmd_run(cfg, store, args):
    md = _master(cfg, store)
    with MpmScraper(cfg) as scraper:
        s = run_once(cfg, store, md, scraper, _now(cfg))
    print(f"run {s.run_id}: {s.responses_new} response baru, {s.docs_read} dokumen dibaca, error: {s.errors or '-'}")
    return 1 if s.stopped else 0


def cmd_publish(cfg, store, args):
    rid = publish(store, _now(cfg))
    print(f"published run {rid}" if rid else "publish gagal: belum ada run selesai")
    return 0 if rid else 1


def cmd_scheduled(cfg, store, args):
    code = cmd_run(cfg, store, args)
    now = _now(cfg)
    window = int(cfg.settings["schedule"]["read_interval_minutes"])
    for hhmm in cfg.settings["schedule"]["publish_times"]:
        h, m = map(int, hhmm.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if 0 <= (now - target).total_seconds() < window * 60:
            cmd_publish(cfg, store, args)
            break
    return code


def cmd_login(cfg, store, args):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(cfg.path("edge_profile")), channel="msedge", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg.settings["mpm_home_url"])
        input("Login di jendela Edge sampai halaman MPM terbuka, lalu tekan Enter di sini...")
        ctx.close()
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="cptracker")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    m = sub.add_parser("master")
    m.add_argument("file")
    m.add_argument("--by", default="Admin")
    sub.add_parser("run")
    sub.add_parser("publish")
    sub.add_parser("scheduled")
    args = p.parse_args(argv)
    cfg = load_config()
    store = Store(cfg.path("database"))
    return {"login": cmd_login, "master": cmd_master, "run": cmd_run, "publish": cmd_publish,
            "scheduled": cmd_scheduled}[args.cmd](cfg, store, args)


if __name__ == "__main__":
    sys.exit(main())
