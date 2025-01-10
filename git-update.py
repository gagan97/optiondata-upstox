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
    """Run a shell command and return the output."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[bold red]Error during command:[/bold red] {command}")
        console.print(f"[bold red]Error message:[/bold red] {result.stderr.strip()}")
        raise Exception(result.stderr.strip())
    return result.stdout.strip()

def git_add_commit_push():
    """Add all changes, commit, and push to the repository."""
    # Start the progress bar
    with progress:
        task1 = progress.add_task("[cyan]Adding changes...", total=100)
        run_command("git add .")
        progress.update(task1, completed=100)

        task2 = progress.add_task("[green]Committing changes...", total=100)
        commit_message = "Automated commit of updated scripts"
        try:
            run_command(f"git commit -m \"{commit_message}\"")
        except Exception as e:
            progress.update(task2, completed=0)
            raise e
        progress.update(task2, completed=100)

        task3 = progress.add_task("[blue]Pushing to repository...", total=100)
        run_command("git push origin main")
        progress.update(task3, completed=100)

def show_summary():
    """Show a summary of the git status."""
    table = Table(title="Git Status Summary", box=box.ROUNDED)
    table.add_column("Operation", justify="right", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")

    # Get git status
    status = run_command("git status --short")
    table.add_row("Changes", status if status else "No changes detected")

    console.print(Panel(table, title="Git Operations Dashboard", subtitle="Automated Git Management"))

if __name__ == "__main__":
    try:
        git_add_commit_push()
        show_summary()
    except Exception as e:
        console.print(f"[bold red]Failed to complete Git operations:[/bold red] {str(e)}")
