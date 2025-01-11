from datetime import datetime
import subprocess
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.panel import Panel
from rich.layout import Layout
from rich.table import Table
from rich import box
from rich.live import Live
from rich.text import Text
from rich.align import Align

console = Console()

def create_progress():
    """Create progress bars for individual tasks and overall progress."""
    task_progress = Progress(
        "{task.description}",
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        expand=True
    )
    
    overall_progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        expand=True
    )
    
    return task_progress, overall_progress

def run_command(command):
    """Run a shell command and return the output and status."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def check_for_changes():
    """Check if there are any changes to commit."""
    stdout, _, _ = run_command("git status --porcelain")
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
    
    stdout, _, _ = run_command("git status --porcelain")
    stats['changed_files'] = []
    for line in stdout.split('\n'):
        if line.strip():
            status = line[:2]
            filename = line[3:].strip()
            stats['changed_files'].append((status, filename))
    
    stats['modified_files'] = len(stats['changed_files'])
    return stats

class DashboardManager:
    def __init__(self):
        self.task_progress, self.overall_progress = create_progress()
        self.status_message = ""
        self.operation_status = "idle"
        self.pushed_files = []
        self.initial_file_statuses = {}

    def store_initial_statuses(self):
        """Store the initial status of files before operations."""
        stdout, _, _ = run_command("git status --porcelain")
        for line in stdout.split('\n'):
            if line.strip():
                status = line[:2]
                filename = line[3:].strip()
                self.initial_file_statuses[filename] = status

    def create_header(self):
        """Create the dashboard header."""
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            "[b]Git Dashboard[/b]",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        return Panel(grid, style="white on blue")

    def create_info_section(self, stats):
        """Create repository info section."""
        info_text = Text()
        info_text.append("Branch: ", style="dim")
        info_text.append(f"🔖 {stats['branch']}", style="bold cyan")
        info_text.append(" | ", style="dim")
        info_text.append("Modified Files: ", style="dim")
        info_text.append(f"📝 {stats['modified_files']}", style="bold magenta")
        
        if stats['last_commit']:
            info_text.append("\nLast Commit: ", style="dim")
            info_text.append(f"[{stats['last_commit']['hash']}] ", style="yellow")
            info_text.append(stats['last_commit']['message'], style="green")
            info_text.append(f" ({stats['last_commit']['time']})", style="dim")
            
        return Panel(info_text, box=box.ROUNDED)

    def create_files_table(self, files_data, title):
        """Create a table for displaying files."""
        table = Table(show_header=True, box=box.ROUNDED, expand=True)
        table.add_column("Status", style="cyan", width=12)
        table.add_column("File", style="white")

        status_map = {
            'M ': "📝 Modified",
            'A ': "➕ Added",
            'D ': "❌ Deleted",
            'R ': "🔄 Renamed",
            'C ': "📋 Copied",
            '??': "❓ Untracked"
        }

        for status, filename in files_data:
            status_text = status_map.get(status, status)
            table.add_row(status_text, filename)

        return Panel(table, title=title, box=box.ROUNDED)

    def create_progress_section(self):
        """Create the progress section for the footer."""
        if self.operation_status == "idle":
            return Panel(
                Align.center("Ready for operations", vertical="middle"),
                box=box.ROUNDED
            )
        elif self.operation_status == "running":
            progress_table = Table.grid(expand=True)
            progress_table.add_row(
                Panel(
                    self.overall_progress,
                    title="Overall Progress",
                    border_style="green",
                    padding=(1, 1),
                ),
            )
            progress_table.add_row(
                Panel(
                    self.task_progress,
                    title="Current Tasks",
                    border_style="blue",
                    padding=(1, 1),
                ),
            )
            return progress_table
        else:
            status_style = "bold green" if self.operation_status == "success" else "bold red"
            return Panel(
                Align.center(Text(self.status_message, style=status_style), vertical="middle"),
                box=box.ROUNDED
            )

    def create_dashboard(self, stats):
        """Create the main dashboard layout."""
        layout = Layout(name="root")
        
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=8),
        )
        
        layout["header"].update(self.create_header())
        
        main_layout = Layout()
        main_layout.split_row(
            Layout(self.create_info_section(stats), ratio=1),
            Layout(self.create_files_table(
                stats['changed_files'], 
                "📋 Changed Files"
            ), ratio=2),
        )
        layout["main"].update(main_layout)
        layout["footer"].update(self.create_progress_section())
        
        return layout

    def git_operations(self, live):
        """Perform git operations with live updates."""
        if not check_for_changes():
            self.status_message = "No changes to commit"
            self.operation_status = "success"
            return False

        self.operation_status = "running"
        overall_task = self.overall_progress.add_task("Git Operations", total=300)
        
        try:
            self.store_initial_statuses()
            self.pushed_files = list(self.initial_file_statuses.keys())

            # Add changes
            task1 = self.task_progress.add_task("Adding changes...", total=100)
            stdout, stderr, returncode = run_command("git add .")
            if returncode != 0:
                raise Exception(f"Git add failed: {stderr}")
            self.task_progress.update(task1, completed=100)
            self.overall_progress.update(overall_task, advance=100)
            
            # Commit changes
            task2 = self.task_progress.add_task("Committing changes...", total=100)
            commit_msg = f"Automated commit: Updated {len(self.pushed_files)} files"
            stdout, stderr, returncode = run_command(f'git commit -m "{commit_msg}"')
            if returncode != 0:
                raise Exception(f"Git commit failed: {stderr}")
            self.task_progress.update(task2, completed=100)
            self.overall_progress.update(overall_task, advance=100)
            
            # Push changes
            task3 = self.task_progress.add_task("Pushing to remote...", total=100)
            stdout, stderr, returncode = run_command("git push origin main")
            if returncode != 0:
                raise Exception(f"Git push failed: {stderr}")
            self.task_progress.update(task3, completed=100)
            self.overall_progress.update(overall_task, advance=100)
            
            num_files = len(self.pushed_files)
            self.status_message = f"✅ Successfully pushed {num_files} file{'s' if num_files != 1 else ''}"
            self.operation_status = "success"
            return True
            
        except Exception as e:
            self.status_message = f"❌ Error: {str(e)}"
            self.operation_status = "error"
            return False

def main():
    dashboard_manager = DashboardManager()
    console.clear()
    
    with Live(auto_refresh=True, refresh_per_second=4) as live:
        # Initial dashboard
        stats = get_repo_stats()
        live.update(dashboard_manager.create_dashboard(stats))
        
        # Perform git operations
        dashboard_manager.git_operations(live)
        
        # Final update with results
        stats = get_repo_stats()
        live.update(dashboard_manager.create_dashboard(stats))
        
        # Keep the dashboard visible
        console.input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
