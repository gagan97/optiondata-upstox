from datetime import datetime, timezone, timedelta
import boto3
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.table import Table
from rich.live import Live
from rich.tree import Tree

console = Console()

# Initialize AWS clients
ec2 = boto3.client('ec2')
cloudwatch = boto3.client('cloudwatch')
pricing = boto3.client('pricing', region_name='us-east-1')  # Pricing API is only available in us-east-1
iam = boto3.client('iam')

class HeaderWidget:
    """Display header with instance info and current time."""
    def __init__(self, instance_id):
        self.instance_id = instance_id

    def __rich__(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            f"[b]Instance:[/b] {self.instance_id}",
            "[b]AWS Instance Monitor[/b]",
            datetime.now().ctime().replace(":", "[blink]:[/]"),
        )
        return Panel(grid, style="white on blue")

def create_header():
    """Create a styled header panel"""
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_row("[bold cyan]AWS Instance Controller[/bold cyan]")
    grid.add_row("[dim]Manage your EC2 instances with style[/dim]")
    return Panel(grid, box=ROUNDED, border_style="blue")

def make_layout() -> Layout:
    """Define the layout structure."""
    layout = Layout(name="root")

    # Main splits
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=7),
    )

    # Split main area into side and body
    layout["main"].split_row(
        Layout(name="side", ratio=1),
        Layout(name="body", ratio=2),
    )

    # Split side area into two boxes
    layout["side"].split(
        Layout(name="metrics", ratio=1),
        Layout(name="volumes", ratio=1),
    )

    # Split body area into two sections
    layout["body"].split(
        Layout(name="network", ratio=1),
        Layout(name="security", ratio=1),
    )

    return layout

def get_instance_price(instance_type, region):
    """Get the hourly price for the instance type"""
    try:
        response = pricing.get_products(
            ServiceCode='AmazonEC2',
            Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                {'Type': 'TERM_MATCH', 'Field': 'regionCode', 'Value': region},
                {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
                {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'}
            ]
        )
        
        if response['PriceList']:
            price_data = json.loads(response['PriceList'][0])
            on_demand = price_data['terms']['OnDemand']
            price_dimensions = list(list(on_demand.values())[0]['priceDimensions'].values())[0]
            return float(price_dimensions['pricePerUnit']['USD'])
        return None
    except Exception as e:
        console.print(f"[red]Error getting price info: {str(e)}[/red]")
        return None

def get_instance_metrics(instance_id):
    """Get CloudWatch metrics for the instance"""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=1)
    
    metrics = {}
    try:
        # CPU Utilization
        cpu_response = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average']
        )
        metrics['cpu'] = cpu_response['Datapoints'][-1]['Average'] if cpu_response['Datapoints'] else 0

        # Network In/Out
        network_in = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='NetworkIn',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average']
        )
        network_out = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='NetworkOut',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average']
        )
        network_out = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='NetworkOut',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average']
        )
        
        metrics['network_in'] = network_in['Datapoints'][-1]['Average'] if network_in['Datapoints'] else 0
        metrics['network_out'] = network_out['Datapoints'][-1]['Average'] if network_out['Datapoints'] else 0
        
        # Disk I/O
        disk_read = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='DiskReadBytes',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average']
        )
        disk_write = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='DiskWriteBytes',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average']
        )
        
        metrics['disk_read'] = disk_read['Datapoints'][-1]['Average'] if disk_read['Datapoints'] else 0
        metrics['disk_write'] = disk_write['Datapoints'][-1]['Average'] if disk_write['Datapoints'] else 0

        return metrics
    except Exception as e:
        console.print(f"[red]Error getting metrics: {str(e)}[/red]")
        return {
            'cpu': 0,
            'network_in': 0,
            'network_out': 0,
            'disk_read': 0,
            'disk_write': 0
        }

def get_security_groups(instance_id):
    """Get detailed security group information"""
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        security_groups = []
        
        for sg in instance['SecurityGroups']:
            sg_details = ec2.describe_security_groups(GroupIds=[sg['GroupId']])['SecurityGroups'][0]
            security_groups.append({
                'id': sg['GroupId'],
                'name': sg['GroupName'],
                'description': sg_details['Description'],
                'inbound_rules': sg_details['IpPermissions'],
                'outbound_rules': sg_details['IpPermissionsEgress']
            })
        
        return security_groups
    except Exception as e:
        console.print(f"[red]Error getting security group info: {str(e)}[/red]")
        return []

def get_network_interfaces(instance_id):
    """Get detailed network interface information"""
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        interfaces = []
        
        for eni in instance['NetworkInterfaces']:
            interfaces.append({
                'id': eni['NetworkInterfaceId'],
                'subnet_id': eni['SubnetId'],
                'vpc_id': eni['VpcId'],
                'private_ip': eni['PrivateIpAddress'],
                'public_ip': eni.get('Association', {}).get('PublicIp', 'N/A'),
                'mac_address': eni['MacAddress'],
                'status': eni['Status']
            })
        
        return interfaces
    except Exception as e:
        console.print(f"[red]Error getting network interface info: {str(e)}[/red]")
        return []

def view_volume_details():
    """View detailed volume information"""
    console.clear()
    console.print(create_header())
    
    volumes = get_volume_info(INSTANCE_ID)
    
    for volume in volumes:
        table = Table(title=f"Volume: {volume['volume_id']}", box=ROUNDED)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        
        table.add_row("Device", volume['device'])
        table.add_row("Size", f"{volume['size']} GB")
        table.add_row("Volume Type", volume['type'])
        table.add_row("IOPS", str(volume['iops']))
        table.add_row("Encrypted", "Yes" if volume['encrypted'] else "No")
        table.add_row("Created", format_datetime(volume['created']))
        table.add_row("State", volume['state'])
        
        console.print(Panel(table, border_style="cyan"))
        console.print("")
    
    console.print("\nPress Enter to continue...")
    input()
def view_cost_estimates():
    """View detailed cost estimates for cloud instance usage"""
    console.clear()
    console.print(create_header())
    
    info = get_instance_info()
    hourly_price = get_instance_price(info['type'], 'us-east-1')  # Default region
    
    if hourly_price and info['total_hours']:
        table = Table(title=f"Cost Estimates for {info['type']}", box=ROUNDED)
        table.add_column("Period", style="cyan")
        table.add_column("Cost", style="white")
        table.add_column("Details", style="green")
        
        # Calculate different time period costs
        hourly = hourly_price
        daily = hourly * 24
        weekly = daily * 7
        monthly = daily * 30
        yearly = monthly * 12
        total = hourly_price * info['total_hours']
        
        # Add rows to the table
        table.add_row("Hourly Rate", f"${hourly:.3f}", "Base instance rate")
        table.add_row("Daily Estimate", f"${daily:.2f}", "24 hours of usage")
        table.add_row("Weekly Estimate", f"${weekly:.2f}", "7 days of usage")
        table.add_row("Monthly Estimate", f"${monthly:.2f}", "30 days of usage")
        table.add_row("Yearly Estimate", f"${yearly:.2f}", "365 days of usage")
        table.add_row("Total Projected", f"${total:.2f}", 
                     f"Based on {info['total_hours']} hours")
        
        console.print(table)
        
        # Print additional information
        console.print("\n[yellow]Note:[/yellow] Estimates are based on current pricing "
                     "and do not include additional services or data transfer costs.")
        console.print(f"Instance Type: [blue]{info['type']}[/blue]")
        console.print(f"Start Date: [blue]{info['start_date'].strftime('%Y-%m-%d %H:%M:%S')}[/blue]")
    else:
        console.print("[red]Error:[/red] Unable to retrieve pricing information.")
def get_volume_info(instance_id):
    """Get detailed information about attached EBS volumes"""
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        volumes = []
        
        for volume in instance['BlockDeviceMappings']:
            volume_id = volume['Ebs']['VolumeId']
            volume_info = ec2.describe_volumes(VolumeIds=[volume_id])['Volumes'][0]
            
            volumes.append({
                'device': volume['DeviceName'],
                'volume_id': volume_id,
                'size': volume_info['Size'],
                'type': volume_info['VolumeType'],
                'state': volume_info['State'],
                'encrypted': volume_info['Encrypted'],
                'iops': volume_info.get('Iops', 'N/A'),
                'created': volume_info['CreateTime']
            })
        
        return volumes
    except Exception as e:
        console.print(f"[red]Error getting volume info: {str(e)}[/red]")
        return []

def get_instance_uptime(instance_id):
    """Calculate total instance uptime from CloudWatch metrics"""
    try:
        # Get instance launch time
        response = ec2.describe_instances(InstanceIds=[instance_id])
        launch_time = response['Reservations'][0]['Instances'][0]['LaunchTime']
        
        # Calculate total running hours since launch
        total_hours = (datetime.now(timezone.utc) - launch_time).total_seconds() / 3600
        
        return {
            'launch_time': launch_time,
            'total_hours': round(total_hours, 2)
        }
    except Exception as e:
        console.print(f"[red]Error calculating uptime: {str(e)}[/red]")
        return {'launch_time': None, 'total_hours': 0}
def get_instance_info():
    """Get detailed instance information"""
    try:
        response = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
        instance = response['Reservations'][0]['Instances'][0]
        
        # Get tags
        tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
        
        # Get uptime information
        uptime_info = get_instance_uptime(INSTANCE_ID)
        
        return {
            'state': instance['State']['Name'],
            'ip': instance.get('PublicIpAddress', 'Not assigned'),
            'type': instance['InstanceType'],
            'az': instance['Placement']['AvailabilityZone'],
            'vpc_id': instance.get('VpcId', 'N/A'),
            'subnet_id': instance.get('SubnetId', 'N/A'),
            'launch_time': uptime_info['launch_time'],
            'total_hours': uptime_info['total_hours'],
            'platform': instance.get('PlatformDetails', 'N/A'),
            'architecture': instance.get('Architecture', 'N/A'),
            'tags': tags
        }
    except Exception as e:
        console.print(f"[red]Error getting instance info: {str(e)}[/red]")
        return {
            'state': 'unknown',
            'ip': 'unknown',
            'type': 'unknown',
            'az': 'unknown',
            'vpc_id': 'unknown',
            'subnet_id': 'unknown',
            'launch_time': None,
            'total_hours': 0,
            'platform': 'unknown',
            'architecture': 'unknown',
            'tags': {}
        }

def format_datetime(dt):
    """Format datetime object to readable string"""
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def display_status():
    """Display current instance status in a styled table"""
    info = get_instance_info()
    volumes = get_volume_info(INSTANCE_ID)
    
    status_color = {
        'running': 'green',
        'stopped': 'red',
        'pending': 'yellow',
        'stopping': 'yellow',
        'unknown': 'dim white'
    }.get(info['state'], 'white')

    # Main instance information table
    instance_table = Table(box=ROUNDED, expand=True, show_header=False)
    instance_table.add_column("Key", style="cyan", width=20)
    instance_table.add_column("Value", style="white")
    
    instance_table.add_row("Instance ID", INSTANCE_ID)
    instance_table.add_row("Current Status", f"[{status_color}]{info['state']}[/{status_color}]")
    instance_table.add_row("Public IP", info['ip'])
    instance_table.add_row("Instance Type", info['type'])
    instance_table.add_row("Zone", info['az'])
    instance_table.add_row("VPC ID", info['vpc_id'])
    instance_table.add_row("Subnet ID", info['subnet_id'])
    instance_table.add_row("Platform", info['platform'])
    instance_table.add_row("Architecture", info['architecture'])
    instance_table.add_row("Launch Time", format_datetime(info['launch_time']))
    instance_table.add_row("Total Running Hours", f"{info['total_hours']} hours")
    
    # Tags table
    if info['tags']:
        instance_table.add_row("", "")  # Empty row for spacing
        instance_table.add_row("[bold]Tags[/bold]", "")
        for key, value in info['tags'].items():
            instance_table.add_row(f"  {key}", value)

    # Volume information table
    volume_table = Table(box=ROUNDED, show_header=True)
    volume_table.add_column("Device", style="cyan")
    volume_table.add_column("Volume ID", style="cyan")
    volume_table.add_column("Size (GB)", justify="right")
    volume_table.add_column("Type")
    volume_table.add_column("State")
    volume_table.add_column("IOPS")
    volume_table.add_column("Encrypted")
    volume_table.add_column("Created")

    for volume in volumes:
        volume_table.add_row(
            volume['device'],
            volume['volume_id'],
            str(volume['size']),
            volume['type'],
            volume['state'],
            str(volume['iops']),
            "Yes" if volume['encrypted'] else "No",
            format_datetime(volume['created'])
        )

    # Combine tables in panels
    layout = Layout()
    layout.split(
        Panel(instance_table, title="[bold]Instance Details[/bold]", border_style="cyan", box=ROUNDED),
        Panel(volume_table, title="[bold]Volume Information[/bold]", border_style="cyan", box=ROUNDED)
    )
    
    return layout

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
            if get_instance_info()['state'] == 'running':
                console.print(Panel("[yellow]Instance is already running! Proceeding to SSH connection...[/yellow]", 
                                  box=ROUNDED, border_style="yellow"))
                progress.update(task, completed=100)
            else:
                ec2.start_instances(InstanceIds=[INSTANCE_ID])
                wait_for_instance_state('running', progress)
                
                console.print(Panel("[bold green]✓ Instance started successfully![/bold green]", 
                                  box=ROUNDED, border_style="green"))
                
                console.print("[yellow]Waiting 30 seconds for services to start...[/yellow]")
                time.sleep(30)
            
            console.print("[dim]Initiating SSH connection...[/dim]")
            try:
                os.chmod(KEY_PATH, 0o600)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not set key permissions: {str(e)}[/yellow]")
            
            instance_ip = get_instance_info()['ip']
            time.sleep(1)
            
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
            if get_instance_info()['state'] == 'stopped':
                console.print(Panel("[yellow]Instance is already stopped![/yellow]", 
                                  box=ROUNDED, border_style="yellow"))
                time.sleep(2)
                return

            ec2.stop_instances(InstanceIds=[INSTANCE_ID])
            wait_for_instance_state('stopped', progress)
            
            console.print(Panel("[bold red]✓ Instance stopped successfully![/bold red]", 
                              box=ROUNDED, border_style="red"))
            
        except ClientError as e:
            progress.stop()
            error_message = f"[bold red]Error:[/bold red] {e.response['Error']['Message']}"
            console.print(Panel(error_message, border_style="red", box=ROUNDED))
            sys.exit(1)

def get_instance_status(instance_id):
    """Get detailed instance status checks"""
    try:
        response = ec2.describe_instance_status(InstanceIds=[instance_id])
        if response['InstanceStatuses']:
            status = response['InstanceStatuses'][0]
            return {
                'system_status': status['SystemStatus']['Status'],
                'instance_status': status['InstanceStatus']['Status'],
                'system_details': status['SystemStatus'].get('Details', []),
                'instance_details': status['InstanceStatus'].get('Details', [])
            }
        return None
    except Exception as e:
        console.print(f"[red]Error getting instance status: {str(e)}[/red]")
        return None

def get_instance_role():
    """Get IAM role information for the instance"""
    try:
        response = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
        instance = response['Reservations'][0]['Instances'][0]
        if 'IamInstanceProfile' in instance:
            profile_arn = instance['IamInstanceProfile']['Arn']
            profile_name = profile_arn.split('/')[-1]
            
            # Get role details
            response = iam.get_instance_profile(InstanceProfileName=profile_name)
            if response['InstanceProfile']['Roles']:
                role = response['InstanceProfile']['Roles'][0]
                
                # Get role policies
                attached_policies = iam.list_attached_role_policies(RoleName=role['RoleName'])
                inline_policies = iam.list_role_policies(RoleName=role['RoleName'])
                
                return {
                    'role_name': role['RoleName'],
                    'role_id': role['RoleId'],
                    'arn': role['Arn'],
                    'attached_policies': attached_policies['AttachedPolicies'],
                    'inline_policies': inline_policies['PolicyNames']
                }
        return None
    except Exception as e:
        console.print(f"[red]Error getting IAM role info: {str(e)}[/red]")
        return None

def format_bytes(bytes_value):
    """Format bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.2f} PB"

def create_metrics_panel(metrics):
    """Create a panel showing instance metrics."""
    metrics_table = Table(show_header=False, box=box.ROUNDED)
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Value", style="white")
    
    metrics_table.add_row("CPU Utilization", f"{metrics['cpu']:.1f}%")
    metrics_table.add_row("Network In", format_bytes(metrics['network_in']))
    metrics_table.add_row("Network Out", format_bytes(metrics['network_out']))
    metrics_table.add_row("Disk Read", format_bytes(metrics['disk_read']))
    metrics_table.add_row("Disk Write", format_bytes(metrics['disk_write']))
    
    return Panel(metrics_table, title="[b]Instance Metrics", border_style="green")

def create_volumes_panel(volumes):
    """Create a panel showing volume information."""
    volume_table = Table(box=box.ROUNDED, show_header=True)
    volume_table.add_column("Device")
    volume_table.add_column("Size")
    volume_table.add_column("Type")
    volume_table.add_column("IOPS")
    
    for volume in volumes:
        volume_table.add_row(
            volume['device'],
            f"{volume['size']} GB",
            volume['type'],
            str(volume['iops'])
        )
    
    return Panel(volume_table, title="[b]EBS Volumes", border_style="blue")

def create_network_panel(network_interfaces):
    """Create a panel showing network information."""
    net_table = Table(box=box.ROUNDED, show_header=True)
    net_table.add_column("Interface ID")
    net_table.add_column("Private IP")
    net_table.add_column("Public IP")
    net_table.add_column("Status")
    
    for interface in network_interfaces:
        net_table.add_row(
            interface['id'],
            interface['private_ip'],
            interface['public_ip'],
            interface['status']
        )
    
    return Panel(net_table, title="[b]Network Interfaces", border_style="magenta")

def create_security_panel(security_groups):
    """Create a panel showing security group information."""
    sg_tree = Tree("🔒 Security Groups")
    for sg in security_groups:
        sg_node = sg_tree.add(f"[cyan]{sg['name']}[/cyan] ({sg['id']})")
        inbound = sg_node.add("Inbound Rules")
        outbound = sg_node.add("Outbound Rules")
        
        for rule in sg['inbound_rules']:
            ports = f"{rule.get('FromPort', 'All')} - {rule.get('ToPort', 'All')}"
            protocol = rule.get('IpProtocol', 'All')
            for ip_range in rule.get('IpRanges', []):
                inbound.add(f"{protocol.upper()} {ports} from {ip_range['CidrIp']}")
    
    return Panel(sg_tree, title="[b]Security Groups", border_style="red")

def monitor_instance(instance_id: str):
    """Main function to monitor the instance with live updates."""
    layout = make_layout()
    layout["header"].update(HeaderWidget(instance_id))

    with Live(layout, refresh_per_second=1, screen=True):
        while True:
            # Get all instance information
            metrics = get_instance_metrics(instance_id)
            volumes = get_volume_info(instance_id)
            network_interfaces = get_network_interfaces(instance_id)
            security_groups = get_security_groups(instance_id)

            # Update all panels
            layout["metrics"].update(create_metrics_panel(metrics))
            layout["volumes"].update(create_volumes_panel(volumes))
            layout["network"].update(create_network_panel(network_interfaces))
            layout["security"].update(create_security_panel(security_groups))

if __name__ == "__main__":
    # Configuration
    INSTANCE_ID = "i-0974bc14f968e1549"
    KEY_PATH = "windows-server-aws.pem"   # Your key file path
    USERNAME = "ubuntu"                   # SSH username
    REGION = "us-east-1"  # Add your AWS region
    try:
        monitor_instance(INSTANCE_ID)
    except KeyboardInterrupt:
        console.print("[yellow]Monitoring stopped by user[/yellow]")
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
            time.sleep(2)
        else:
            console.print(Panel("[yellow]👋 Goodbye![/yellow]", 
                              box=ROUNDED, border_style="yellow"))
            sys.exit(0)
