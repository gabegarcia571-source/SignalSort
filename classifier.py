"""
classifier.py — Tiered AI classification engine for Smart File Organizer
"""

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

CONFIG_DIR = Path(__file__).parent / "config"
TAXONOMY_PATH = CONFIG_DIR / "taxonomy.json"
LOG_DIR = Path(__file__).parent / "logs"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "phi3"

DATA_EXTENSIONS = {".csv", ".xlsx", ".xls", ".dta", ".parquet", ".json"}
INSTALLER_EXTENSIONS = {".exe", ".msi", ".pkg", ".dmg", ".deb", ".rpm", ".appimage"}
FORCE_ACADEMIC_EXTENSIONS = {".do"}
CODING_HOMEWORK_EXTENSIONS = {".ipynb", ".py", ".r", ".rmd", ".jl"}
ACADEMIC_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".rtf"}
ACADEMIC_FILENAME_PATTERNS = [
    r"\becon\w*\b",
    r"\beconometrics?\b",
    r"\beconmath\b",
    r"\bcomm\d{3,4}\b",
    r"\bweek\s*\d+\b",
    r"\blab\s*\d+\b",
]
ACADEMIC_MATERIAL_PATTERNS = [
    r"\blec\b",
    r"\blec[_ -]?\d+(?:\b|_)",
    r"\blecture(s)?\b",
    r"\bsyllabus\b",
    r"\bmodule\s*\d+\b",
    r"\bweek\s*\d+\b",
]
ACADEMIC_ARTICLE_FILENAME_PATTERNS = [
    r"\barxiv\b",
    r"\bssrn\b",
    r"\bnber\b",
    r"\bdoi\b",
    r"\bjournal\b",
    r"\bworking[ _-]?paper\b",
    r"\bet[ _-]?al\b",
    r"\bproceedings\b",
    r"_-_",
    r"\barticle\b",
    r"\breadings?\b",
    r"\bchapter\b",
]
ACADEMIC_MY_WRITING_FILENAME_PATTERNS = [
    r"\bpolicy[ _-]?memo\b",
    r"\bmemo\b",
    r"\breflection\b",
    r"\bresponse[ _-]?paper\b",
    r"\blit(erature)?[ _-]?review\b",
    r"\bfinal[ _-]?paper\b",
    r"\bessay\b",
    r"\bthesis\b",
    r"\bproposal\b",
]
CODING_HOMEWORK_FILENAME_PATTERNS = [
    r"\bweek[_ -]?\d+.*\b(hw|homework)\b",
    r"\b(hw|homework)[_ -]?\d+\b",
    r"\bassignment[_ -]?\d+\b",
    r"\blab[_ -]?\d+\b",
    r"\bproblem[_ -]?set\b",
]
NOISE_IMAGE_PATTERNS = [
    r"^img[_ -]?\d+",
    r"^image\d+",
    r"^chatgpt image",
    r"^[0-9a-f]{16,}",
]
NOISE_ARCHIVE_PATTERNS = [
    r"^drive-download",
    r"^onedrive_",
    r"^compressed$",
    r"^files$",
]
NOISE_EMAIL_CAL_PATTERNS = [
    r"safe attachments scan in progress",
    r"atp scan in progress",
    r"^calendar$",
    r"^invite(\s*\(\d+\))?$",
]
ARCHIVE_ACADEMIC_PATTERNS = [
    r"\becon\d+\b",
    r"\bweek[_ -]?\d+\b",
    r"\blec[_ -]?\d+\b",
    r"\blecture\b",
    r"\bsyllabus\b",
    r"\bassignment\b",
    r"\bhomework\b",
]
ARCHIVE_DATASET_PATTERNS = [
    r"\bfiltered\b",
    r"\bexport\b",
    r"\bdataset\b",
    r"\bdata\b",
    r"\bstata\b",
]
ARCHIVE_INSTALLER_PATTERNS = [
    r"\binstaller\b",
    r"\bsetup\b",
    r"\bportable\b",
    r"\bdriver\b",
]
TEMP_EMAIL_PATTERNS = [
    r"^fwd[_ -]",
    r"^~\$",
]
TIER1_DATA_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".dta", ".parquet"}
TIER1_WEAK_DATA_KEYWORDS = {"draft", "job", "intern", "doi"}
TIER1_MIN_SCORE = 2
TIER1_MIN_SCORE_FOR_DATA_OVERRIDE = 4


def _data_subfolder_for_extension(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == ".csv":
        return "CSV"
    if suffix in {".xlsx", ".xls"}:
        return "Spreadsheets"
    if suffix == ".dta":
        return "Stata"
    if suffix in {".json", ".parquet"}:
        return "Structured"
    return "General"


def context_prior_classify(file_path: Path) -> tuple:
    filename = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if suffix in FORCE_ACADEMIC_EXTENSIONS:
        return (
            "Academic",
            "Class_Data",
            0.93,
            "Context prior — .do files routed to Academic/Class_Data",
        )

    if suffix in DATA_EXTENSIONS and any(re.search(p, filename) for p in ACADEMIC_FILENAME_PATTERNS):
        return (
            "Academic",
            "Class_Data",
            0.91,
            "Context prior — econ/class signal in data filename",
        )

    if any(re.search(p, filename) for p in ACADEMIC_MATERIAL_PATTERNS):
        return (
            "Academic",
            "Course_Materials",
            0.91,
            "Context prior — lecture/course signal in filename",
        )

    return None, "", 0.0, ""


def academic_document_prior_classify(file_path: Path) -> tuple:
    filename = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if suffix not in ACADEMIC_DOCUMENT_EXTENSIONS:
        return None, "", 0.0, ""

    if any(re.search(p, filename) for p in ACADEMIC_MY_WRITING_FILENAME_PATTERNS):
        return (
            "Academic",
            "My_Writing",
            0.91,
            "Context prior — strong academic writing signal in filename",
        )

    if any(re.search(p, filename) for p in ACADEMIC_ARTICLE_FILENAME_PATTERNS):
        return (
            "Academic",
            "External_Papers_Articles",
            0.91,
            "Context prior — strong academic article signal in filename",
        )

    return None, "", 0.0, ""


def academic_coding_homework_prior_classify(file_path: Path) -> tuple:
    filename = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if suffix not in CODING_HOMEWORK_EXTENSIONS:
        return None, "", 0.0, ""

    if any(re.search(p, filename) for p in CODING_HOMEWORK_FILENAME_PATTERNS):
        return (
            "Academic",
            "Coding_Homework",
            0.92,
            "Context prior — coding homework filename pattern",
        )

    return None, "", 0.0, ""


def archive_prior_classify(file_path: Path) -> tuple:
    filename = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if suffix not in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return None, "", 0.0, ""

    if any(re.search(p, filename) for p in ARCHIVE_INSTALLER_PATTERNS):
        return (
            "Review_Buckets",
            "Installers",
            0.91,
            "Context prior — installer-like archive name",
        )

    if any(re.search(p, filename) for p in ARCHIVE_ACADEMIC_PATTERNS):
        return (
            "Academic",
            "Course_Materials",
            0.91,
            "Context prior — academic signal in archive filename",
        )

    if any(re.search(p, filename) for p in ARCHIVE_DATASET_PATTERNS):
        return (
            "Data_Bucket",
            "General",
            0.90,
            "Context prior — dataset/export signal in archive filename",
        )

    return None, "", 0.0, ""


def fallback_data_bucket(file_path: Path) -> tuple:
    suffix = file_path.suffix.lower()
    if suffix in DATA_EXTENSIONS:
        subfolder = _data_subfolder_for_extension(suffix)
        return (
            "Data_Bucket",
            subfolder,
            0.90,
            f"Deterministic fallback — data extension '{suffix}' routed to Data_Bucket/{subfolder}",
        )
    return None, "", 0.0, ""


def fallback_image_bucket(file_path: Path) -> tuple:
    suffix = file_path.suffix.lower()
    if suffix == ".png":
        return (
            "Review_Buckets",
            "PNGs",
            0.90,
            "Deterministic fallback — unmatched PNG routed to Review_Buckets/PNGs",
        )
    if suffix in {".jpg", ".jpeg"}:
        return (
            "Review_Buckets",
            "JPG_JPEG",
            0.90,
            "Deterministic fallback — unmatched JPG/JPEG routed to Review_Buckets/JPG_JPEG",
        )
    if suffix in {".gif", ".webp"}:
        return (
            "Review_Buckets",
            "Images_Generic",
            0.90,
            "Deterministic fallback — unmatched GIF/WEBP routed to Review_Buckets/Images_Generic",
        )
    return None, "", 0.0, ""


def noise_bucket_classify(file_path: Path) -> tuple:
    stem_lower = file_path.stem.lower()
    suffix = file_path.suffix.lower()

    if suffix in INSTALLER_EXTENSIONS:
        return (
            "Review_Buckets",
            "Installers",
            0.91,
            "Deterministic noise bucket — installer binary/package extension",
        )

    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".svg"}:
        if any(re.search(p, stem_lower) for p in NOISE_IMAGE_PATTERNS):
            return (
                "Review_Buckets",
                "Images_Generic",
                0.91,
                "Deterministic noise bucket — generic image naming pattern",
            )

    if suffix in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        if any(re.search(p, stem_lower) for p in NOISE_ARCHIVE_PATTERNS):
            return (
                "Review_Buckets",
                "Archives_Generic",
                0.91,
                "Deterministic noise bucket — generic archive naming pattern",
            )

    if suffix in {".eml", ".ics"}:
        if any(re.search(p, stem_lower) for p in TEMP_EMAIL_PATTERNS):
            return (
                "Review_Buckets",
                "Email_System",
                0.91,
                "Deterministic noise bucket — temp/forwarded email naming pattern",
            )
        if any(re.search(p, stem_lower) for p in NOISE_EMAIL_CAL_PATTERNS):
            return (
                "Review_Buckets",
                "Email_System",
                0.91,
                "Deterministic noise bucket — system email/calendar naming pattern",
            )

    return None, "", 0.0, ""


def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tier0_classify(filename: str, taxonomy: dict) -> tuple:
    name_lower = filename.lower()
    for category, meta in taxonomy.items():
        for pattern in meta.get("tier0_patterns", []):
            if re.search(pattern, name_lower):
                return category, 0.95, f"Tier 0 — filename matched pattern '{pattern}'"
    return None, 0.0, ""


def tier1_classify(filename: str, taxonomy: dict) -> tuple:
    file_path = Path(filename)
    name_stem = file_path.stem.lower()
    suffix = file_path.suffix.lower()

    tokens = _tier1_tokenize(name_stem)
    normalized = " ".join(tokens)

    category_scores = {}
    category_hits = {}

    for category, meta in taxonomy.items():
        score, hits = _tier1_score_category(
            meta.get("keywords", []),
            tokens,
            normalized,
            _tier1_negative_overrides(tokens),
        )
        if score > 0:
            category_scores[category] = score
            category_hits[category] = hits

    if not category_scores:
        return None, 0.0, ""

    best_category = max(category_scores, key=lambda c: category_scores[c])
    best_score = category_scores[best_category]
    matched_keywords = category_hits.get(best_category, [])

    if best_score < TIER1_MIN_SCORE:
        return None, 0.0, ""

    # Calendar/email files (.ics/.eml) are already caught by noise_bucket_classify(), so no weak-keyword blocking here
    if suffix in TIER1_DATA_EXTENSIONS:
        strong_hits = [kw for kw in matched_keywords if kw not in TIER1_WEAK_DATA_KEYWORDS]
        if best_score < TIER1_MIN_SCORE_FOR_DATA_OVERRIDE or len(strong_hits) < 2:
            return None, 0.0, ""

    confidence = min(0.84 + 0.03 * best_score, 0.98)
    tier1_payload = {
        "category": best_category,
        "confidence": round(confidence, 3),
        "matched_keywords": matched_keywords,
        "tokens": tokens,
    }
    reason = (
        "Tier 1 — scored keyword match: "
        f"{tier1_payload['matched_keywords']} | tokens={tier1_payload['tokens']} | score={best_score}"
    )
    return tier1_payload["category"], tier1_payload["confidence"], reason


def _tier1_tokenize(name_stem: str) -> list:
    raw = re.split(r"[_\-\.\s]+", name_stem)
    return [token for token in raw if token]


def _tier1_negative_overrides(tokens: list) -> set:
    blocked = set()
    token_set = set(tokens)
    if "international" in token_set:
        blocked.add("intern")
    return blocked


def _tier1_score_category(keywords: list, tokens: list, normalized: str, blocked_keywords: set) -> tuple:
    score = 0
    hits = []
    token_set = set(tokens)

    for kw in keywords:
        keyword = str(kw).strip().lower()
        if not keyword or keyword in blocked_keywords:
            continue

        exact_token_match = keyword in token_set
        weak_match = False

        if not exact_token_match:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            weak_match = re.search(pattern, normalized) is not None

        if exact_token_match:
            score += 2
            hits.append(keyword)
        elif weak_match:
            score += 1
            hits.append(keyword)

    return score, hits


def _read_file_preview(file_path: Path, max_chars: int = 4000) -> str:
    try:
        with open(file_path, "r", errors="ignore", encoding="utf-8") as f:
            return f.read(max_chars)
    except Exception:
        return ""


def tier2_classify(file_path: Path, taxonomy: dict) -> tuple:
    content = _read_file_preview(file_path)
    labels = list(taxonomy.keys())

    categories_text = "\n".join(
        f"- {label}: {meta['description']}" for label, meta in taxonomy.items()
    )

    prompt = (
        "You are a strict file organizer. "
        "Classify the file into exactly one of the following categories.\n\n"
        f"Categories:\n{categories_text}\n\n"
        f"File name: {file_path.name}\n"
        f"File content preview:\n{content[:3000]}\n\n"
        "Rules:\n"
        "1. Respond with ONLY the category name — nothing else.\n"
        "2. If unsure, respond with: Personal\n"
        f"3. Valid categories: {', '.join(labels)}"
    )

    try:
        payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False}
        resp = requests.post(OLLAMA_URL, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        category = str(data.get("response", "")).strip()

        if category in taxonomy:
            return category, 0.92, f"Tier 2 — Ollama classified as '{category}'"

        for label in labels:
            if label.lower() in category.lower():
                return label, 0.80, f"Tier 2 — Ollama fuzzy match '{category}' → '{label}'"

        return None, 0.0, f"Tier 2 — Ollama returned unrecognised label: '{category}'"

    except requests.exceptions.ConnectionError:
        return None, 0.0, "Tier 2 — Ollama not running (start Ollama app/system tray)"
    except Exception as e:
        return None, 0.0, f"Tier 2 — Error: {e}"


def classify_academic_authorship(file_path: Path, config: dict) -> str:
    rules = config.get("academic_authorship", {})
    name_lower = file_path.name.lower()

    for signal in rules.get("my_writing_signals", []):
        if signal.lower() in name_lower:
            return "My_Writing"

    for signal in rules.get("external_signals", []):
        if signal.lower() in name_lower:
            return "External_Papers_Articles"

    content = _read_file_preview(file_path, max_chars=1500).lower()
    for signal in rules.get("external_signals", []):
        if signal.lower() in content:
            return "External_Papers_Articles"

    return "My_Writing"


def simplify_subfolder(category: str, subfolder: str, config: dict) -> str:
    org_cfg = config.get("organization", {})
    if not org_cfg.get("simple_mode", False):
        return subfolder

    collapse = org_cfg.get("collapse_subfolders", {})
    if category in collapse:
        return collapse[category]

    return subfolder


def classify_file(file_path: Path, config: dict, use_llm: bool = True) -> dict:
    taxonomy = config["taxonomy"]
    threshold = config["review"]["confidence_threshold"]
    filename = file_path.name

    category, subfolder, confidence, reason = context_prior_classify(file_path)
    tier_used = "H" if category else None
    llm_called = False

    if category is None:
        category, subfolder, confidence, reason = academic_document_prior_classify(file_path)
        tier_used = "H" if category else None

    if category is None:
        category, subfolder, confidence, reason = academic_coding_homework_prior_classify(file_path)
        tier_used = "H" if category else None

    if category is None:
        category, subfolder, confidence, reason = archive_prior_classify(file_path)
        tier_used = "H" if category else None

    if category is None:
        category, confidence, reason = tier0_classify(filename, taxonomy)
        tier_used = 0 if category else None

    if category is None:
        category, confidence, reason = tier1_classify(filename, taxonomy)
        tier_used = 1 if category else None

    if category is None:
        category, subfolder, confidence, reason = fallback_data_bucket(file_path)
        tier_used = "D" if category else None

    if category is None:
        category, subfolder, confidence, reason = fallback_image_bucket(file_path)
        tier_used = "N" if category else None

    if category is None:
        category, subfolder, confidence, reason = noise_bucket_classify(file_path)
        tier_used = "N" if category else None

    if category is None and use_llm:
        llm_called = True
        llm_cat, llm_conf, llm_reason = tier2_classify(file_path, taxonomy)
        tier_used = 2
        if llm_cat:
            category, confidence, reason = llm_cat, llm_conf, llm_reason
        else:
            reason = llm_reason
            confidence = 0.0
    elif category is None and not use_llm:
        reason = "Tier 2 skipped (--no-llm) and no Tier 0/1 match"

    if not subfolder and category == "Academic":
        subfolder = classify_academic_authorship(file_path, config)

    if category:
        subfolder = simplify_subfolder(category, subfolder, config)

    needs_review = (category is None) or (confidence < threshold)
    if needs_review:
        if category is None:
            category = config["review"]["folder"]

    return {
        "filename": filename,
        "file": str(file_path),
        "category": category,
        "subfolder": subfolder,
        "confidence": round(confidence, 3),
        "reason": reason or "No strong classification signal found",
        "tier_used": tier_used,
        "needs_review": needs_review,
        "llm_called": llm_called,
        "timestamp": datetime.now().isoformat(),
    }


def run_dry_run(scan_root: Path, config: dict, log_callback=print, exclude_dirs: list = None, use_llm: bool = True) -> list:
    exclude_dirs = exclude_dirs or [
        "_Duplicates",
        "_Other",
        "_Needs_Review",
        "logs",
        "__pycache__",
        "By_Project",
        "config",
    ]

    files = [
        f
        for f in scan_root.rglob("*")
        if f.is_file()
        and not f.name.startswith(".")
        and not any(ex in f.parts for ex in exclude_dirs)
    ]

    results = []
    review_count = 0

    perf_cfg = config.get("performance", {})
    default_workers = 6 if use_llm else 4
    worker_count = max(1, int(perf_cfg.get("llm_workers", default_workers)))

    log_callback("=" * 64)
    llm_mode = "enabled" if use_llm else "disabled (--no-llm)"
    log_callback(f"  DRY RUN — {len(files)} files found in {scan_root} | LLM: {llm_mode}")
    log_callback("=" * 64)

    def classify_and_format(file_path: Path):
        result = classify_file(file_path, config, use_llm=use_llm)
        status = "⚠ REVIEW" if result["needs_review"] else "✓      "
        subfolder_str = f"/{result['subfolder']}" if result["subfolder"] else ""
        tier_label = (
            f"T{result['tier_used']}"
            if isinstance(result["tier_used"], int)
            else (result["tier_used"] if result["tier_used"] is not None else "T-")
        )
        line = (
            f"  {status}  {result['filename'][:38]:<38}  →  "
            f"{result['category']}{subfolder_str:<28}  "
            f"({result['confidence']:.0%}, {tier_label})"
        )
        return result, line

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(classify_and_format, file_path) for file_path in files]
        for future in as_completed(futures):
            try:
                result, line = future.result()
            except Exception as e:
                log_callback(f"  ERROR: worker failed — {e}")
                continue
            results.append(result)
            if result["needs_review"]:
                review_count += 1
            log_callback(line)

    log_callback("=" * 64)
    log_callback(f"  Total: {len(files)}  |  Auto-classified: {len(files) - review_count}  |  Needs review: {review_count}")
    log_callback("=" * 64)

    return results


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def run_from_report(
    report_path: Path,
    config: dict,
    log_callback=print,
    needs_review_only: bool = True,
    use_llm: bool = True,
) -> list:
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    rows = []
    with open(report_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if needs_review_only and not _truthy(row.get("needs_review", False)):
                continue
            rows.append(row)

    file_paths = []
    seen = set()
    for row in rows:
        path_str = row.get("file", "")
        if not path_str:
            continue
        if path_str in seen:
            continue
        seen.add(path_str)
        p = Path(path_str)
        if p.exists() and p.is_file():
            file_paths.append(p)

    llm_mode = "enabled" if use_llm else "disabled (--no-llm)"
    mode_label = "needs_review only" if needs_review_only else "all rows"
    log_callback("=" * 64)
    log_callback(
        f"  REPORT RE-RUN — {len(file_paths)} files from {report_path.name} | Mode: {mode_label} | LLM: {llm_mode}"
    )
    log_callback("=" * 64)

    results = []
    review_count = 0

    perf_cfg = config.get("performance", {})
    default_workers = 6 if use_llm else 4
    worker_count = max(1, int(perf_cfg.get("llm_workers", default_workers)))

    def classify_and_format(file_path: Path):
        result = classify_file(file_path, config, use_llm=use_llm)
        status = "⚠ REVIEW" if result["needs_review"] else "✓      "
        subfolder_str = f"/{result['subfolder']}" if result["subfolder"] else ""
        tier_label = (
            f"T{result['tier_used']}"
            if isinstance(result["tier_used"], int)
            else (result["tier_used"] if result["tier_used"] is not None else "T-")
        )
        line = (
            f"  {status}  {result['filename'][:38]:<38}  →  "
            f"{result['category']}{subfolder_str:<28}  "
            f"({result['confidence']:.0%}, {tier_label})"
        )
        return result, line

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(classify_and_format, fp) for fp in file_paths]
        for future in as_completed(futures):
            try:
                result, line = future.result()
            except Exception as e:
                log_callback(f"  ERROR: worker failed — {e}")
                continue
            results.append(result)
            if result["needs_review"]:
                review_count += 1
            log_callback(line)

    log_callback("=" * 64)
    log_callback(f"  Total: {len(file_paths)}  |  Auto-classified: {len(file_paths) - review_count}  |  Needs review: {review_count}")
    log_callback("=" * 64)

    return results


def write_report(results: list, output_path: Path = None) -> dict:
    if output_path is None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = LOG_DIR / f"classification_report_{timestamp}.csv"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "filename",
        "category",
        "subfolder",
        "confidence",
        "tier_used",
        "needs_review",
        "reason",
        "llm_called",
        "file",
        "timestamp",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    needs_review = [r for r in results if r["needs_review"]]
    auto_done = [r for r in results if not r["needs_review"]]

    by_tier = {0: 0, 1: 0, 2: 0, "H": 0, "D": 0, "N": 0, "none": 0}
    llm_calls = 0
    for r in results:
        tier = r.get("tier_used")
        if tier in (0, 1, 2):
            by_tier[tier] += 1
        elif tier in ("H", "D", "N"):
            by_tier[tier] += 1
        else:
            by_tier["none"] += 1
        if r.get("llm_called"):
            llm_calls += 1

    return {
        "total": len(results),
        "auto_classified": len(auto_done),
        "needs_review": len(needs_review),
        "tier0_hits": by_tier[0],
        "tier1_hits": by_tier[1],
        "tier2_hits": by_tier[2],
        "context_prior_hits": by_tier["H"],
        "data_bucket_hits": by_tier["D"],
        "noise_bucket_hits": by_tier["N"],
        "no_match_hits": by_tier["none"],
        "llm_calls": llm_calls,
        "report_path": str(output_path),
    }


def apply_classification(results: list, project_root: Path, log_callback=print, dry_run: bool = False) -> dict:
    stats = {"moved": 0, "skipped_review": 0, "skipped_missing": 0, "skipped_already_in_place": 0, "errors": 0}
    move_records = []

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = LOG_DIR / f"move_manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    for result in results:
        if result["needs_review"]:
            stats["skipped_review"] += 1
            continue

        src = Path(result["file"])
        if not src.exists():
            log_callback(f"  SKIP (missing): {result['filename']}")
            stats["skipped_missing"] += 1
            continue

        category = result["category"]
        subfolder = result.get("subfolder", "")

        dest_dir = project_root / category
        if subfolder:
            dest_dir = dest_dir / subfolder

        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_file = dest_dir / result["filename"]

        if src.resolve() == dest_file.resolve():
            log_callback(f"  SKIP (already in place): {result['filename']}")
            stats["skipped_already_in_place"] += 1
            continue

        counter = 1
        while dest_file.exists():
            dest_file = dest_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1

        action = "WOULD MOVE" if dry_run else "MOVED"
        try:
            if not dry_run:
                import shutil

                shutil.move(str(src), str(dest_file))
                move_records.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "source": str(src),
                        "destination": str(dest_file),
                        "category": category,
                        "subfolder": subfolder,
                        "confidence": result.get("confidence", ""),
                        "tier_used": result.get("tier_used", ""),
                    }
                )
            log_callback(f"  {action}: {result['filename']} → {category}/{subfolder}")
            stats["moved"] += 1
        except Exception as e:
            log_callback(f"  ERROR: {result['filename']} — {e}")
            stats["errors"] += 1

    if not dry_run and move_records:
        with open(manifest_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "source",
                    "destination",
                    "category",
                    "subfolder",
                    "confidence",
                    "tier_used",
                ],
            )
            writer.writeheader()
            writer.writerows(move_records)
        stats["manifest_path"] = str(manifest_path)
    else:
        stats["manifest_path"] = ""

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart File Classifier")
    parser.add_argument("scan_dir", nargs="?", help="Directory to scan")
    parser.add_argument("--apply", action="store_true", help="Move files after classification")
    parser.add_argument("--project-root", default=None, help="Where to move files when --apply is set")
    parser.add_argument("--no-llm", action="store_true", help="Skip Tier 2 Ollama calls")
    parser.add_argument("--from-report", default=None, help="CSV report path to reprocess")
    parser.add_argument("--all-rows", action="store_true", help="When using --from-report, process all rows (default is needs_review only)")
    args = parser.parse_args()

    config = load_taxonomy()

    if args.from_report:
        results = run_from_report(
            Path(args.from_report),
            config,
            use_llm=not args.no_llm,
            needs_review_only=not args.all_rows,
        )
    else:
        if not args.scan_dir:
            print("Error: scan_dir is required unless --from-report is provided.")
            raise SystemExit(1)
        scan = Path(args.scan_dir)
        if not scan.exists():
            print(f"Error: '{scan}' does not exist.")
            raise SystemExit(1)
        results = run_dry_run(scan, config, use_llm=not args.no_llm)
    summary = write_report(results)

    print(f"\n  Report saved to: {summary['report_path']}")
    print(f"  Auto-classified: {summary['auto_classified']} / {summary['total']}")
    print(f"  Needs review:    {summary['needs_review']}")
    print(
        "  Tier breakdown:  "
        f"H={summary['context_prior_hits']} | D={summary['data_bucket_hits']} | N={summary['noise_bucket_hits']} | "
        f"T0={summary['tier0_hits']} | T1={summary['tier1_hits']} | "
        f"T2={summary['tier2_hits']} | None={summary['no_match_hits']} | LLM calls={summary['llm_calls']}"
    )

    if args.apply:
        if not args.project_root:
            print("\nError: --project-root required when using --apply")
            raise SystemExit(1)
        print("\nApplying classification...")
        stats = apply_classification(results, Path(args.project_root))
        print(f"  Moved: {stats['moved']}  |  Skipped (review): {stats['skipped_review']}  |  Errors: {stats['errors']}")
