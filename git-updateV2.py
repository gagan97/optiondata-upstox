from datetime import datetime
import subprocess
import time
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
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        expand=True
    )
    
    overall_progress = Progress(
        TextColumn("[bold green]Overall Progress:"),
        BarColumn(bar_width=None),
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
        
        # Initialize overall progress task
        self.overall_task_id = self.overall_progress.add_task("", total=100)
        
        # Track both initial and final states of files
        self.initial_files = []
        self.final_files = []

    def store_initial_statuses(self):
        """Store the initial status of files before operations."""
        stdout, _, _ = run_command("git status --porcelain")
        self.initial_files = []
        for line in stdout.split('\n'):
            if line.strip():
                status = line[:2]
                filename = line[3:].strip()
                self.initial_files.append((status, filename))
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

        return Panel(table, title=f"[bold blue]{title}[/bold blue]", box=box.ROUNDED)

    def create_progress_section(self):
        """Create the progress section for the footer."""
        if self.operation_status == "idle":
            return Panel(
                Align.center("Waiting to start operations...", vertical="middle"),
                border_style="blue",
                box=box.ROUNDED
            )
        elif self.operation_status == "running":
            grid = Table.grid(padding=1, expand=True)
            grid.add_row(self.overall_progress)
            grid.add_row(self.task_progress)
            return Panel(grid, border_style="blue", box=box.ROUNDED)
        else:
            # After completion, show both status message and file changes
            grid = Table.grid(padding=1, expand=True)
            status_style = "bold green" if self.operation_status == "success" else "bold red"
            grid.add_row(Text(self.status_message, style=status_style))
            
            if self.pushed_files:
                pushed_files_text = Text()
                pushed_files_text.append("\nPushed files:\n", style="bold blue")
                for filename in self.pushed_files:
                    pushed_files_text.append(f"✓ {filename}\n", style="green")
                grid.add_row(pushed_files_text)
            
            return Panel(grid, border_style="blue", box=box.ROUNDED)

    def create_dashboard(self, stats):
        """Create the main dashboard layout."""
        layout = Layout(name="root")
        
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=10),
        )
        
        layout["header"].update(self.create_header())
        
        # Show different content based on operation status
        if self.operation_status == "success" and self.pushed_files:
            main_layout = Layout()
            main_layout.split_row(
                Layout(self.create_info_section(stats), ratio=1),
                Layout(self.create_files_table(
                    [(self.initial_file_statuses.get(f, '??'), f) for f in self.pushed_files],
                    "✅ Successfully Pushed Files"
                ), ratio=2),
            )
            layout["main"].update(main_layout)
        else:
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
        self.store_initial_statuses()
        
        try:
            # Clear existing tasks
            self.task_progress.tasks.clear()
            
            # Add changes
            add_task = self.task_progress.add_task("Adding changes...", total=100)
            self.overall_progress.update(self.overall_task_id, completed=0)
            
            stdout, stderr, returncode = run_command("git add .")
            if returncode != 0:
                raise Exception(f"Git add failed: {stderr}")
            
            self.task_progress.update(add_task, completed=100)
            self.overall_progress.update(self.overall_task_id, completed=33)
            live.refresh()
            time.sleep(0.5)  # Add slight delay for visual feedback
            
            # Commit changes
            commit_task = self.task_progress.add_task("Committing changes...", total=100)
            commit_msg = f"Automated commit: Updated {len(self.initial_files)} files"
            stdout, stderr, returncode = run_command(f'git commit -m "{commit_msg}"')
            if returncode != 0:
                raise Exception(f"Git commit failed: {stderr}")
            
            self.task_progress.update(commit_task, completed=100)
            self.overall_progress.update(self.overall_task_id, completed=66)
            live.refresh()
            time.sleep(0.5)  # Add slight delay for visual feedback
            
            # Push changes
            push_task = self.task_progress.add_task("Pushing to remote...", total=100)
            stdout, stderr, returncode = run_command("git push origin main")
            if returncode != 0:
                raise Exception(f"Git push failed: {stderr}")
            
            self.task_progress.update(push_task, completed=100)
            self.overall_progress.update(self.overall_task_id, completed=100)
            live.refresh()
            
            # Store pushed files
            self.pushed_files = [filename for _, filename in self.initial_files]
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
    
    with Live(auto_refresh=True, refresh_per_second=10) as live:
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
