import subprocess

def get_public_ip():
    try:
        result = subprocess.run(
            ["aws", "ec2", "describe-instances",
             "--query", "Reservations[*].Instances[*].PublicIpAddress",
             "--output", "text"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            print("Error retrieving public IP address:", result.stderr)
            return None

        ip_addresses = result.stdout.strip().split()
        if ip_addresses:
            return ip_addresses[0]
        else:
            print("No public IP addresses found.")
            return None
    except Exception as e:
        print("An error occurred:", e)
        return None

def ssh_to_instance(ip_address):
    ssh_command = f"ssh -i windows-server-aws.pem -o StrictHostKeyChecking=no ubuntu@{ip_address}"
    print("Executing SSH command:", ssh_command)

    try:
        subprocess.run(ssh_command, shell=True)
    except Exception as e:
        print("An error occurred while trying to SSH:", e)

if __name__ == "__main__":
    ip_address = get_public_ip()
    if ip_address:
        ssh_to_instance(ip_address)
