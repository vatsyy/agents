def collect_existing(paths):
    existing = []
    for path in paths:
        if path.exists():
            existing.append(path)
    return existing
