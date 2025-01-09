import os
import time
import schedule
from multiprocessing import Process
import random
import sys
import logging
from datetime import datetime
import traceback
import calendar
import argparse
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.live import Live
from rich.layout import Layout
from rich.text import Text

# Initialize Rich console
console = Console()

# Define paths to the scripts - Update these with full paths
SCRIPTS = {
    "logoutCLI": os.path.join(os.getcwd(), "logoutCLI.py"),
    "loginCLI": os.path.join(os.getcwd(), "loginCLI.py"),
    "options": [
        os.path.join(os.getcwd(), "historic_optionChain_Bankex.py"),
        os.path.join(os.getcwd(), "historic_optionChain_BankNifty.py"),
        os.path.join(os.getcwd(), "historic_optionChain_FinNifty.py"),
        os.path.join(os.getcwd(), "historic_optionChain_Nifty50.py"),
        os.path.join(os.getcwd(), "historic_optionChain_NiftyMidcpSelect.py"),
        os.path.join(os.getcwd(), "historic_optionChain_NiftyNXT50.py"),
        os.path.join(os.getcwd(), "historic_optionChain_Sensex.py")
    ]
}

# Enhanced logging configuration
LOG_FILE = os.path.join(os.getcwd(), "api", "autorun.log")
DEBUG_MODE = True

def is_trading_hours():
    """Check if current time is within trading hours (9:00-15:30)."""
    current_time = datetime.now().time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("15:30", "%H:%M").time()
    return start_time <= current_time <= end_time

def is_weekday():
    """Check if today is a weekday."""
    return datetime.now().weekday() < 5

def get_current_day():
    """Get current day name and check if it's a weekday."""
    current_day = datetime.now().strftime("%A")
    is_weekday_val = datetime.now().weekday() < 5
    return current_day, is_weekday_val

def verify_scripts_exist():
    """Verify all script files exist before attempting to run them."""
    missing_scripts = []
    
    for script_type in ["logoutCLI", "loginCLI"]:
        if not os.path.isfile(SCRIPTS[script_type]):
            missing_scripts.append(SCRIPTS[script_type])
    
    for script in SCRIPTS["options"]:
        if not os.path.isfile(script):
            missing_scripts.append(script)
    
    if missing_scripts:
        console.print(f"[red]Missing script files: {', '.join(missing_scripts)}")
        return False
    return True

def create_dashboard():
    """Create a rich dashboard layout"""
    layout = Layout()
    layout.split_column(
        Layout(name="header"),
        Layout(name="main"),
        Layout(name="footer")
    )
    return layout

def update_header(layout):
    """Update dashboard header with current status"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_day, is_weekday_val = get_current_day()
    trading_status = "TRADING HOURS" if is_trading_hours() else "NON-TRADING HOURS"
    status_color = "green" if is_trading_hours() else "red"
    
    header = Table.grid()
    header.add_column(style="bold cyan", justify="center")
    header.add_row(f"🕒 {current_time}")
    header.add_row(f"📅 {current_day} ({'Weekday' if is_weekday_val else 'Weekend'})")
    header.add_row(f"[{status_color}]{trading_status}")
    
    layout["header"].update(Panel(header, title="System Status", border_style="blue"))

def create_script_table():
    """Create a table showing script status"""
    table = Table(title="Script Status", show_header=True, header_style="bold magenta")
    table.add_column("Script", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Last Run", justify="right")
    return table

def run_script_with_progress(script_path):
    """Run a Python script with progress bar"""
    try:
        script_name = os.path.basename(script_path)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task(f"Running {script_name}...", total=100)
            
            import subprocess
            process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Simulate progress while script is running
            while process.poll() is None:
                progress.update(task, advance=1)
                time.sleep(0.1)
            
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                progress.update(task, completed=100)
                console.print(f"[green]✓ {script_name} completed successfully")
            else:
                console.print(f"[red]✗ {script_name} failed")
                if stderr:
                    console.print(f"[red]Error: {stderr}")
                    
            return process.returncode == 0
            
    except Exception as e:
        console.print(f"[red]Error running {script_path}: {str(e)}")
        return False

def run_concurrent_scripts(script_paths):
    """Run multiple Python scripts concurrently with progress tracking"""
    with console.status("[bold green]Running concurrent scripts...") as status:
        processes = []
        process_info = {}
        
        for script in script_paths:
            if not os.path.isfile(script):
                console.print(f"[red]Script not found, skipping: {script}")
                continue
                
            try:
                p = Process(target=run_script_with_progress, args=(script,))
                processes.append(p)
                process_info[p.pid] = script
                p.start()
            except Exception as e:
                console.print(f"[red]Failed to start {script}: {str(e)}")
        
        for p in processes:
            p.join()
            script_name = os.path.basename(process_info.get(p.pid, "Unknown script"))
            status_color = "green" if p.exitcode == 0 else "red"
            console.print(f"[{status_color}]{script_name}: {'Completed' if p.exitcode == 0 else 'Failed'}")

def task_sequence():
    """Run the task sequence with visual progress tracking"""
    layout = create_dashboard()
    
    with Live(layout, refresh_per_second=1) as live:
        update_header(layout)
        
        if not is_weekday():
            console.print("[yellow]Today is weekend. Skipping task sequence.")
            return False
        
        try:
            if not verify_scripts_exist():
                console.print("[red]Aborting task sequence due to missing scripts")
                return False
            
            # Execute scripts with progress tracking
            console.print("\n[bold cyan]Starting Task Sequence[/bold cyan]")
            
            # LogoutCLI
            if not run_script_with_progress(SCRIPTS["logoutCLI"]):
                return False
            
            time.sleep(5)
            
            # LoginCLI
            if not run_script_with_progress(SCRIPTS["loginCLI"]):
                return False
            
            time.sleep(5)
            
            # Option chain scripts
            console.print("\n[bold cyan]Running Option Chain Scripts[/bold cyan]")
            run_concurrent_scripts(SCRIPTS["options"])
            
            return True
            
        except Exception as e:
            console.print(f"[red]Error in task sequence: {str(e)}")
            if DEBUG_MODE:
                console.print(traceback.format_exc())
            return False

def schedule_and_run_tasks():
    """Schedule tasks and handle immediate execution if within trading hours."""
    def random_task():
        current_day, is_weekday_val = get_current_day()
        current_time = datetime.now().strftime("%H:%M")
        
        console.print(f"[cyan]Checking schedule: {current_day} at {current_time}")
        
        if not is_weekday_val:
            console.print("[yellow]Weekend detected. Skipping execution.")
            return
            
        if current_time <= "15:30":
            random_delay = random.randint(0, 3900)
            console.print(f"[cyan]Delaying task execution by {random_delay} seconds")
            time.sleep(random_delay)
            task_sequence()

    # Schedule for future days
    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
        getattr(schedule.every(), day).at("09:00").do(random_task)
    
    console.print("[green]Scheduled tasks for weekdays at 09:00")

    # Check for immediate execution
    current_time = datetime.now().strftime("%H:%M")
    current_day, is_weekday_val = get_current_day()
    
    if is_weekday_val and "09:00" <= current_time <= "15:30":
        console.print(f"[green]Current time {current_time} is within trading hours. Starting immediate execution...")
        task_sequence()
    else:
        console.print(f"[yellow]Current time {current_time} is outside trading hours. Waiting for next scheduled run...")

    # Continue with regular schedule
    while True:
        try:
            schedule.run_pending()
            current_time = datetime.now().strftime("%H:%M")
            
            if current_time >= "15:30":
                console.print(f"[yellow]Stopping execution for today ({current_day})")
                time.sleep(3600)  # Check every hour
            else:
                time.sleep(60)  # Check every minute during trading hours
                
        except Exception as e:
            console.print(f"[red]Scheduler error: {str(e)}")
            if DEBUG_MODE:
                console.print(traceback.format_exc())
            time.sleep(60)

def execute_loginCLI_logoutCLI():
    """Execute logoutCLI and loginCLI scripts once for current day."""
    console.print("[cyan]Starting one-time execution of logoutCLI and loginCLI scripts")
    
    try:
        # Execute logoutCLI script
        if not run_script_with_progress(SCRIPTS["logoutCLI"]):
            console.print("[red]One-time logoutCLI script failed")
            return False
        
        time.sleep(5)
        
        # Execute loginCLI script
        if not run_script_with_progress(SCRIPTS["loginCLI"]):
            console.print("[red]One-time loginCLI script failed")
            return False
            
        console.print("[green]One-time execution completed successfully")
        return True
        
    except Exception as e:
        console.print(f"[red]Error in one-time execution: {str(e)}")
        if DEBUG_MODE:
            console.print(traceback.format_exc())
        return False

def main():
    """Main function with rich console output"""
    parser = argparse.ArgumentParser(description='Script Runner with multiple modes')
    parser.add_argument('--mode', choices=['schedule', 'loginCLI-logoutCLI'], 
                       default='schedule',
                       help='Execution mode: schedule (default) or loginCLI-logoutCLI')
    
    args = parser.parse_args()
    
    console.print("[bold blue]=== Script Runner Started ===[/bold blue]")
    
    layout = create_dashboard()
    with Live(layout, refresh_per_second=1):
        update_header(layout)
        
        if args.mode == 'loginCLI-logoutCLI':
            console.print("[cyan]Running in loginCLI-logoutCLI mode")
            execute_loginCLI_logoutCLI()
            sys.exit(0)
        else:
            console.print("[cyan]Running in schedule mode")
            schedule_and_run_tasks()

if __name__ == "__main__":
    main()
