def get_user(db, username):
    query = "SELECT id, username, email FROM users WHERE username = ?"
    return db.execute(query, (username,)).fetchone()
