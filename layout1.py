import boto3
import os
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich import box
from rich.align import Align
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.table import Table
from rich.live import Live
from rich.tree import Tree
from botocore.exceptions import ClientError

# Initialize rich console
console = Console()

# Configuration
INSTANCE_ID = "i-0974bc14f968e1549"
REGION = "us-east-1"

# Initialize boto3 clients
ec2 = boto3.client('ec2')
cloudwatch = boto3.client('cloudwatch')
pricing = boto3.client('pricing', region_name='us-east-1')
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

def format_bytes(bytes_value):
    """Format bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.2f} PB"

def format_datetime(dt):
    """Format datetime object to string"""
    if isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return str(dt)

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

def get_instance_info():
    """Get basic instance information"""
    try:
        response = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
        instance = response['Reservations'][0]['Instances'][0]
        launch_time = instance['LaunchTime']
        total_hours = (datetime.now(timezone.utc) - launch_time).total_seconds() / 3600
        
        return {
            'state': instance['State']['Name'],
            'type': instance['InstanceType'],
            'launch_time': launch_time,
            'total_hours': total_hours,
            'platform': instance.get('Platform', 'Linux'),
            'architecture': instance['Architecture'],
            'start_date': launch_time
        }
    except Exception as e:
        console.print(f"[red]Error getting instance info: {str(e)}[/red]")
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
        Layout(name="metrics", ratio=1, size=17),
        Layout(name="volumes", ratio=1, size=10),
    )

    # Split body area into two sections
    layout["body"].split(
        Layout(name="network", ratio=1, size=17),
        Layout(name="security", ratio=1, size=10),
    )

    return layout

def create_metrics_panel(metrics, instance_info):
    """Create a panel showing instance metrics and info."""
    metrics_table = Table(show_header=False, box=box.ROUNDED)
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Value", style="white")
    
    # Instance Info
    status_color = {
        'running': 'green',
        'stopped': 'red',
        'pending': 'yellow',
        'stopping': 'yellow',
    }.get(instance_info['state'], 'white')
    
    metrics_table.add_row("Status", f"[{status_color}]{instance_info['state']}[/{status_color}]")
    metrics_table.add_row("Type", instance_info['type'])
    metrics_table.add_row("Launch Time", format_datetime(instance_info['launch_time']))
    metrics_table.add_row("Uptime", f"{instance_info['total_hours']:.1f} hours")
    
    # Performance Metrics
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
        
        for rule in sg['outbound_rules']:
            ports = f"{rule.get('FromPort', 'All')} - {rule.get('ToPort', 'All')}"
            protocol = rule.get('IpProtocol', 'All')
            for ip_range in rule.get('IpRanges', []):
                outbound.add(f"{protocol.upper()} {ports} to {ip_range['CidrIp']}")
    
    return Panel(sg_tree, title="[b]Security Groups", border_style="red")

def create_footer_panel(instance_status):
    """Create a panel showing instance status and system checks."""
    if not instance_status:
        return Panel("No status information available", title="[b]Instance Status", border_style="yellow")
    
    status_table = Table(show_header=False, box=box.ROUNDED)
    status_table.add_column("Check", style="cyan")
    status_table.add_column("Status", style="white")
    
    # Add system status with appropriate color
    system_color = "green" if instance_status['system_status'] == "ok" else "red"
    status_table.add_row(
        "System Status",
        f"[{system_color}]{instance_status['system_status'].upper()}[/{system_color}]"
    )
    
    # Add instance status with appropriate color
    instance_color = "green" if instance_status['instance_status'] == "ok" else "red"
    status_table.add_row(
        "Instance Status",
        f"[{instance_color}]{instance_status['instance_status'].upper()}[/{instance_color}]"
    )
    
    # Add any additional status details
    for detail in instance_status['system_details']:
        status_table.add_row(
            f"System {detail['Name']}",
            detail['Status']
        )
    
    for detail in instance_status['instance_details']:
        status_table.add_row(
            f"Instance {detail['Name']}",
            detail['Status']
        )
    
    return Panel(status_table, title="[b]System Status", border_style="yellow")

def monitor_instance(instance_id: str):
    """Main function to monitor the instance with live updates."""
    try:
        layout = make_layout()
        layout["header"].update(HeaderWidget(instance_id))

        with Live(layout, refresh_per_second=1, screen=True):
            while True:
                try:
                    # Get all instance information
                    instance_info = get_instance_info()
                    if not instance_info:
                        raise Exception("Failed to get instance information")
                    
                    metrics = get_instance_metrics(instance_id)
                    volumes = get_volume_info(instance_id)
                    network_interfaces = get_network_interfaces(instance_id)
                    security_groups = get_security_groups(instance_id)
                    instance_status = get_instance_status(instance_id)

                    # Update all panels
                    layout["metrics"].update(create_metrics_panel(metrics, instance_info))
                    layout["volumes"].update(create_volumes_panel(volumes))
                    layout["network"].update(create_network_panel(network_interfaces))
                    layout["security"].update(create_security_panel(security_groups))
                    layout["footer"].update(create_footer_panel(instance_status))

                    # Sleep for a short duration to prevent API throttling
                    time.sleep(2)

                except Exception as e:
                    error_panel = Panel(
                        f"[red]Error updating dashboard: {str(e)}[/red]\n"
                        "[yellow]Retrying in 5 seconds...[/yellow]",
                        title="[b]Error",
                        border_style="red"
                    )
                    layout["footer"].update(error_panel)
                    time.sleep(5)

    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Fatal error: {str(e)}[/red]")
        sys.exit(1)

def main():
    """Main entry point for the application."""
    console.print("[blue]AWS Instance Monitor[/blue]")
    console.print(f"Monitoring instance: [green]{INSTANCE_ID}[/green]")
    console.print("Press Ctrl+C to exit\n")
    
    try:
        # Verify AWS credentials and instance access
        ec2.describe_instances(InstanceIds=[INSTANCE_ID])
        monitor_instance(INSTANCE_ID)
    except ClientError as e:
        if e.response['Error']['Code'] == 'UnauthorizedOperation':
            console.print("[red]Error: Invalid AWS credentials or insufficient permissions[/red]")
        elif e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
            console.print(f"[red]Error: Instance {INSTANCE_ID} not found[/red]")
        else:
            console.print(f"[red]AWS Error: {str(e)}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    main()
