import subprocess
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.columns import Columns
from rich import box
from rich.live import Live
from rich.text import Text
from rich.console import Group

console = Console()

def create_progress():
    """Create a modern progress bar with spinner."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),  # None allows auto-scaling
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        expand=True
    )

def run_command(command):
    """Run a shell command and return the output and status."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def check_for_changes():
    """Check if there are any changes to commit."""
    stdout, stderr, returncode = run_command("git status --porcelain")
    return bool(stdout)

def get_repo_stats():
    """Get repository statistics."""
    stats = {}
    
    stdout, _, _ = run_command("git branch --show-current")
    stats['branch'] = stdout or "unknown"
    
    stdout, _, _ = run_command("git log -1 --format='%h|%s|%ar'")
    if stdout and '|' in stdout:
        hash_id, message, time_ago = stdout.split('|')
        stats['last_commit'] = {
            'hash': hash_id,
            'message': message[:40] + ('...' if len(message) > 40 else ''),
            'time': time_ago
        }
    else:
        stats['last_commit'] = None
    
    stdout, _, _ = run_command("git status --porcelain | wc -l")
    stats['modified_files'] = int(stdout or 0)
    
    return stats

class DashboardManager:
    def __init__(self):
        self.progress = create_progress()
        self.status_message = ""
        self.operation_status = "idle"  # idle, running, success, error
        
    def create_status_section(self, stats):
        """Create the status section of the dashboard."""
        return Columns([
            Panel(
                Text(f"🔖 {stats['branch']}", style="bold cyan"),
                title="Branch",
                box=box.ROUNDED,
                padding=(0, 2),
                title_align="left"
            ),
            Panel(
                Text(f"📝 {stats['modified_files']}", style="bold magenta"),
                title="Modified Files",
                box=box.ROUNDED,
                padding=(0, 2),
                title_align="left"
            )
        ], expand=True)

    def create_commit_section(self, stats):
        """Create the commit info section."""
        if stats['last_commit']:
            commit_text = Text.assemble(
                (f"#{stats['last_commit']['hash']} ", "bold yellow"),
                (f"{stats['last_commit']['message']}\n", "dim white"),
                (f"🕒 {stats['last_commit']['time']}", "italic blue")
            )
        else:
            commit_text = Text("No commits yet", style="dim")
        
        return Panel(
            commit_text,
            title="Last Commit",
            box=box.ROUNDED,
            padding=(0, 2),
            title_align="left"
        )

    def create_progress_section(self):
        """Create the progress section."""
        if self.operation_status == "idle":
            return Panel(
                Text("Waiting for operations...", style="dim"),
                title="Status",
                box=box.ROUNDED,
                padding=(0, 2)
            )
        elif self.operation_status == "running":
            return Panel(
                self.progress,
                title="Progress",
                box=box.ROUNDED,
                padding=(0, 2)
            )
        else:
            return Panel(
                Text(self.status_message, 
                     style="bold green" if self.operation_status == "success" else "bold red"),
                title="Status",
                box=box.ROUNDED,
                padding=(0, 2)
            )

    def create_dashboard(self, stats):
        """Create the full dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="status", size=3),
            Layout(name="commit", size=4),
            Layout(name="progress", size=3)
        )
        
        layout["status"].update(self.create_status_section(stats))
        layout["commit"].update(self.create_commit_section(stats))
        layout["progress"].update(self.create_progress_section())
        
        return Panel(
            layout,
            title="[bold blue]Git Operations Dashboard[/bold blue]",
            subtitle=f"[dim]Last updated: {datetime.now().strftime('%H:%M:%S')}[/dim]",
            box=box.ROUNDED
        )

    def git_operations(self, live):
        """Perform git operations with live updates."""
        if not check_for_changes():
            self.status_message = "No changes detected in the working directory."
            self.operation_status = "success"
            return False

        self.operation_status = "running"
        try:
            # Add changes
            task1 = self.progress.add_task("Adding changes", total=100)
            stdout, stderr, returncode = run_command("git add .")
            if returncode != 0:
                raise Exception(f"Git add failed: {stderr}")
            self.progress.update(task1, completed=100)
            
            # Commit changes
            task2 = self.progress.add_task("Committing changes", total=100)
            stdout, stderr, returncode = run_command(
                'git commit -m "Automated commit of updated scripts"'
            )
            if returncode != 0:
                raise Exception(f"Git commit failed: {stderr}")
            self.progress.update(task2, completed=100)
            
            # Push changes
            task3 = self.progress.add_task("Pushing to repository", total=100)
            stdout, stderr, returncode = run_command("git push origin main")
            if returncode != 0:
                raise Exception(f"Git push failed: {stderr}")
            self.progress.update(task3, completed=100)
            
            self.status_message = "✓ Successfully completed all Git operations!"
            self.operation_status = "success"
            return True
            
        except Exception as e:
            self.status_message = f"✗ Failed: {str(e)}"
            self.operation_status = "error"
            return False

if __name__ == "__main__":
    dashboard_manager = DashboardManager()
    console.clear()
    
    with Live(auto_refresh=False) as live:
        # Initial dashboard
        stats = get_repo_stats()
        live.update(dashboard_manager.create_dashboard(stats))
        live.refresh()
        
        # Perform git operations
        dashboard_manager.git_operations(live)
        
        # Final update with results
        stats = get_repo_stats()
        live.update(dashboard_manager.create_dashboard(stats))
        live.refresh()
        
        # Keep the dashboard visible
        console.input("\nPress Enter to exit...")
