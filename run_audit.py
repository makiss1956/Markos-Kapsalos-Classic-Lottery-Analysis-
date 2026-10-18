from modules.stochastic_auditor import StochasticAuditor
import os

if __name__ == "__main__":
    # Διαδρομή προς το αρχείο κληρώσεων
    data_path = os.path.join("data", "ΚΑΤΑΛΟΓΟΣ ΚΛΗΡΩΣΕΩΝ ΓΙΟΥΡΟΤΖΑΚ ΣΩΣΤΟΣ ΜΕ ΤΖΑΚΠΟΤ 12-26.txt")
    
    auditor = StochasticAuditor(data_path)
    auditor.run_full_audit()
