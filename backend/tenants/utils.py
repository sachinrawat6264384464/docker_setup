import os
import platform
import logging

logger = logging.getLogger(__name__)

def update_hosts_file(domain, action='add'):
    """
    Update the local hosts file to include the tenant domain.
    Requires administrator privileges on Windows.
    """
    if not domain:
        return False

    # Skip for real domains, only process localhost-based domains
    if not (domain.endswith('.localhost') or domain == 'localhost'):
        # If it's a real domain (like hoaconnecthub.com), we don't touch hosts file
        # because it should be handled by DNS.
        return False

    system = platform.system()
    if system == 'Windows':
        hosts_path = r'C:\Windows\System32\drivers\etc\hosts'
    else:
        hosts_path = '/etc/hosts'

    ip_address = '127.0.0.1'
    entry = f"{ip_address}  {domain}\n"

    try:
        if not os.path.exists(hosts_path):
            logger.error(f"Hosts file not found at {hosts_path}")
            return False

        with open(hosts_path, 'r') as f:
            lines = f.readlines()

        if action == 'add':
            # Check if already exists
            if any(domain in line for line in lines):
                logger.info(f"Domain {domain} already exists in hosts file.")
                return True
            
            # Add entry
            try:
                with open(hosts_path, 'a') as f:
                    # Ensure there's a newline before adding
                    if lines and not lines[-1].endswith('\n'):
                        f.write('\n')
                    f.write(entry)
                logger.info(f"Added {domain} to hosts file.")
                return True
            except PermissionError:
                logger.warning(f"Permission denied while writing to {hosts_path}. Run as Administrator.")
                return False

        elif action == 'remove':
            new_lines = [line for line in lines if domain not in line]
            if len(new_lines) == len(lines):
                return True
                
            try:
                with open(hosts_path, 'w') as f:
                    f.writelines(new_lines)
                logger.info(f"Removed {domain} from hosts file.")
                return True
            except PermissionError:
                logger.warning(f"Permission denied while writing to {hosts_path}. Run as Administrator.")
                return False

    except Exception as e:
        logger.error(f"Failed to update hosts file: {e}")
        return False
