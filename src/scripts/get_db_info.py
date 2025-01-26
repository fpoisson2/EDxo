import sqlite3

# Connect to the database
conn = sqlite3.connect('programme.db')
cursor = conn.cursor()

# Get all table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

# Print the schema of each table
for table in tables:
    table_name = table[0]
    print(f"Schema for {table_name}:")
    cursor.execute(f"PRAGMA table_info({table_name});")
    schema = cursor.fetchall()
    for column in schema:
        print(column)
    print("\n")

# Close the connection
conn.close()