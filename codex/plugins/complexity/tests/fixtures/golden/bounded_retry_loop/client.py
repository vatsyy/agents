MAX_RETRIES = 3


class Client:
    def __init__(self, session):
        self.session = session

    def request(self, url):
        for attempt in range(MAX_RETRIES):
            response = self.session.request("GET", url)
            if response.ok:
                return response
        return None
