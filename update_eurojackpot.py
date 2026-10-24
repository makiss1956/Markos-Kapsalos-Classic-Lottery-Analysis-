import os
import pandas as pd

# Αξιόπιστη Raw πηγή δεδομένων Eurojackpot που δεν μπλοκάρεται από bot protections
REMOTE_CSV_URL = "https://raw.githubusercontent.com/szczyglis-dev/python-lottery-dataset-analyze/main/eurojackpot.csv"
LOCAL_CSV_PATH = "data/eurojackpot_raw_history.csv"

def update_dataset():
    print("Λήψη ενημερωμένων δεδομένων Eurojackpot...")
    try:
        # Ανάγνωση απευθείας από το raw link χωρίς bot filtering
        df_remote = pd.read_csv(REMOTE_CSV_URL)
    except Exception as e:
        print(f"Σφάλμα κατά τη λήψη των δεδομένων: {e}")
        return

    # Δημιουργία φακέλου data αν δεν υπάρχει
    os.makedirs(os.path.dirname(LOCAL_CSV_PATH), exist_ok=True)

    # Αποθήκευση στο ακριβές μονοπάτι του έργου σας
    df_remote.to_csv(LOCAL_CSV_PATH, index=False)
    print(f"Το αρχείο {LOCAL_CSV_PATH} ενημερώθηκε επιτυχώς!")

if __name__ == "__main__":
    update_dataset()
