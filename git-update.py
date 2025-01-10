import subprocess
from rich.console import Console
from rich.progress import Progress
from rich.panel import Panel
from rich.table import Table
from rich import box

# Initialize console and progress bar
console = Console()
progress = Progress(console=console)

def run_command(command):
    """Run a shell command and return the output and status."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def check_for_changes():
    """Check if there are any changes to commit."""
    stdout, stderr, returncode = run_command("git status --porcelain")
    return bool(stdout)

def git_add_commit_push():
    """Add all changes, commit, and push to the repository."""
    with progress:
        # Check for changes first
        if not check_for_changes():
            console.print("[yellow]No changes detected in the working directory.[/yellow]")
            return False

        # Add changes
        task1 = progress.add_task("[cyan]Adding changes...", total=100)
        stdout, stderr, returncode = run_command("git add .")
        if returncode != 0:
            progress.update(task1, completed=0)
            raise Exception(f"Git add failed: {stderr}")
        progress.update(task1, completed=100)

        # Commit changes
        task2 = progress.add_task("[green]Committing changes...", total=100)
        commit_message = "Automated commit of updated scripts"
        stdout, stderr, returncode = run_command(f'git commit -m "{commit_message}"')
        if returncode != 0:
            progress.update(task2, completed=0)
            raise Exception(f"Git commit failed: {stderr}")
        progress.update(task2, completed=100)

        # Push changes
        task3 = progress.add_task("[blue]Pushing to repository...", total=100)
        stdout, stderr, returncode = run_command("git push origin main")
        if returncode != 0:
            progress.update(task3, completed=0)
            raise Exception(f"Git push failed: {stderr}")
        progress.update(task3, completed=100)
        
        return True

def show_summary():
    """Show a summary of the git status."""
    table = Table(title="Git Status Summary", box=box.ROUNDED)
    table.add_column("Operation", justify="right", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")

    # Get git status
    stdout, stderr, returncode = run_command("git status --short")
    table.add_row("Changes", stdout if stdout else "No changes detected")

    # Get last commit
    stdout, stderr, returncode = run_command("git log -1 --oneline")
    table.add_row("Last Commit", stdout if stdout else "No commits yet")

    # Get current branch
    stdout, stderr, returncode = run_command("git branch --show-current")
    table.add_row("Current Branch", stdout if stdout else "Unknown")

    console.print(Panel(table, title="Git Operations Dashboard", subtitle="Automated Git Management"))

if __name__ == "__main__":
    try:
        if git_add_commit_push():
            console.print("[green]Successfully completed all Git operations![/green]")
        show_summary()
    except Exception as e:
        console.print(f"[bold red]Failed to complete Git operations:[/bold red] {str(e)}")
