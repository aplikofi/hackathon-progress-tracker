from flask import Flask
from config import Config
from extensions import db
from routes.auth_routes import auth_bp
from routes.hackathon_routes import hackathon_bp
from routes.file_routes import file_bp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def auto_migrate_db(engine):
    """Executes safe ALTER TABLE statements to add missing columns to PostgreSQL or SQLite databases."""
    from sqlalchemy import text, inspect
    migrations = [
        ("hackathons", "is_idea_submission", "ALTER TABLE hackathons ADD COLUMN is_idea_submission BOOLEAN DEFAULT FALSE;"),
        ("hackathons", "header_note", "ALTER TABLE hackathons ADD COLUMN header_note VARCHAR(255);"),
        ("participated_events", "is_idea_submission", "ALTER TABLE participated_events ADD COLUMN is_idea_submission BOOLEAN DEFAULT FALSE;"),
        ("participated_events", "header_note", "ALTER TABLE participated_events ADD COLUMN header_note VARCHAR(255);"),
    ]
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
    except Exception as e:
        logger.error(f"Failed to inspect database tables: {e}")
        existing_tables = []

    for table, col, alter_sql in migrations:
        try:
            if table in existing_tables:
                cols = [c['name'] for c in inspector.get_columns(table)]
                if col not in cols:
                    logger.info(f"Adding missing column '{col}' to table '{table}'...")
                    with engine.begin() as conn:
                        conn.execute(text(alter_sql))
                    logger.info(f"Successfully added column '{col}' to '{table}'.")
            else:
                # If table check wasn't possible via inspect, try ALTER TABLE IF NOT EXISTS on Postgres
                if engine.dialect.name == 'postgresql':
                    pg_sql = alter_sql.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
                    with engine.begin() as conn:
                        conn.execute(text(pg_sql))
        except Exception as e:
            logger.warning(f"Migration check/execution for {table}.{col} skipped: {e}")

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions
    db.init_app(app)
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(hackathon_bp)
    app.register_blueprint(file_bp)
    
    # Initialize database tables and migrations cleanly
    with app.app_context():
        try:
            dialect = db.engine.dialect.name
            logger.info(f"Database dialect: {dialect} | Using PostgreSQL: {dialect == 'postgresql'}")
            if dialect != 'postgresql':
                logger.warning("Running on local SQLite database. On Render, ensure DATABASE_URL is set in Render Environment variables.")
        except Exception as e:
            logger.error(f"Could not inspect database dialect: {e}")
            
        try:
            db.create_all()
            logger.info("db.create_all() checked successfully.")
        except Exception as e:
            logger.error(f"db.create_all() failed: {e}")
            
        try:
            auto_migrate_db(db.engine)
            logger.info("auto_migrate_db checked successfully.")
        except Exception as e:
            logger.error(f"auto_migrate_db failed: {e}")
            
    return app

app = create_app()

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
