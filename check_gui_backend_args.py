import inspect
from SrtSync import SrtSync

sig = inspect.signature(SrtSync.sync)
print(sig)

required = {"min_target_missing_words", "ms_per_token", "min_gap_ms"}
missing = required - set(sig.parameters)
if missing:
    raise SystemExit(f"Missing backend args: {missing}")

bad = {"min_missing_words"} & set(sig.parameters)
if bad:
    raise SystemExit(f"Old backend args still present: {bad}")

print("OK: GUI/backend argument names are current.")
