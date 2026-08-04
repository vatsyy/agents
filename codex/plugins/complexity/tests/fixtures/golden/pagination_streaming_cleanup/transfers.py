def list_pages(client):
    next_url = "/start"
    while next_url:
        response = client.request(next_url)
        next_url = response.next_url


def download_chunks(source, sink, remaining):
    while remaining:
        chunk = source.read(8192)
        sink.write(chunk)
        remaining -= len(chunk)


def cleanup_remote_folders(client, folder_ids):
    for folder_id in folder_ids:
        client.delete_folder(folder_id)
