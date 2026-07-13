import subprocess, os
cwd = os.getcwd()
env = os.environ.copy()
env["GIT_TERMINAL_PROMPT"] = "0"
r = subprocess.run(
    ["git", "push", "origin", "main"],
    capture_output=True, text=True, timeout=60, env=env, cwd=cwd
)
out = os.path.join(cwd, "_push_out.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("EXIT: " + str(r.returncode) + "\n")
    f.write(r.stdout + "\n")
    f.write(r.stderr + "\n")
