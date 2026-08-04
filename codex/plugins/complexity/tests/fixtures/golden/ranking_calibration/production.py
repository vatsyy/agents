def load_each_record(frappe, names):
    values = []
    for name in names:
        values.append(frappe.db.get_value("Item", name, "item_name"))
    return values


MAX_RETRIES = 3


def retry_request(client, url):
    for attempt in range(MAX_RETRIES):
        response = client.request(url)
        if response.ok:
            return response
        if response.status_code == 400:
            return None
        if response.status_code == 401:
            return None
        if response.status_code == 403:
            return None
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            continue
    return None


def stream_chunks(source):
    digest = 0
    while chunk := source.read(8192):
        digest += len(chunk)
    return digest


def list_pages(client):
    next_url = "/start"
    while next_url:
        response = client.request(next_url)
        next_url = response.next_url
