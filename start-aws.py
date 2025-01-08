import boto3
import os
import sys
import time
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.prompt import IntPrompt
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.table import Table
from rich.live import Live
from rich.box import ROUNDED
from botocore.exceptions import ClientError

# Initialize rich console with better styling
console = Console()

# Configuration
INSTANCE_ID = "i-0974bc14f968e1549"
KEY_PATH = "windows-server-aws.pem"   # Your key file path
USERNAME = "ubuntu"                   # SSH username

# Initialize boto3 EC2 client
ec2 = boto3.client('ec2')

def create_header():
    """Create a styled header panel"""
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_row("[bold cyan]AWS Instance Controller[/bold cyan]")
    grid.add_row("[dim]Manage your EC2 instances with style[/dim]")
    return Panel(grid, box=ROUNDED, border_style="blue")

def get_instance_info():
    """Get detailed instance information"""
    try:
        response = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
        instance = response['Reservations'][0]['Instances'][0]
        return {
            'state': instance['State']['Name'],
            'ip': instance.get('PublicIpAddress', 'Not assigned'),
            'type': instance['InstanceType'],
            'az': instance['Placement']['AvailabilityZone']
        }
    except Exception:
        return {
            'state': 'unknown',
            'ip': 'unknown',
            'type': 'unknown',
            'az': 'unknown'
        }

def display_status():
    """Display current instance status in a styled table"""
    info = get_instance_info()
    status_color = {
        'running': 'green',
        'stopped': 'red',
        'pending': 'yellow',
        'stopping': 'yellow',
        'unknown': 'dim white'
    }.get(info['state'], 'white')

    table = Table(box=ROUNDED, expand=True, show_header=False)
    table.add_column("Key", style="cyan", width=20)
    table.add_column("Value", style="white")
    
    table.add_row("Instance ID", INSTANCE_ID)
    table.add_row("Current Status", f"[{status_color}]{info['state']}[/{status_color}]")
    table.add_row("Public IP", info['ip'])
    table.add_row("Instance Type", info['type'])
    table.add_row("Zone", info['az'])
    
    return Panel(table, title="[bold]Instance Details[/bold]", border_style="cyan", box=ROUNDED)

def create_menu():
    """Create a styled menu panel"""
    menu_text = Text.from_markup("""
[cyan]1.[/cyan] Start Instance
[cyan]0.[/cyan] Stop Instance
[cyan]-1.[/cyan] Exit Program

Enter your choice: """)
    return Panel(menu_text, title="[bold]Menu Options[/bold]", border_style="cyan", box=ROUNDED)

def custom_progress():
    """Create a custom progress bar with spinner"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(complete_style="green", finished_style="green"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
        transient=True
    )

def wait_for_instance_state(desired_state, progress):
    """Wait for instance to reach desired state"""
    while True:
        info = get_instance_info()
        if info['state'] == desired_state:
            return True
        time.sleep(2)
        progress.update(progress.task_ids[0], advance=2)

def start_instance():
    """Start the EC2 instance with enhanced visual feedback"""
    console.clear()
    console.print(create_header())
    
    with custom_progress() as progress:
        task = progress.add_task("[cyan]Starting instance...", total=100)
        
        try:
            # Check if instance is already running
            if get_instance_info()['state'] == 'running':
                console.print(Panel("[yellow]Instance is already running! Proceeding to SSH connection...[/yellow]", 
                                  box=ROUNDED, border_style="yellow"))
                progress.update(task, completed=100)  # Complete the progress bar
            else:
                # Start the instance
                ec2.start_instances(InstanceIds=[INSTANCE_ID])
                
                # Wait for instance to be running
                wait_for_instance_state('running', progress)
                
                console.print(Panel("[bold green]✓ Instance started successfully![/bold green]", 
                                  box=ROUNDED, border_style="green"))
                
                # Wait for instance to initialize
                console.print("[yellow]Waiting 30 seconds for services to start...[/yellow]")
                time.sleep(30)
            
            # Prepare for SSH connection
            console.print("[dim]Initiating SSH connection...[/dim]")
            try:
                os.chmod(KEY_PATH, 0o600)  # Set proper key permissions
            except Exception as e:
                console.print(f"[yellow]Warning: Could not set key permissions: {str(e)}[/yellow]")
            
            # Get instance IP
            instance_ip = get_instance_info()['ip']
            
            # Brief pause to show the status message
            time.sleep(1)
            
            # Execute SSH command using os.execvp to replace current process
            ssh_args = ['ssh', '-i', KEY_PATH, '-o', 'ConnectTimeout=10', 
                       '-o', 'StrictHostKeyChecking=no', f'{USERNAME}@{instance_ip}']
            
            os.execvp('ssh', ssh_args)
            
        except ClientError as e:
            progress.stop()
            error_message = f"[bold red]Error:[/bold red] {e.response['Error']['Message']}"
            console.print(Panel(error_message, border_style="red", box=ROUNDED))
            sys.exit(1)

def stop_instance():
    """Stop the EC2 instance with enhanced visual feedback"""
    console.clear()
    console.print(create_header())
    
    with custom_progress() as progress:
        task = progress.add_task("[cyan]Stopping instance...", total=100)
        
        try:
            # Check if instance is already stopped
            if get_instance_info()['state'] == 'stopped':
                console.print(Panel("[yellow]Instance is already stopped![/yellow]", 
                                  box=ROUNDED, border_style="yellow"))
                time.sleep(2)
                return

            ec2.stop_instances(InstanceIds=[INSTANCE_ID])
            
            # Wait for instance to be stopped
            wait_for_instance_state('stopped', progress)  # Fixed: Pass progress object instead of task
            
            console.print(Panel("[bold red]✓ Instance stopped successfully![/bold red]", 
                              box=ROUNDED, border_style="red"))
            
        except ClientError as e:
            progress.stop()
            error_message = f"[bold red]Error:[/bold red] {e.response['Error']['Message']}"
            console.print(Panel(error_message, border_style="red", box=ROUNDED))
            sys.exit(1)

def main():
    """Main function with enhanced UI"""
    while True:
        console.clear()
        console.print(create_header())
        console.print(display_status())
        console.print(create_menu())
        
        action = IntPrompt.ask("", default=-1)
        
        if action == 1:
            start_instance()
            break
        elif action == 0:
            stop_instance()
            time.sleep(2)  # Give user time to see the success message
        else:
            console.print(Panel("[yellow]👋 Goodbye![/yellow]", 
                              box=ROUNDED, border_style="yellow"))
            sys.exit(0)

if __name__ == "__main__":
    main()
