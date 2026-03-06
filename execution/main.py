import time
import os
import sys

print("===== BOT ALIVE AND LOUD =====")
print("Current working directory:", os.getcwd())
print("Files in current dir:", os.listdir("."))
print("PYTHONPATH:", os.environ.get("PYTHONPATH", "not set"))
print("All env vars count:", len(os.environ))
print("Sample env var:", os.environ.get("RENDER", "no RENDER var"))

for i in range(1, 21):
    print(f"TEST LINE {i} — გამარჯობა Render! {time.strftime('%H:%M:%S')}")
    sys.stdout.flush()  # იძულებითი flush, რომ დაუყოვნებლივ გამოჩნდეს
    time.sleep(1)

print("===== TEST FINISHED =====")
time.sleep(300)  # დამატებითი დრო ლოგების დასანახად
