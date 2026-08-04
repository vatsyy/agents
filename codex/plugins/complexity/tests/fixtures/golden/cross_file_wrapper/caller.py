from api import delete_folder


def cleanup(folder_ids):
    for folder_id in folder_ids:
        delete_folder(folder_id)
