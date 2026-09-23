import subprocess

def run_and_wait(cmd):
    process = subprocess.Popen(cmd, shell=True)
    while process.poll() is None:
        pass
    return process.returncode