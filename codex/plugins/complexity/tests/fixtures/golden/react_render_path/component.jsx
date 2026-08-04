export default function ItemList({ items, selectedIds }) {
  const visible = items
    .filter((item) => selectedIds.includes(item.id))
    .map((item) => ({ ...item, label: item.name.trim() }))
    .sort((left, right) => left.label.localeCompare(right.label));

  return <ul>{visible.map((item) => <li key={item.id}>{item.label}</li>)}</ul>;
}
