import requests


class Client:
    def _request(self, url):
        return requests.get(url)

    def upload_many(self, urls):
        results = []
        for url in urls:
            results.append(self._request(url))
        return results


def save_documents(docs):
    for doc in docs:
        doc.db_set("processed", 1)


def load_item_names(frappe, names):
    values = []
    for name in names:
        values.append(frappe.db.get_value("Item", name, "item_name"))
    return values


def load_filtered_rows(frappe, filters):
    rows = []
    for filter_value in filters:
        rows.extend(frappe.get_all("Item", filters={"item_group": filter_value}))
    return rows


def load_django_widgets(Widget, keys):
    widgets = []
    for key in keys:
        widgets.append(Widget.objects.get(pk=key))
    return widgets


def load_sqlalchemy_rows(session, ids):
    rows = []
    for row_id in ids:
        rows.append(session.execute("select * from table where id=:id", {"id": row_id}))
    return rows
