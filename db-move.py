import psycopg2
from psycopg2 import sql
import configparser
import os
import logging
from datetime import datetime

# Set up logging
def setup_logging():
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, f'db_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

# Function to read database config from an .ini file
def read_db_config(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    
    config = configparser.ConfigParser()
    config.read(file_path)
    
    try:
        return {
            'dbname': config['postgresql']['database'],
            'user': config['postgresql']['user'],
            'password': config['postgresql']['password'],
            'host': config['postgresql']['host'],
            'port': config['postgresql']['port']
        }
    except KeyError as e:
        raise KeyError(f"Missing configuration key in {file_path}: {str(e)}")

# Function to establish database connection
def create_db_connection(conn_params, db_name):
    try:
        conn = psycopg2.connect(**conn_params)
        logger.info(f"Successfully connected to {db_name} database")
        return conn
    except psycopg2.Error as e:
        logger.error(f"Error connecting to {db_name} database: {str(e)}")
        raise

# Function to count rows in a table
def count_rows(cursor, table_name):
    try:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name))
        )
        return cursor.fetchone()[0]
    except psycopg2.Error:
        return 0

# Function to get table columns
def get_table_columns(cursor, table_name):
    cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """, (table_name,))
    return cursor.fetchall()

# Function to create table with matching structure
def create_matching_table(source_cur, target_cur, table_name, target_conn):
    try:
        # Get column information from source table
        columns = get_table_columns(source_cur, table_name)
        
        # Generate CREATE TABLE statement
        columns_def = ', '.join(
            f"{sql.Identifier(col[0]).as_string(target_cur)} {col[1]}"
            for col in columns
        )
        
        create_table_query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {} ({})
        """).format(
            sql.Identifier(table_name),
            sql.SQL(columns_def)
        )
        
        target_cur.execute(create_table_query)
        target_conn.commit()
        logger.info(f"Created table {table_name} in target database")
        
    except psycopg2.Error as e:
        logger.error(f"Error creating table {table_name}: {str(e)}")
        target_conn.rollback()
        raise

# Function to get existing timestamps from target table
def get_existing_timestamps(target_cur, table_name):
    try:
        target_cur.execute(
            sql.SQL("SELECT timestamp FROM {} ORDER BY timestamp").format(
                sql.Identifier(table_name)
            )
        )
        return set(row[0] for row in target_cur.fetchall())
    except psycopg2.Error:
        return set()

# Function to copy data between databases
def copy_data(source_conn, target_conn, table_name):
    total_rows_inserted = 0
    skipped_rows = 0
    
    try:
        with source_conn.cursor() as source_cur, target_conn.cursor() as target_cur:
            # Count rows before migration
            source_rows = count_rows(source_cur, table_name)
            target_rows_before = count_rows(target_cur, table_name)
            
            logger.info(f"Table {table_name} - Source rows: {source_rows}, Target rows before: {target_rows_before}")
            
            # Get existing timestamps from target
            existing_timestamps = get_existing_timestamps(target_cur, table_name)
            
            # Get all data from source
            source_cur.execute(
                sql.SQL("SELECT * FROM {} ORDER BY timestamp").format(
                    sql.Identifier(table_name)
                )
            )
            columns = [desc[0] for desc in source_cur.description]
            timestamp_idx = columns.index('timestamp')
            
            # Create the placeholder string for the VALUES clause
            placeholders = sql.SQL(', ').join([sql.SQL('%s') for _ in columns])
            
            # Prepare the insert query
            insert_query = sql.SQL("""
                INSERT INTO {} ({}) VALUES ({})
            """).format(
                sql.Identifier(table_name),
                sql.SQL(', ').join(map(sql.Identifier, columns)),
                placeholders
            )
            
            # Process rows in batches
            batch = []
            batch_size = 1000
            
            while True:
                rows = source_cur.fetchmany(batch_size)
                if not rows:
                    break
                
                # Filter out rows with existing timestamps
                new_rows = [
                    row for row in rows 
                    if row[timestamp_idx] not in existing_timestamps
                ]
                
                skipped_rows += len(rows) - len(new_rows)
                
                if new_rows:
                    # Add new timestamps to existing set
                    existing_timestamps.update(row[timestamp_idx] for row in new_rows)
                    
                    # Insert new rows
                    target_cur.executemany(insert_query.as_string(target_cur), new_rows)
                    target_conn.commit()
                    
                    total_rows_inserted += len(new_rows)
                    logger.info(f"Inserted {len(new_rows)} new rows for table {table_name}")
            
            # Count rows after migration
            target_rows_after = count_rows(target_cur, table_name)
            
            logger.info(f"""
Table {table_name} migration summary:
- Source rows: {source_rows}
- Target rows before: {target_rows_before}
- Target rows after: {target_rows_after}
- Rows inserted: {total_rows_inserted}
- Rows skipped (duplicates): {skipped_rows}
- New rows added: {target_rows_after - target_rows_before}
""")
            
            return total_rows_inserted
            
    except psycopg2.Error as e:
        logger.error(f"Error copying data for table {table_name}: {str(e)}")
        target_conn.rollback()
        raise

def main():
    try:
        # Paths to the .ini files
        option_chain_ini_path = os.path.join('api', 'ini', 'OptionChain.ini')
        option_data_ini_path = os.path.join('api', 'ini', 'optiondata.ini')

        # Read the connection parameters from the .ini files
        option_chain_conn_params = read_db_config(option_chain_ini_path)
        option_data_conn_params = read_db_config(option_data_ini_path)

        # Connect to both databases
        source_conn = create_db_connection(option_chain_conn_params, "OptionChain")
        target_conn = create_db_connection(option_data_conn_params, "OptionData")

        # Get list of tables from source database
        with source_conn.cursor() as source_cur:
            source_cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
            tables = source_cur.fetchall()

        total_tables = len(tables)
        tables_processed = 0
        total_rows_migrated = 0

        # Process each table
        for table in tables:
            table_name = table[0]
            tables_processed += 1
            
            logger.info(f"Processing table {table_name} ({tables_processed}/{total_tables})")
            
            # Create table in target if it doesn't exist
            create_matching_table(source_conn.cursor(), target_conn.cursor(), table_name, target_conn)
            
            # Copy data
            rows_migrated = copy_data(source_conn, target_conn, table_name)
            total_rows_migrated += rows_migrated

        logger.info(f"""
Migration Summary:
----------------
Total tables processed: {tables_processed}
Total rows migrated: {total_rows_migrated}
""")

    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        raise

    finally:
        # Close connections
        if 'source_conn' in locals():
            source_conn.close()
        if 'target_conn' in locals():
            target_conn.close()
        logger.info("Database connections closed")

if __name__ == "__main__":
    logger = setup_logging()
    logger.info("Starting database migration")
    main()
