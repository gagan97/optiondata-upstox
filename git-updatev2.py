import subprocess
import time
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

console = Console()

def create_progress():
    """Create a modern progress bar with spinner."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        expand=False
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
    
    # Get current branch
    stdout, _, _ = run_command("git branch --show-current")
    stats['branch'] = stdout or "unknown"
    
    # Get last commit info
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
    
    # Get number of modified files
    stdout, _, _ = run_command("git status --porcelain | wc -l")
    stats['modified_files'] = int(stdout or 0)
    
    return stats

def create_dashboard(stats):
    """Create a modern dashboard layout."""
    # Create main layout
    layout = Layout()
    layout.split_column(
        Layout(name="upper", size=3),
        Layout(name="lower", size=4)
    )
    
    # Create status boxes
    status_boxes = []
    
    # Branch status
    branch_panel = Panel(
        Text(f"🔖 {stats['branch']}", style="bold cyan"),
        title="Branch",
        box=box.ROUNDED,
        padding=(0, 2),
        title_align="left"
    )
    status_boxes.append(branch_panel)
    
    # Modified files status
    files_panel = Panel(
        Text(f"📝 {stats['modified_files']}", style="bold magenta"),
        title="Modified Files",
        box=box.ROUNDED,
        padding=(0, 2),
        title_align="left"
    )
    status_boxes.append(files_panel)
    
    # Last commit info
    if stats['last_commit']:
        commit_text = Text.assemble(
            (f"#{stats['last_commit']['hash']} ", "bold yellow"),
            (f"{stats['last_commit']['message']}\n", "dim white"),
            (f"🕒 {stats['last_commit']['time']}", "italic blue")
        )
    else:
        commit_text = Text("No commits yet", style="dim")
    
    commit_panel = Panel(
        commit_text,
        title="Last Commit",
        box=box.ROUNDED,
        padding=(0, 2),
        title_align="left"
    )
    
    # Combine layouts
    layout["upper"].update(Columns(status_boxes))
    layout["lower"].update(commit_panel)
    
    return layout

def git_add_commit_push():
    """Add all changes, commit, and push to the repository."""
    if not check_for_changes():
        console.print("[yellow]No changes detected in the working directory.[/yellow]")
        return False
    
    progress = create_progress()
    with progress:
        # Add changes
        task1 = progress.add_task("Adding changes", total=100)
        stdout, stderr, returncode = run_command("git add .")
        if returncode != 0:
            raise Exception(f"Git add failed: {stderr}")
        progress.update(task1, completed=100)
        
        # Commit changes
        task2 = progress.add_task("Committing changes", total=100)
        commit_message = "Automated commit of updated scripts"
        stdout, stderr, returncode = run_command(f'git commit -m "{commit_message}"')
        if returncode != 0:
            raise Exception(f"Git commit failed: {stderr}")
        progress.update(task2, completed=100)
        
        # Push changes
        task3 = progress.add_task("Pushing to repository", total=100)
        stdout, stderr, returncode = run_command("git push origin main")
        if returncode != 0:
            raise Exception(f"Git push failed: {stderr}")
        progress.update(task3, completed=100)
    
    return True

if __name__ == "__main__":
    try:
        console.clear()
        with Live(console=console, screen=True, refresh_per_second=4) as live:
            stats = get_repo_stats()
            dashboard = create_dashboard(stats)
            live.update(Panel(
                dashboard,
                title="[bold blue]Git Operations Dashboard[/bold blue]",
                subtitle=f"[dim]Last updated: {datetime.now().strftime('%H:%M:%S')}[/dim]",
                box=box.ROUNDED
            ))
            
            if git_add_commit_push():
                console.print("\n[green]✓ Successfully completed all Git operations![/green]")
            
            # Update dashboard with new stats
            stats = get_repo_stats()
            dashboard = create_dashboard(stats)
            live.update(Panel(
                dashboard,
                title="[bold blue]Git Operations Dashboard[/bold blue]",
                subtitle=f"[dim]Last updated: {datetime.now().strftime('%H:%M:%S')}[/dim]",
                box=box.ROUNDED
            ))
            
    except Exception as e:
        console.print(f"\n[bold red]✗ Failed to complete Git operations:[/bold red] {str(e)}")
