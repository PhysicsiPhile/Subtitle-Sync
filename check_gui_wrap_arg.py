from pathlib import Path
txt = Path("gui.py").read_text(encoding="utf-8", errors="ignore")

assert "self.wrap_chars_var" in txt, "GUI wrap field missing"
assert "wrap_chars = int(self.wrap_chars_var.get().strip())" in txt, "wrap_chars variable is not parsed"
assert "wrap_chars=wrap_chars" in txt, "wrap_chars is not passed to backend"

print("OK: GUI defines and passes wrap_chars.")
