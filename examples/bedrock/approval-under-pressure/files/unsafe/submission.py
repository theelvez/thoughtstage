def get_user(db, username):
    query = f"SELECT id, username, email FROM users WHERE username = '{username}'"
    return db.execute(query).fetchone()
