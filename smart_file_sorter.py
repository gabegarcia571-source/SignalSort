import hashlib
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, scrolledtext

try:
    from classifier import apply_classification, load_taxonomy, run_dry_run, run_from_report, write_report

    CLASSIFIER_AVAILABLE = True
except ImportError:
    CLASSIFIER_AVAILABLE = False

scan_dirs = [Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents"]

base_dir = Path(r"C:\Users\12022\Downloads\Full Organization")
duplicates_dir = base_dir / "_Duplicates"
other_dir = base_dir / "_Other"
project_root = base_dir / "By_Project"

SCHEDULE_DAY = "MON"
SCHEDULE_TIME = "12:00"
TASK_NAME = "SmartFileSorter"

rules = {
    "Code/Python": [".py", ".ipynb"],
    "Code/R": [".r", ".rmd"],
    "Code/Stata": [".do"],
    "Data": [".csv", ".xlsx", ".xls", ".dta", ".parquet", ".json"],
    "Papers_PDFs": [".pdf"],
    "Text_Documents": [".docx", ".doc", ".txt", ".rtf"],
    "Presentations": [".pptx", ".ppt"],
    "Images": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "Markdown": [".md"],
    "Calendar_Email": [".ics", ".eml"],
    "Installers": [".exe", ".msi"],
    "Web_Files": [".html", ".htm"],
}


def get_file_hash(file_path):
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def safe_destination(folder, filename):
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    destination = folder / filename
    counter = 1
    while destination.exists():
        destination = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return destination


def run_sort(log_callback, done_callback):
    seen_hashes = {}
    stats = {"moved": 0, "duplicates": 0, "skipped": 0, "errors": 0, "other": 0}

    for category in rules:
        (base_dir / category).mkdir(parents=True, exist_ok=True)
    duplicates_dir.mkdir(parents=True, exist_ok=True)
    other_dir.mkdir(parents=True, exist_ok=True)

    log_callback("=" * 48)
    log_callback("  Smart File Organizer — Starting...")
    log_callback(f"  Output folder: {base_dir}")
    log_callback("=" * 48)

    for folder in scan_dirs:
        if not folder.exists():
            log_callback(f"\n[!] Folder not found, skipping: {folder}")
            continue

        log_callback(f"\nScanning: {folder}")

        for item in folder.iterdir():
            if not item.is_file():
                continue

            if item.name.startswith("."):
                stats["skipped"] += 1
                continue

            ext = item.suffix.lower()

            target_category = None
            for category, extensions in rules.items():
                if ext in extensions:
                    target_category = category
                    break

            if target_category is None:
                destination = safe_destination(other_dir, item.name)
                try:
                    shutil.move(str(item), str(destination))
                    log_callback(f"OTHER: {item.name} → _Other/")
                    stats["other"] += 1
                except Exception as e:
                    log_callback(f"LOCKED/ERROR: {item.name} — {e}")
                    stats["errors"] += 1
                continue

            file_hash = get_file_hash(item)
            if file_hash and file_hash in seen_hashes:
                destination = safe_destination(duplicates_dir, f"duplicate_{item.name}")
                try:
                    shutil.move(str(item), str(destination))
                    log_callback(f"DUPLICATE: {item.name} → _Duplicates/")
                    stats["duplicates"] += 1
                except Exception as e:
                    log_callback(f"LOCKED/ERROR: {item.name} — {e}")
                    stats["errors"] += 1
                continue

            destination = safe_destination(base_dir / target_category, item.name)
            try:
                shutil.move(str(item), str(destination))
                if file_hash:
                    seen_hashes[file_hash] = destination
                log_callback(f"MOVED: {item.name} → {target_category}/")
                stats["moved"] += 1
            except Exception as e:
                log_callback(f"LOCKED/ERROR: {item.name} — {e}")
                stats["errors"] += 1

    done_callback(stats)


def get_script_path():
    return Path(sys.argv[0]).resolve()


def schedule_task():
    script = get_script_path()
    python = sys.executable
    cmd = (
        f'schtasks /create /tn "{TASK_NAME}" '
        f'/tr "\\"{python}\\" \\"{script}\\" --headless" '
        f"/sc WEEKLY /d {SCHEDULE_DAY} /st {SCHEDULE_TIME} /f"
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr


def remove_task():
    cmd = f'schtasks /delete /tn "{TASK_NAME}" /f'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr


def task_exists():
    cmd = f'schtasks /query /tn "{TASK_NAME}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0


def headless_run():
    def log(msg):
        print(msg)

    def done(stats):
        log("\n" + "=" * 48)
        log("  DONE! Summary:")
        log(f"  Moved:       {stats['moved']} files")
        log(f"  Duplicates:  {stats['duplicates']} files → _Duplicates/")
        log(f"  Other:       {stats['other']} files → _Other/")
        log(f"  Skipped:     {stats['skipped']} files")
        log(f"  Errors:      {stats['errors']} files")
        log(f"\n  Files saved to: {base_dir}")
        log("=" * 48)

    run_sort(log, done)


def headless_classify(apply: bool = False, no_llm: bool = False, from_report: str = None, all_rows: bool = False):
    if not CLASSIFIER_AVAILABLE:
        print("Classifier not available — ensure classifier.py is in the same folder.")
        return

    config = load_taxonomy()
    if from_report:
        results = run_from_report(
            Path(from_report),
            config,
            log_callback=print,
            needs_review_only=not all_rows,
            use_llm=not no_llm,
        )
    else:
        results = run_dry_run(base_dir, config, log_callback=print, use_llm=not no_llm)
    summary = write_report(results)

    print(f"\n  Report: {summary['report_path']}")
    print(f"  Auto-classified: {summary['auto_classified']} / {summary['total']}")
    print(f"  Needs review:    {summary['needs_review']}")
    print(
        "  Tier breakdown:  "
        f"H={summary['context_prior_hits']} | D={summary['data_bucket_hits']} | N={summary['noise_bucket_hits']} | "
        f"T0={summary['tier0_hits']} | T1={summary['tier1_hits']} | "
        f"T2={summary['tier2_hits']} | None={summary['no_match_hits']} | LLM calls={summary['llm_calls']}"
    )

    if apply:
        print("\nApplying classification — moving files into By_Project/...")
        stats = apply_classification(results, project_root, log_callback=print)
        print(
            f"  Moved: {stats['moved']}  |  Review skipped: {stats['skipped_review']}  |  "
            f"Missing skipped: {stats['skipped_missing']}  |  In-place skipped: {stats['skipped_already_in_place']}  |  "
            f"Errors: {stats['errors']}"
        )
        if stats.get("manifest_path"):
            print(f"  Move manifest: {stats['manifest_path']}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart File Organizer")
        self.resizable(False, False)
        self.configure(bg="#1e1e2e")
        self._build_ui()
        self._refresh_schedule_status()

    def _build_ui(self):
        pad = 16
        bg = "#1e1e2e"
        card = "#2a2a3e"
        acc = "#7c6af7"
        txt = "#cdd6f4"
        dim = "#6c7086"
        green = "#a6e3a1"
        red = "#f38ba8"
        yellow = "#f9e2af"

        self._colors = {"BG": bg, "CARD": card, "ACC": acc, "TXT": txt, "DIM": dim, "GREEN": green, "RED": red, "YELLOW": yellow}

        header = tk.Frame(self, bg=bg)
        header.pack(fill="x", padx=pad, pady=(pad, 0))
        tk.Label(header, text="🗂  Smart File Organizer", font=("Segoe UI", 15, "bold"), bg=bg, fg=txt).pack(side="left")

        self.status_label = tk.Label(header, text="● Idle", font=("Segoe UI", 10), bg=bg, fg=dim)
        self.status_label.pack(side="right", pady=4)

        info = tk.Frame(self, bg=card, padx=pad, pady=8)
        info.pack(fill="x", padx=pad, pady=(8, 0))
        tk.Label(info, text=f"Output folder:  {base_dir}", font=("Segoe UI", 9), bg=card, fg=dim).pack(anchor="w")
        tk.Label(info, text="Scans:  Desktop  •  Downloads  •  Documents", font=("Segoe UI", 9), bg=card, fg=dim).pack(anchor="w")

        log_frame = tk.Frame(self, bg=bg)
        log_frame.pack(padx=pad, pady=(10, 0))

        self.log_box = scrolledtext.ScrolledText(log_frame, width=62, height=18, font=("Consolas", 9), bg="#12121c", fg=txt, insertbackground=txt, relief="flat", bd=0, state="disabled")
        self.log_box.pack()

        for key, color in {
            "move": green,
            "dup": yellow,
            "skip": dim,
            "err": red,
            "head": acc,
            "plain": txt,
        }.items():
            self.log_box.tag_config(key, foreground=color)

        stats_frame = tk.Frame(self, bg=card)
        stats_frame.pack(fill="x", padx=pad, pady=(8, 0))

        self.stat_vars = {}
        for label, key, color in [
            ("Moved", "moved", green),
            ("Duplicates", "duplicates", yellow),
            ("Other", "other", txt),
            ("Skipped", "skipped", dim),
            ("Errors", "errors", red),
        ]:
            col = tk.Frame(stats_frame, bg=card)
            col.pack(side="left", expand=True, fill="x", padx=8, pady=6)
            var = tk.StringVar(value="—")
            self.stat_vars[key] = var
            tk.Label(col, textvariable=var, font=("Segoe UI", 14, "bold"), bg=card, fg=color).pack()
            tk.Label(col, text=label, font=("Segoe UI", 8), bg=card, fg=dim).pack()

        btn_frame = tk.Frame(self, bg=bg)
        btn_frame.pack(padx=pad, pady=12, fill="x")

        self.run_btn = tk.Button(btn_frame, text="▶  Run Now", font=("Segoe UI", 10, "bold"), bg=acc, fg="#ffffff", relief="flat", bd=0, padx=16, pady=8, cursor="hand2", command=self._on_run)
        self.run_btn.pack(side="left")

        tk.Frame(btn_frame, bg=bg, width=10).pack(side="left")

        self.sched_btn = tk.Button(btn_frame, text="", font=("Segoe UI", 10), bg=card, fg=txt, relief="flat", bd=0, padx=16, pady=8, cursor="hand2", command=self._on_schedule_toggle)
        self.sched_btn.pack(side="left")

        self.sched_status = tk.Label(btn_frame, text="", font=("Segoe UI", 9), bg=bg, fg=dim)
        self.sched_status.pack(side="left", padx=(10, 0))

        classify_frame = tk.Frame(self, bg=bg)
        classify_frame.pack(padx=pad, pady=(0, 4), fill="x")

        classify_color = acc if CLASSIFIER_AVAILABLE else dim
        classify_text = "🧠  Classify (Dry Run)" if CLASSIFIER_AVAILABLE else "🧠  Classifier not installed"

        self.classify_btn = tk.Button(
            classify_frame,
            text=classify_text,
            font=("Segoe UI", 10),
            bg=classify_color,
            fg="#ffffff",
            relief="flat",
            bd=0,
            padx=16,
            pady=8,
            cursor="hand2",
            state="normal" if CLASSIFIER_AVAILABLE else "disabled",
            command=self._on_classify_dry_run,
        )
        self.classify_btn.pack(side="left")

        tk.Label(
            classify_frame,
            text="  Generates CSV report only — no files moved",
            font=("Segoe UI", 8),
            bg=bg,
            fg=dim,
        ).pack(side="left")

        tk.Label(self, text="Weekly schedule: Every Monday at 12:00 PM", font=("Segoe UI", 8), bg=bg, fg=dim).pack(pady=(0, pad))

    def _log(self, message):
        self.after(0, self._log_main, message)

    def _log_main(self, message):
        self.log_box.config(state="normal")
        m = message.strip()
        if m.startswith("MOVED"):
            tag = "move"
        elif m.startswith("DUPLICATE"):
            tag = "dup"
        elif m.startswith("LOCKED") or m.startswith("ERROR"):
            tag = "err"
        elif m.startswith("[!]"):
            tag = "skip"
        elif m.startswith("=") or m.startswith("DRY RUN") or m.startswith("Total"):
            tag = "head"
        else:
            tag = "plain"

        self.log_box.insert("end", message + "\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _set_status(self, text, color):
        self.after(0, lambda: self.status_label.config(text=text, fg=color))

    def _on_run(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")
        for v in self.stat_vars.values():
            v.set("…")

        self.run_btn.config(state="disabled")
        self._set_status("● Running", self._colors["ACC"])

        def worker():
            run_sort(self._log, self._on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, stats):
        def update():
            for key in ["moved", "duplicates", "other", "skipped", "errors"]:
                self.stat_vars[key].set(str(stats[key]))

            self._set_status("● Done", self._colors["GREEN"])
            self.run_btn.config(state="normal")

        self.after(0, update)

    def _refresh_schedule_status(self):
        if task_exists():
            self.sched_btn.config(text="🗑  Remove Schedule")
            self.sched_status.config(text="✔ Scheduled: Every Monday at 12:00 PM", fg=self._colors["GREEN"])
        else:
            self.sched_btn.config(text="🕐  Enable Weekly Schedule")
            self.sched_status.config(text="Not scheduled", fg=self._colors["DIM"])

    def _on_schedule_toggle(self):
        if task_exists():
            ok, msg = remove_task()
            if ok:
                messagebox.showinfo("Schedule Removed", "The weekly schedule has been removed.")
            else:
                messagebox.showerror("Error", f"Could not remove task:\n{msg}")
        else:
            ok, msg = schedule_task()
            if ok:
                messagebox.showinfo("Schedule Enabled", "Smart File Organizer will run every Monday at 12:00 PM.")
            else:
                messagebox.showerror("Error", f"Could not create task. Try Administrator mode.\n\n{msg}")

        self._refresh_schedule_status()

    def _on_classify_dry_run(self):
        if not CLASSIFIER_AVAILABLE:
            messagebox.showerror("Not Available", "classifier.py not found in the same folder.")
            return

        self.classify_btn.config(state="disabled")
        self._set_status("● Classifying...", self._colors["ACC"])

        def worker():
            try:
                config = load_taxonomy()
                results = run_dry_run(base_dir, config, log_callback=self._log)
                summary = write_report(results)

                def finish():
                    self._log(f"Report saved: {summary['report_path']}")
                    self._log(
                        "Tier breakdown: "
                        f"H={summary['context_prior_hits']} | D={summary['data_bucket_hits']} | N={summary['noise_bucket_hits']} | "
                        f"T0={summary['tier0_hits']} | T1={summary['tier1_hits']} | "
                        f"T2={summary['tier2_hits']} | None={summary['no_match_hits']} | "
                        f"LLM calls={summary['llm_calls']}"
                    )
                    self._set_status("● Done", self._colors["GREEN"])
                    self.classify_btn.config(state="normal")

                self.after(0, finish)
            except Exception as e:
                self.after(0, lambda: self._log(f"ERROR: {e}"))
                self.after(0, lambda: self._set_status("● Error", self._colors["RED"]))
                self.after(0, lambda: self.classify_btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    no_llm = "--no-llm" in sys.argv
    from_report = None
    all_rows = "--all-rows" in sys.argv
    if "--from-report" in sys.argv:
        idx = sys.argv.index("--from-report")
        if idx + 1 < len(sys.argv):
            from_report = sys.argv[idx + 1]

    if "--headless" in sys.argv:
        headless_run()
    elif "--classify-dry-run" in sys.argv:
        headless_classify(apply=False, no_llm=no_llm, from_report=from_report, all_rows=all_rows)
    elif "--classify-apply" in sys.argv:
        headless_classify(apply=True, no_llm=no_llm, from_report=from_report, all_rows=all_rows)
    else:
        app = App()
        app.mainloop()
