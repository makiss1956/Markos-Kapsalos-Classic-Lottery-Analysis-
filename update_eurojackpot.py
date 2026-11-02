#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Αυτόματη ενημέρωση των κληρώσεων Eurojackpot στο data/eurojackpot_raw_history.csv.

Ο μηχανισμός (eurojackpot_updater.py — στο ίδιο φάκελο του repo):
  1. Κατεβάζει τις λείπουσες κληρώσεις από validated CSV που ενημερώνεται
     καθημερινά (raw.githubusercontent.com — χωρίς bot restrictions).
  2. Τις επαληθεύει μία-μία με το επίσημο eurojackpot.org.
  3. Εντοπίζει μόνο ό,τι λείπει από το αρχείο σου (backfill, idempotent) και
     γράφει στο ΑΚΡΙΒΕΣ format σου: Date;N1;..;N5;E1;E2;Status (semicolon,
     padding «05», κενό Status όπως οι τελευταίες χειροκίνητες γραμμές σου).

Κρατάμε το ΠΑΛΙΟ όνομα update_eurojackpot.py ώστε τα υπάρχοντα workflows
(update_history.yml και lottery-pipeline.yml) να δουλέψουν ΧΩΡΙΣ ΚΑΜΙΑ αλλαγή.
"""

from eurojackpot_updater import main

if __name__ == "__main__":
    main([
        "--csv", "data/eurojackpot_raw_history.csv",
        # Θέλεις σταθερή τιμή στη στήλη Status στα νέα rows; Ξεσχολίασε:
        # "--fill-col", "Status=JACKPOT",
    ])
