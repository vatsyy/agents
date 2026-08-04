import requests


def delete_folder(folder_id):
    return requests.delete(f"https://example.invalid/folders/{folder_id}")
