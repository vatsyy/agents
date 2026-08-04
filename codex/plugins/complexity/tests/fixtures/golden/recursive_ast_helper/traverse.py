def target_names(target):
    if isinstance(target, Name):
        return {target.id}
    if isinstance(target, (Tuple, List)):
        return {name for item in target.elts for name in target_names(item)}
    return set()
