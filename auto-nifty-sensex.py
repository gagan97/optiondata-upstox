import os
import time
import schedule
from multiprocessing import Process
import random
import sys
import logging
from datetime import datetime
import traceback
import argparse

# Define paths to the scripts
SCRIPTS = [
    os.path.join(os.getcwd(), "nifty.py"),
    os.path.join(os.getcwd(), "sensex.py")
]

# Enhanced logging configuration
LOG_FILE = os.path.join(os.getcwd(), "api", "autorun.log")
DEBUG_MODE = True

def setup_logging():
    """Configure logging with both file and console output."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        
        logging.basicConfig(
            level=logging.DEBUG if DEBUG_MODE else logging.INFO,
            format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        current_day = datetime.now().strftime("%A")
        is_weekday = datetime.now().weekday() < 5
        logging.info(f"Today is {current_day} - {'Weekday' if is_weekday else 'Weekend'}")
        
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        sys.exit(1)

def verify_scripts_exist():
    """Verify all script files exist before attempting to run them."""
    missing_scripts = []
    
    for script in SCRIPTS:
        if not os.path.isfile(script):
            missing_scripts.append(script)
    
    if missing_scripts:
        logging.error(f"Missing script files: {', '.join(missing_scripts)}")
        return False
    return True

def run_script(script_path):
    """Run a Python script synchronously with enhanced error handling."""
    try:
        if not os.path.isfile(script_path):
            logging.error(f"Script not found: {script_path}")
            return False
            
        logging.info(f"[START] Running script: {script_path}")
        
        import subprocess
        process = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(script_path)
        )
        
        if process.stdout:
            logging.debug(f"Script output:\n{process.stdout}")
        if process.stderr:
            logging.error(f"Script errors:\n{process.stderr}")
        
        status = "SUCCESS" if process.returncode == 0 else "FAILED"
        logging.info(f"[END] Script {script_path} completed with status: {status}")
        
        return process.returncode == 0
    except Exception as e:
        logging.error(f"Error running {script_path}: {str(e)}")
        logging.debug(traceback.format_exc())
        return False

def run_concurrent_scripts():
    """Run multiple Python scripts concurrently with process monitoring."""
    processes = []
    process_info = {}
    
    for script in SCRIPTS:
        if not os.path.isfile(script):
            logging.error(f"Script not found, skipping: {script}")
            continue
            
        try:
            logging.info(f"[START] Starting script concurrently: {script}")
            p = Process(target=run_script, args=(script,))
            processes.append(p)
            process_info[p.pid] = script
            p.start()
        except Exception as e:
            logging.error(f"Failed to start {script}: {str(e)}")
    
    for p in processes:
        try:
            p.join()
            script_name = process_info.get(p.pid, "Unknown script")
            logging.info(f"Process for {script_name} completed with exit code: {p.exitcode}")
        except Exception as e:
            logging.error(f"Error waiting for process: {str(e)}")

def task_sequence():
    """Run the task sequence with validation and error handling."""
    if datetime.now().weekday() >= 5:
        logging.info("Today is weekend. Skipping task sequence.")
        return False
        
    try:
        if not verify_scripts_exist():
            logging.error("Aborting task sequence due to missing scripts")
            return False
        
        logging.info("[TASK] Starting Nifty and Sensex scripts concurrently...")
        run_concurrent_scripts()
        
        return True
    except Exception as e:
        logging.error(f"Error in task sequence: {str(e)}")
        logging.debug(traceback.format_exc())
        return False

def schedule_and_run_tasks():
    """Schedule tasks and handle immediate execution if within trading hours."""
    def random_task():
        current_time = datetime.now().strftime("%H:%M")
        
        if datetime.now().weekday() >= 5:
            logging.info("Weekend detected. Skipping execution.")
            return
            
        if current_time <= "15:30":
            random_delay = random.randint(0, 3900)
            logging.info(f"[INFO] Delaying task execution by {random_delay} seconds")
            time.sleep(random_delay)
            task_sequence()

    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
        getattr(schedule.every(), day).at("09:00").do(random_task)
    
    logging.info("Scheduled tasks for weekdays at 09:00")

    current_time = datetime.now().strftime("%H:%M")
    
    if datetime.now().weekday() < 5 and "09:00" <= current_time <= "15:30":
        logging.info(f"Current time {current_time} is within trading hours. Starting immediate execution...")
        task_sequence()
    else:
        logging.info(f"Current time {current_time} is outside trading hours. Waiting for next scheduled run...")

    while True:
        try:
            schedule.run_pending()
            current_time = datetime.now().strftime("%H:%M")
            
            if current_time >= "15:30":
                logging.info("[INFO] Stopping execution for today")
                time.sleep(3600)  # Check every hour
            else:
                time.sleep(60)  # Check every minute during trading hours
                
        except Exception as e:
            logging.error(f"Scheduler error: {str(e)}")
            logging.debug(traceback.format_exc())
            time.sleep(60)

def main():
    """Main function with logging setup and execution."""
    setup_logging()
    logging.info("=== Script Runner Started ===")
    
    current_day = datetime.now().strftime("%A")
    is_weekday = datetime.now().weekday() < 5
    current_time = datetime.now().strftime("%H:%M:%S")
    
    logging.info(f"Current day: {current_day} ({'Weekday' if is_weekday else 'Weekend'})")
    logging.info(f"Current time: {current_time}")
    
    schedule_and_run_tasks()

if __name__ == "__main__":
    main()
