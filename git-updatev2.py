import subprocess
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.panel import Panel
from rich.layout import Layout
from rich.columns import Columns
from rich import box
from rich.live import Live
from rich.text import Text

console = Console()

def create_progress():
    """Create a compact progress bar with spinner."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
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
            'message': message[:30] + ('...' if len(message) > 30 else ''),
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
        self.operation_status = "idle"

    def create_info_section(self, stats):
        """Create a compact info section combining branch and modified files."""
        info_text = Text()
        info_text.append("Branch: ", style="dim")
        info_text.append(f"🔖 {stats['branch']}", style="bold cyan")
        info_text.append(" | ", style="dim")
        info_text.append("Files: ", style="dim")
        info_text.append(f"📝 {stats['modified_files']}", style="bold magenta")
        return Panel(info_text, box=box.ROUNDED)

    def create_commit_section(self, stats):
        """Create a compact commit info section."""
        if stats['last_commit']:
            commit_text = Text()
            commit_text.append(f"#{stats['last_commit']['hash']} ", style="bold yellow")
            commit_text.append(f"{stats['last_commit']['message']} ", style="dim white")
            commit_text.append(f"({stats['last_commit']['time']})", style="italic blue")
        else:
            commit_text = Text("No commits yet", style="dim")
        return Panel(commit_text, box=box.ROUNDED)

    def create_progress_section(self):
        """Create a compact progress section."""
        content = Text("Ready for operations", style="dim")
        if self.operation_status == "running":
            content = self.progress
        elif self.operation_status in ["success", "error"]:
            content = Text(
                self.status_message,
                style="bold green" if self.operation_status == "success" else "bold red"
            )
        return Panel(content, box=box.ROUNDED)

    def create_dashboard(self, stats):
        """Create a compact dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="info", size=3),
            Layout(name="commit", size=3),
            Layout(name="progress", size=3)
        )
        
        layout["info"].update(self.create_info_section(stats))
        layout["commit"].update(self.create_commit_section(stats))
        layout["progress"].update(self.create_progress_section())
        
        return Panel(
            layout,
            title="[bold blue]Git Operations[/bold blue]",
            subtitle=f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
            box=box.ROUNDED
        )

    def git_operations(self, live):
        """Perform git operations with live updates."""
        if not check_for_changes():
            self.status_message = "No changes to commit"
            self.operation_status = "success"
            return False

        self.operation_status = "running"
        try:
            task1 = self.progress.add_task("Adding changes", total=100)
            stdout, stderr, returncode = run_command("git add .")
            if returncode != 0:
                raise Exception(f"Git add failed: {stderr}")
            self.progress.update(task1, completed=100)
            
            task2 = self.progress.add_task("Committing changes", total=100)
            stdout, stderr, returncode = run_command(
                'git commit -m "Automated commit of updated scripts"'
            )
            if returncode != 0:
                raise Exception(f"Git commit failed: {stderr}")
            self.progress.update(task2, completed=100)
            
            task3 = self.progress.add_task("Pushing to remote", total=100)
            stdout, stderr, returncode = run_command("git push origin main")
            if returncode != 0:
                raise Exception(f"Git push failed: {stderr}")
            self.progress.update(task3, completed=100)
            
            self.status_message = "✓ Operations completed successfully"
            self.operation_status = "success"
            return True
            
        except Exception as e:
            self.status_message = f"✗ Error: {str(e)}"
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
