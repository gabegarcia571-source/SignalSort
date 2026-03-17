# SignalSort

**Smart file organization. Built in 4 hours. Deterministic, efficient, zero bloat.**

Two layers:
- **Layer 1**: File-type routing (extensions → folders)
- **Layer 2**: Smart project classification (5-tier deterministic → optional LLM fallback)

No-LLM by default. Weekly automated. One click to schedule.

## Quick Start

**Default (no-LLM, fastest, recommended):**
```bash
python smart_file_sorter.py --classify-dry-run --no-llm
```

**Apply moves:**
```bash
python smart_file_sorter.py --classify-apply --no-llm
```

**For development/testing (with LLM fallback):**
```bash
python smart_file_sorter.py --classify-dry-run
```

**Reprocess flagged files from a report:**
```bash
python smart_file_sorter.py --classify-dry-run --no-llm --from-report logs/classification_report_YYYYMMDD_HHMMSS.csv
```

## Safety & Reversibility

- Dry-run mode writes a CSV report to `logs/` — no files moved.
- Apply mode writes a move manifest for rollback tracking.
- Already-organized files are skipped; missing files are logged.
- **Workflow**: dry-run first, check the summary, then apply.

## Design Philosophy

**Simple > Complex.** The system uses deterministic rules first (context priors, regex, keyword matching) before falling back to an optional LLM. Result: 65%+ of files classify without AI, in seconds, on your machine. No API calls. No latency.

**Few folders > Many folders.** `organization.simple_mode` (on by default) collapses subfolders into broad categories. Keeps your top level sane. Want granularity? Set `simple_mode` to `false` in `config/taxonomy.json`.

## How It Works

**Tier H (Context Priors)** → `.do` files, lecture patterns, academic data signals  
**Tier D (Data Fallback)** → `.csv, .xlsx, .json, .dta, .parquet` by extension  
**Tier 0 (Regex)** → Filename pattern matches (e.g., `resume`, `hw1`, `final_exam`)  
**Tier 1 (Keywords)** → Tokenized, boundary-aware keyword scoring (e.g., `model` + `pipeline`)  
**Tier N (Noise Buckets)** → Generic image/archive/system email names  
**Tier 2 (Optional LLM)** → Falls back to local Ollama if all else fails (disabled by `--no-llm`)

Each tier is deterministic and fast. Most files classify in Tier 0–1.

**Report Summary** shows tier breakdown:
- `H, D, N`: Context/deterministic hits
- `T0, T1, T2`: Tier hits (T2 = LLM calls)
- `LLM calls`: Number of files that hit Tier 2

If LLM calls are high, you need better keywords in `config/taxonomy.json`. Expand tier0_patterns or keywords for that category.

## Routing Rules

- `.do` files are routed to `Academic/Class_Data` before Tier 0/1/2.
- Data files with academic signals (e.g., `econ`, `econometrics`, `COMM####`, `week#`, `lab#`) are routed to `Academic/Class_Data`.
- Lecture/course signals (e.g., `lec`, `lecture`, `syllabus`, `module`, `week#`) are routed to `Academic/Course_Materials`.
- Strong paper/article signals in filename (e.g., `arxiv`, `ssrn`, `nber`, `doi`, `journal`, `working paper`, `et al`, `proceedings`) are routed to `Academic/External_Papers_Articles`.
- Academic writing signals (e.g., `policy memo`, `memo`, `lit review`, `essay`, `thesis`, `proposal`) are routed to `Academic/My_Writing`.
- Coding homework files (e.g., `week_8_week_9-hw.ipynb`, `hw2.py`, `assignment_3.ipynb`) are routed to `Academic/Coding_Homework`.
- Remaining generic data files are routed to `Data_Bucket` subfolders by extension:
	- `CSV`, `Spreadsheets`, `Stata`, `Structured`, `General`
- Generic low-signal files are routed to `Review_Buckets`:
	- `PNGs` (all unmatched `.png` files)
	- `JPG_JPEG` (all unmatched `.jpg` / `.jpeg` files)
	- `Images_Generic` (includes unmatched `.gif` / `.webp`)
	- `Images_Generic` (e.g., `IMG_####`, `ChatGPT Image ...`, hash-like names)
	- `Archives_Generic` (e.g., `drive-download*`, `OneDrive_*`, `compressed.zip`)
	- `Email_System` (e.g., scanner/placeholder `.eml`/`.ics` names)
	- `Installers` (e.g., `.exe`, `.msi`, `.pkg`, `.dmg`, `.deb`, `.rpm`, `.appimage`)

Additional minimal priors:
- Academic-like archives (`econ####`, `week#`, `lec#`, `lecture`, `syllabus`, `assignment`, `homework`) route to `Academic`.
- Dataset/export archives (`filtered`, `export`, `dataset`, `data`, `stata`) route to `Data_Bucket`.
- Forwarded/temp email names (e.g., `Fwd_*`, `~$*`) route to `Review_Buckets/Email_System`.

## Excluded Folders

Skipped during scan:
- `__pycache__`, `logs`, `config` (system dirs)
- `By_Project`, `_Duplicates`, `_Other`, `_Needs_Review` (already organized)

## Weekly Automation

Open the GUI and click **🕐 Enable Weekly Schedule** — sets up Windows Task Scheduler to run dry-run classification every Monday at 12:00 PM. No manual setup needed.

## Notes

- Built to stay simple. No unnecessary features. No bloat.
- Runs locally. No cloud, no APIs (except optional Ollama fallback).
- Built in 4 hours. It works. Use it.
