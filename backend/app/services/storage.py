"""Small dialect-aware atomic upsert shared by persistent cache metadata."""
def upsert(db, model, rows, keys):
    if not rows:
        return
    dialect = db.get_bind().dialect.name
    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise ValueError('EcoMonitor supports SQLite and PostgreSQL')
    # Bounded batches also respect SQLite bind parameter limits.
    for offset in range(0,len(rows),100):
        statement = insert(model).values(rows[offset:offset+100])
        db.execute(statement.on_conflict_do_update(index_elements=keys,
            set_={column: getattr(statement.excluded,column) for column in rows[0] if column not in keys}))
