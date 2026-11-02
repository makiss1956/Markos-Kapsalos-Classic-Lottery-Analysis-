#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eurojackpot Updater
===================
Αυτόματη ενημέρωση του αρχείου κληρώσεων Eurojackpot (CSV) κάθε Τρίτη &
Παρασκευή. Εντοπίζει τις λείπουσες κληρώσεις, τις κατεβάζει, τις επαληθεύει
και τις προσθέτει στο αρχείο — χωρίς χειροκίνητη ενασχόληση.

ΠΗΓΕΣ ΔΕΔΟΜΕΝΩΝ (δεν υπάρχουν bot-restrictions, απλά HTTP GET):
  1. ΚΥΡΙΑ: Πλήρες, validated CSV ιστορικό (2012-03-23 → σήμερα) του repo
     dev-baris/lottery-archive, που ενημερώνεται καθημερινά μέσω GitHub Actions:
     https://raw.githubusercontent.com/dev-baris/lottery-archive/main/eu/eurojackpot/results.csv
  2. ΕΠΑΛΗΘΕΥΣΗ / FALLBACK: Το επίσημο eurojackpot.org σερβίρει JSON ανά
     ημερομηνία κλήρωσης (το ίδιο endpoint που χρησιμοποιεί η σελίδα του):
     https://www.eurojackpot.org/proxy.php?d=euroJackpot/YYYYMMDD

Χρήση:
  python3 eurojackpot_updater.py                     # ενημέρωση του eurojackpot.csv
  python3 eurojackpot_updater.py --csv data/my.csv   # δικό σου αρχείο
  python3 eurojackpot_updater.py --dry-run           # δοκιμή χωρίς εγγραφή
  python3 eurojackpot_updater.py --no-verify         # χωρίς cross-check με το official site
  python3 eurojackpot_updater.py --fill-col Status=JACKPOT   # σταθερή τιμή σε extra στήλη

Κωδικοί εξόδου: 0 = ΟΚ (ή καμία νέα κλήρωση) | 1 = σφάλμα | 2 = αποτυχία επαλήθευσης
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta

# --------------------------------------------------------------------------
# ΡΥΘΜΙΣΕΙΣ ΠΗΓΩΝ
# --------------------------------------------------------------------------
PRIMARY_CSV_URL = (
    "https://raw.githubusercontent.com/dev-baris/lottery-archive/"
    "main/eu/eurojackpot/results.csv"
)
OFFICIAL_PROXY_URL = "https://www.eurojackpot.org/proxy.php?d=euroJackpot/{ymd}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RETRIES = 3          # προσπάθειες ανά αίτημα
TIMEOUT = 25         # δευτερόλεπτα ανά αίτημα

DEFAULT_HEADER = ["date", "n1", "n2", "n3", "n4", "n5", "e1", "e2"]

# Ημέρες κλήρωσης: Δευτέρα=0, Τρίτη=1, ..., Παρασκευή=4
DRAW_WEEKDAYS = (1, 4)

# --------------------------------------------------------------------------
# ΑΝΙΧΝΕΥΣΗ ΣΤΗΛΩΝ (για να ταιριάζει και με «δικό σου» CSV)
# --------------------------------------------------------------------------
DATE_COL_ALIASES = {
    "date", "draw_date", "drawdate", "drawing_date", "datum",
    "ημερομηνια", "ημερομηνία", "imerominia", "hmerominia",
}
NUM_COL_ALIASES = (
    {f"n{i}" for i in range(1, 6)}
    | {f"num{i}" for i in range(1, 6)}
    | {f"number{i}" for i in range(1, 6)}
    | {f"nr{i}" for i in range(1, 6)}
    | {f"ball{i}" for i in range(1, 6)}
    | {f"αριθμος{i}" for i in range(1, 6)}
    | {f"αριθμός{i}" for i in range(1, 6)}
)
EURO_COL_ALIASES = {
    "e1", "e2", "euro1", "euro2", "star1", "star2",
    "ε1", "ε2", "αστερι1", "αστερι2", "αστέρι1", "αστέρι2",
}
NUMS_SINGLE_ALIASES = {"numbers", "winning_numbers", "αριθμοι", "αριθμοί"}
EURO_SINGLE_ALIASES = {
    "euro", "euro_numbers", "euronumbers", "stars", "lucky_stars",
    "ευρω", "ευρώ", "αστερια", "αστέρια",
}

DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%Y.%m.%d", "%d/%m/%y", "%d-%m-%y",
]

# --------------------------------------------------------------------------
# ΒΟΗΘΗΤΙΚΑ
# --------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> "None":
    log(f"[ΣΦΑΛΜΑ] {msg}")
    sys.exit(code)


def http_get(url: str) -> bytes:
    """GET με retries και εκθετικό backoff. Επιστρέφει bytes ή κάνει raise."""
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError) as err:
            last_err = err
            if attempt < RETRIES:
                wait = 2 ** attempt
                log(f"  [πρόσπαθεια {attempt}/{RETRIES} απέτυχε: {err} — ξαναδοκιμή σε {wait}s]")
                time.sleep(wait)
    raise RuntimeError(f"αποτυχία λήψης {url}: {last_err}")


def strip_accents(s: str) -> str:
    nk = unicodedata.normalize("NFD", s)
    return "".join(c for c in nk if not unicodedata.combining(c)).lower().strip()


def norm_header(h: str) -> str:
    return strip_accents(h.replace("﻿", "").strip())


def parse_date_any(value: str):
    """Δοκιμάζει όλες τις γνωστές μορφές ημερομηνίας (και με ώρα στο τέλος)."""
    v = (value or "").strip()
    candidates = [v]
    if " " in v:
        candidates.append(v.split()[0])
    if "T" in v:
        candidates.append(v.split("T")[0])
    for c in candidates:
        for fmt in DATE_FORMATS:
            try:
                return date(*time.strptime(c, fmt)[:3]), fmt
            except ValueError:
                continue
    return None, None


def validate_draw(d: date, nums, euros) -> tuple:
    """Έλεγχος εγκυρότητας κλήρωσης: 5/50 + 2/12 + σωστή ημέρα."""
    nums = tuple(int(x) for x in nums)
    euros = tuple(int(x) for x in euros)
    if len(nums) != 5 or len(set(nums)) != 5 or not all(1 <= n <= 50 for n in nums):
        raise ValueError(f"λάθος κύριοι αριθμοί {nums} για {d}")
    if len(euros) != 2 or len(set(euros)) != 2 or not all(1 <= e <= 12 for e in euros):
        raise ValueError(f"λάθοι αριθμοί Euro {euros} για {d}")
    if d.weekday() not in DRAW_WEEKDAYS:
        raise ValueError(f"η {d} δεν είναι Τρίτη ή Παρασκευή")
    return nums, euros


def expected_draw_dates(after: date, until: date) -> list:
    """Όλες οι Τρίτες/Παρασκευές στο διάστημα (after, until]."""
    out, d = [], after + timedelta(days=1)
    while d <= until:
        if d.weekday() in DRAW_WEEKDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# ΠΗΓΗ 1: ΠΛΗΡΕΣ CSV (κύρια πηγή)
# --------------------------------------------------------------------------

def fetch_reference_draws() -> dict:
    log(f"[2/4] Λήψη πλήρους ιστορικού από: {PRIMARY_CSV_URL}")
    raw = http_get(PRIMARY_CSV_URL).decode("utf-8-sig")
    draws = {}
    for row in csv.DictReader(raw.splitlines()):
        try:
            d = date(*time.strptime(row["date"].strip(), "%Y-%m-%d")[:3])
        except (KeyError, ValueError):
            continue
        try:
            nums = (int(row["n1"]), int(row["n2"]), int(row["n3"]),
                    int(row["n4"]), int(row["n5"]))
            euros = (int(row["e1"]), int(row["e2"]))
            draws[d] = validate_draw(d, nums, euros)
        except (KeyError, ValueError, TypeError):
            continue  # άκυρη γραμμή στην πηγή — προσπερνάται
    if not draws:
        raise RuntimeError("το κύριο CSV δεν περιέχει έγκυρες κληρώσεις")
    log(f"      ΟΚ — {len(draws)} κληρώσεις ({min(draws)} → {max(draws)})")
    return draws


# --------------------------------------------------------------------------
# ΠΗΓΗ 2: ΕΠΙΣΗΜΟ eurojackpot.org (επαλήθευση / fallback)
# --------------------------------------------------------------------------

def fetch_official_draw(d: date, silent: bool = False):
    """Επιστρέφει (nums, euros) αν η κλήρωση της ημερομηνίας d είναι
    δημοσιευμένη, None αν δεν βρέθηκε/δεν έχει δημοσιευτεί."""
    ymd = d.strftime("%Y%m%d")
    url = OFFICIAL_PROXY_URL.format(ymd=ymd)
    try:
        data = json.loads(http_get(url).decode("utf-8"))
    except (RuntimeError, json.JSONDecodeError) as err:
        if not silent:
            log(f"      [προειδοποίηση] official site μη διαθέσιμο για {d}: {err}")
        return None
    last = (data or {}).get("last") or {}
    if isinstance(last, dict):          # κανονική μορφή: 1 αντικείμενο
        last = [last]
    for item in last:                   # λίστα: ψάχνουμε τη ζητούμενη ημερομηνία
        if not isinstance(item, dict):
            continue
        dt = item.get("date") or {}
        try:
            actual = date(int(dt["year"]), int(dt["month"]), int(dt["day"]))
        except (KeyError, TypeError, ValueError):
            continue
        if actual != d:
            continue  # η κλήρωση της ημερομηνίας d δεν είναι (ακόμη) δημοσιευμένη
        nums, euros = item.get("numbers") or [], item.get("euroNumbers") or []
        if nums and euros:
            return tuple(int(n) for n in nums), tuple(int(e) for e in euros)
    return None


# --------------------------------------------------------------------------
# ΔΙΑΒΑΣΜΑ / ΕΓΓΡΑΦΗ ΤΟΥ ΔΙΚΟΥ ΣΟΥ CSV
# --------------------------------------------------------------------------

class CsvLayout:
    """Περιγραφή της δομής του CSV του χρήστη."""

    def __init__(self, header, delimiter, date_col, num_cols, euro_cols,
                 nums_single=None, euro_single=None, datefmt=None,
                 joiner: str = ",", num_pad=None, euro_pad=None,
                 extra_last=None, fill_map=None):
        self.header = header
        self.delimiter = delimiter
        self.date_col = date_col
        self.num_cols = num_cols          # λίστα 5 ονομάτων στηλ ή None
        self.euro_cols = euro_cols        # λίστα 2 ονομάτων στηλ ή None
        self.nums_single = nums_single    # όνομα συνδυασμένης στήλης ή None
        self.euro_single = euro_single
        self.datefmt = datefmt            # μορφή ημερομηνίας στο αρχείο
        self.joiner = joiner              # διαχωριστικό συνδυασμένης στήλης
        self.num_pad = num_pad            # πλάτος padding (π.χ. 2 → «05») ή None
        self.euro_pad = euro_pad
        self.extra_last = extra_last or {}  # τιμές extra στηλών από τελευταία γραμμή
        self.fill_map = fill_map or {}      # σταθερές τιμές από --fill-col

    @staticmethod
    def _fmt_num(v: int, pad) -> str:
        return f"{v:0{pad}d}" if pad else str(v)

    def row_for(self, d: date, nums, euros) -> dict:
        joiner = self.joiner
        row = {c: "" for c in self.header}
        dstr = d.strftime(self.datefmt) if self.datefmt else d.isoformat()
        row[self.date_col] = dstr
        if self.num_cols:
            for c, n in zip(self.num_cols, nums):
                row[c] = self._fmt_num(n, self.num_pad)
        else:
            row[self.nums_single] = joiner.join(
                self._fmt_num(n, self.num_pad) for n in nums)
        if self.euro_cols:
            for c, e in zip(self.euro_cols, euros):
                row[c] = self._fmt_num(e, self.euro_pad)
        else:
            row[self.euro_single] = joiner.join(
                self._fmt_num(e, self.euro_pad) for e in euros)
        # Υπόλοιπες στήλες (π.χ. Status): --fill-col > τιμή τελευταίας γραμμής > κενό
        known = {self.date_col, *(self.num_cols or []), *(self.euro_cols or []),
                 self.nums_single, self.euro_single}
        for c in self.header:
            if c in known:
                continue
            row[c] = self.fill_map.get(c, self.extra_last.get(c, ""))
        return row


def sniff_delimiter(first_line: str) -> str:
    for cand in (",", ";", "\t", "|"):
        if cand in first_line:
            return cand
    return ","


def load_existing(path: str):
    """Διαβάζει το υπάρχον CSV. Επιστρέφει (layout, {date: (nums,euros)}).
    Αν το αρχείο δεν υπάρχει → (None, {})."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None, {}
    except (OSError, csv.Error) as err:
        raise RuntimeError(f"αδυναμία ανάγνωσης {path}: {err}")

    if not lines or not lines[0].strip():
        return None, {}
    delim = sniff_delimiter(lines[0])
    reader = csv.DictReader(lines, delimiter=delim)
    header = [h for h in (reader.fieldnames or []) if h is not None]
    rows = [r for r in reader if r]
    norm = {h: norm_header(h) for h in header}
    header_only = not rows

    # Εύρεση στήλης ημερομηνίας
    date_col = next((h for h, n in norm.items() if n in DATE_COL_ALIASES), None)
    if date_col is None:
        raise RuntimeError(
            f"δεν βρέθηκε στήλη ημερομηνίας στο {path}. "
            f"Ορίστε τη με --date-col (κεφαλίδες: {header})"
        )

    # Εύρεση στηλών αριθμών (5 ξεχωριστές ή 1 συνδυασμένη)
    num_cols = [h for h, n in norm.items() if n in NUM_COL_ALIASES]
    nums_single = next((h for h, n in norm.items() if n in NUMS_SINGLE_ALIASES), None)
    euro_cols = [h for h, n in norm.items() if n in EURO_COL_ALIASES]
    euro_single = next((h for h, n in norm.items() if n in EURO_SINGLE_ALIASES), None)

    if not num_cols and not nums_single:
        raise RuntimeError(
            f"δεν βρέθηκαν στήλες αριθμών στο {path}. "
            f"Ορίστε τες με --num-cols / --nums-col (κεφαλίδες: {header})"
        )
    if not euro_cols and not euro_single:
        raise RuntimeError(
            f"δεν βρέθηκαν στήλες Euro/αστέρων στο {path}. "
            f"Ορίστε τες με --euro-cols / --euros-col (κεφαλίδες: {header})"
        )

    # Εύρεση μορφής ημερομηνίας από την 1η έγκυρη γραμμή
    datefmt = None
    for row in rows:
        parsed, fmt = parse_date_any(row.get(date_col, ""))
        if parsed:
            datefmt = fmt
            break
    if datefmt is None and not header_only:
        raise RuntimeError(
            f"καμία αναγνωρίσιμη μορφή ημερομηνίας στη στήλη «{date_col}» "
            f"του {path} (υποστηριζόμενες: {', '.join(DATE_FORMATS)})"
        )

    # Ανάγνωση υπαρχόντων draws (+ ανίχνευση padding και extra στηλών)
    draws: dict = {}
    joiner = ","
    num_pad = euro_pad = None
    extra_last: dict = {}
    extra_cols = [c for c in header
                  if c not in {date_col, *(num_cols or []), *(euro_cols or []),
                               nums_single, euro_single}]
    for row in rows:
        parsed, _ = parse_date_any(row.get(date_col, ""))
        if not parsed:
            continue  # κενή/καταστραμμένη γραμμή
        try:
            if num_cols:
                raws = [str(row[c]).strip() for c in num_cols[:5]]
                nums = tuple(int(float(v)) for v in raws)
            else:
                sample = row.get(nums_single, "") or ""
                for ch in (",", " ", "-", "/", ";", "|"):
                    if ch in sample:
                        joiner = ch
                        break
                raws = [x.strip() for x in sample.split(joiner) if x.strip()]
                nums = tuple(int(float(x)) for x in raws)
            if euro_cols:
                raws_e = [str(row[c]).strip() for c in euro_cols[:2]]
                euros = tuple(int(float(v)) for v in raws_e)
            else:
                raws_e = [x.strip() for x in (row.get(euro_single, "") or "").split(joiner) if x.strip()]
                euros = tuple(int(float(x)) for x in raws_e)
            nums, euros = validate_draw(parsed, nums, euros)
        except (ValueError, TypeError):
            continue  # άκυρη γραμμή — την προσπερνάμε
        # Ανίχνευση padding από την 1η έγκυρη γραμμή (π.χ. «05» → pad 2)
        if num_pad is None and raws and all(v.isdigit() for v in raws) \
                and any(v.startswith("0") for v in raws):
            num_pad = max(len(v) for v in raws)
        if euro_pad is None and raws_e and all(v.isdigit() for v in raws_e) \
                and any(v.startswith("0") for v in raws_e):
            euro_pad = max(len(v) for v in raws_e)
        extra_last = {c: (row.get(c) or "").strip() for c in extra_cols}
        if parsed in draws:
            log(f"      [προειδοποίηση] διπλή γραμμή για {parsed} — κρατάμε την 1η")
            continue
        draws[parsed] = nums, euros

    layout = CsvLayout(header, delim, date_col,
                       num_cols or None, euro_cols or None,
                       nums_single, euro_single, datefmt, joiner=joiner,
                       num_pad=num_pad, euro_pad=euro_pad,
                       extra_last=extra_last)
    if header_only:
        log(f"[1/4] Το {path} έχει μόνο κεφαλίδες — θα προστεθεί πλήρες ιστορικό.")
    else:
        log(f"[1/4] Υπάρχον αρχείο: {path} — {len(draws)} κληρώσεις, "
            f"νεότερη: {max(draws) if draws else '—'}")
    if extra_cols:
        fill_desc = ", ".join(f"{c}←«{extra_last.get(c, '')}»" for c in extra_cols)
        log(f"      Extra στήλες: {fill_desc} (νέες τιμές με --fill-col ΣΤΗΛΗ=ΤΙΜΗ)")
    return layout, draws


def append_rows(path: str, layout: CsvLayout | None, new_draws: dict) -> None:
    """Γράφει τις νέες κληρώσεις: νέο αρχείο (με DEFAULT_HEADER) ή append."""
    write_header = layout is None
    layout = layout or CsvLayout(DEFAULT_HEADER, ",", "date",
                                 DEFAULT_HEADER[1:6], DEFAULT_HEADER[6:8],
                                 None, None, "%Y-%m-%d")
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=layout.delimiter)
        if write_header:
            w.writerow(layout.header)
        for d in sorted(new_draws):
            nums, euros = new_draws[d]
            w.writerow([layout.row_for(d, nums, euros)[c]
                        for c in layout.header])


# --------------------------------------------------------------------------
# ΚΕΝΤΡΙΚΗ ΡΟΗ
# --------------------------------------------------------------------------

def collect_new_draws(existing, reference, verify) -> dict:
    """Υπολογίζει τις νέες κληρώσεις που λείπουν, με επαλήθευση.
    existing=None/{} σημαίνει bootstrap (πλήρες ιστορικό)."""
    today = date.today()
    new_draws: dict = {}

    if existing:
        anchor = max(existing)
        if anchor > today:
            die(f"το αρχείο περιέχει μελλοντική ημερομηνία ({anchor}) — "
                f"έλεγξε το ρολόι ή τη μορφή ημερομηνίας")
    else:
        # Bootstrap: ξεκινάμε με όλο το validated ιστορικό της κύριας πηγής
        anchor = max(reference)
        new_draws.update(reference)
        log(f"      Bootstrap: θα δημιουργηθεί πλήρες ιστορικό "
            f"({len(reference)} κληρώσεις έως {anchor})")

    need = expected_draw_dates(anchor, today)
    missing_dates = [d for d in need if d not in existing and d not in reference]

    for d in need:
        if d in existing:
            continue
        if d in reference:
            new_draws[d] = reference[d]

    # Καθυστέρηση της καθημερινής ενημέρωσης της κύριας πηγής; → επίσημη πηγή
    for d in missing_dates:
        log(f"      {d}: δεν υπάρχει στην κύρια πηγή — δοκιμή επίσημου site…")
        got = fetch_official_draw(d)
        if got:
            new_draws[d] = got
        else:
            log(f"      {d}: δεν έχει δημοσιευτεί ακόμη (φυσιολογικό αν μόλις "
                f"έγινε η κλήρωση) — θα συμπληρωθεί στο επόμενο τρέξιμο")

    if not new_draws:
        return {}

    # Επαλήθευση με το επίσημο site. Για πολύ μεγάλα σύνολα (bootstrap)
    # επαληθεύουμε μόνο τις 3 νεότερες — δεν έχει νόημα 1000 αιτήματα.
    if verify:
        to_check = sorted(new_draws)
        if len(to_check) > 30:
            log(f"[3/4] Bootstrap: επαλήθευση των 3 νεότερων από "
                f"{len(to_check)} κληρώσεων με το eurojackpot.org")
            to_check = to_check[-3:]
        else:
            log(f"[3/4] Επαλήθευση {len(to_check)} νέων κληρώσεων "
                f"με το eurojackpot.org…")
        for d in to_check:
            got = fetch_official_draw(d)
            if got is None:
                log(f"      [προειδοποίηση] {d}: official μη διαθέσιμο — "
                    f"καταχωρείται από την κύρια πηγή (validated repo)")
                continue
            if got != new_draws[d]:
                die(f"ΑΝΤΙΦΑΤΙΚΑ ΔΕΔΟΜΕΝΑ για {d}: κύρια πηγή={new_draws[d]} "
                    f"vs official={got}. ΤΙΠΟΤΑ δεν γράφτηκε. Έλεγξε χειροκίνητα!",
                    code=2)
            log(f"      {d}: ΟΚ {new_draws[d][0]} + {new_draws[d][1]}")
    return new_draws


def main(argv=None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # Python < 3.7

    ap = argparse.ArgumentParser(
        description="Αυτόματη ενημέρωση αρχείου κληρώσεων Eurojackpot")
    ap.add_argument("--csv", default="eurojackpot.csv",
                    help="διαδρομή του CSV αρχείου (προεπιλογή: eurojackpot.csv)")
    ap.add_argument("--dry-run", action="store_true",
                    help="δείχνει τι θα γράψει, χωρίς εγγραφή")
    ap.add_argument("--no-verify", action="store_true",
                    help="παράλειψη cross-check με το επίσημο eurojackpot.org")
    ap.add_argument("--fill-col", action="append", default=[], metavar="ΣΤΗΛΗ=ΤΙΜΗ",
                    help="σταθερή τιμή για extra στήλη στο CSV, π.χ. --fill-col Status=JACKPOT")
    args = ap.parse_args(argv)

    log("=== Eurojackpot Updater ===")
    layout, existing = load_existing(args.csv)
    if layout is not None and args.fill_col:
        for spec in args.fill_col:
            if "=" not in spec:
                die(f"μη έγκυρο --fill-col «{spec}» — μορφή: ΣΤΗΛΗ=ΤΙΜΗ")
            col, val = spec.split("=", 1)
            layout.fill_map[col.strip()] = val
        log("      --fill-col: " + ", ".join(f"{k}←«{v}»" for k, v in layout.fill_map.items()))
    reference = fetch_reference_draws()

    new_draws = collect_new_draws(existing, reference, verify=not args.no_verify)

    if not new_draws:
        log("[4/4] Καμία νέα κλήρωση — το αρχείο είναι ενημερωμένο. ✔")
        return

    log(f"[4/4] {'(DRY-RUN) ' if args.dry_run else ''}Προσθήκη "
        f"{len(new_draws)} κληρώσεων στο {args.csv}:")
    for d in sorted(new_draws):
        nums, euros = new_draws[d]
        log(f"      {d}  {nums}  {euros}")

    if args.dry_run:
        log("DRY-RUN: δεν γράφτηκε τίποτα.")
        return

    append_rows(args.csv, layout, new_draws)
    log(f"ΟΚ! Το {args.csv} ενημερώθηκε ({len(new_draws)} νέες κληρώσεις). ✔")


if __name__ == "__main__":
    main()
