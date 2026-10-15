import os
import sys
import subprocess

key_path = os.path.join(os.environ["TEMP"], "test_key.pem")

if len(sys.argv) > 1 and sys.argv[1] == "--scp":
    # remote_exec.py --scp local_file remote_file
    local_f = sys.argv[2]
    remote_f = sys.argv[3]
    res = subprocess.run(
        ["scp", "-i", key_path, "-o", "StrictHostKeyChecking=no", local_f, f"root@124.220.54.64:{remote_f}"],
        capture_output=True,
        text=True
    )
elif len(sys.argv) > 1 and sys.argv[1] == "--script":
    # remote_exec.py --script local_script.sh
    with open(sys.argv[2], "rb") as f:
        script_bytes = f.read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    res = subprocess.run(
        ["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", "root@124.220.54.64", "bash -s"],
        input=script_bytes,
        capture_output=True
    )
    if res.stdout:
        sys.stdout.buffer.write(res.stdout)
    if res.stderr:
        sys.stderr.buffer.write(res.stderr)
    sys.exit(res.returncode)
else:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "uname -a"
    res = subprocess.run(
        ["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8", "root@124.220.54.64", cmd],
        capture_output=True,
        text=True
    )

if res.stdout:
    print(res.stdout)
if res.stderr:
    print(res.stderr, file=sys.stderr)
sys.exit(res.returncode)
