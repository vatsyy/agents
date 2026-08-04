async function loadUsers(ids) {
  const users = [];
  for (const id of ids) {
    const response = await fetch(`/api/users/${id}`);
    users.push(await response.json());
  }
  return users;
}
