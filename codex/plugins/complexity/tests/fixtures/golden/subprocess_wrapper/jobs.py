import subprocess


def run_job(command):
    return subprocess.run(command, check=False)


def run_all(commands):
    results = []
    for command in commands:
        results.append(run_job(command))
    return results
