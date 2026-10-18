from modules.stochastic_auditor import StochasticAuditor
import os

if __name__ == "__main__":
    # Διαδρομή προς το σωστό αρχείο κληρώσεων στο GitHub
    data_path = os.path.join("data", "eurojackpot_raw_history.csv")
    
    auditor = StochasticAuditor(data_path)
    auditor.run_full_audit()
