"""Require the real table test to reject floor rounding with an actionable diff."""

import subprocess
import sys
from pathlib import Path

result = subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_t78_billing_answers.py",
        "-k",
        "KT-10",
        "-p",
        "tests.t78_mutation_plugin",
        "-q",
    ],
    cwd=Path(__file__).resolve().parents[1],
    capture_output=True,
    text=True,
    timeout=60,
    check=False,
)
output = result.stdout + result.stderr
required = ["KT-10", "energy[1]", "dap_an_tay=3", "ket_qua_ma=2", "chenh=-1 dong"]
if result.returncode != 1 or not all(text in output for text in required):
    print(output)
    raise SystemExit("T-78 mutation was not rejected with the expected diagnostic")
print(
    "T-78 mutation detected: KT-10 energy[1] amount_vnd; dap_an_tay=3; ket_qua_ma=2; chenh=-1 dong; pytest exit=1."
)
