import subprocess
import os.path
import re
import json
import requests
import tempfile
import ai2thor._builds
import shlex

def pci_records():
    records = []
    command = shlex.split('lspci -vmm')
    output = subprocess.check_output(command).decode()

    for devices in output.strip().split("\n\n"):
        record = {}
        records.append(record)
        for row in devices.split("\n"):
            key, value = row.split("\t")
            record[key.split(':')[0]] = value

    return records

def xorg_bus_id():
    bus_id = None
    for r in pci_records():
        if r.get('Vendor', '') == 'NVIDIA Corporation'\
                and r['Class'] in ['VGA compatible controller', '3D controller']:
            bus_id = 'PCI:' + ':'.join(map(lambda x: str(int(x, 16)), re.split(r'[:\.]', r['Slot'])))
            break

    if bus_id is None:
        raise Exception("no valid nvidia device could be found")

    return bus_id

def has_docker():
    return subprocess.call(['which', 'docker']) == 0


def bridge_gateway():
    output = subprocess.check_output("docker network inspect -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' bridge", shell=True).decode('ascii').strip()
    if re.match(r'^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$', output):
        return output
    else:
        raise Exception("Didn't receive a single ip address from network inspect bridge: %s" % output)


def nvidia_version():
    version = None
    version_path = '/proc/driver/nvidia/version'
    if os.path.isfile(version_path):
        with open(version_path) as f:
            for line in f:
                if line.startswith('NVRM version: NVIDIA'):
                    match = re.search(r'Kernel Module\s+([0-9\.]+)\s+', line)
                    if match:
                        version = match.group(1)
                        break
    return version


def generate_dockerfile(tag):

    driver_url = 'http://us.download.nvidia.com/XFree86/Linux-x86_64/{version}/NVIDIA-Linux-x86_64-{version}.run'.format(version=nvidia_version())
    driver_filename = os.path.basename(driver_url)

    dockerfile = """
FROM ai2thor/ai2thor-base:{tag}
RUN wget -q {driver_url} -P /root/
RUN sh /root/{driver_filename} -s --no-kernel-module
""".format(driver_filename=driver_filename, driver_url=driver_url, tag=tag)

    return dockerfile


def image_exists(image_name):
    output = subprocess.check_output("docker images -q %s" % image_name, shell=True)
    return len(output) > 0


def run(image_name, environment):
    environment_string = ""
    for k,v in environment.items():
        environment_string += " -e %s=%s " % (k,v)

    environment_string += " -e %s=%s " % ("AI2THOR_DEVICE_BUSID", xorg_bus_id())
    command = "docker run -d --privileged {environment} {image_name} /root/start.sh".format(environment=environment_string, image_name=image_name)
    container_id = subprocess.check_output(command, shell=True).decode('ascii').strip()
    return container_id


def kill_container(container_id):
    subprocess.check_output("docker kill %s" % container_id, shell=True)


def build_image():

    version = nvidia_version()
    tag = ai2thor._builds.BUILDS['Docker']['tag']
    image_name = 'ai2thor/ai2thor-nvidia-%s:%s' % (version, tag)

    if image_exists(image_name):
        return image_name

    tf = tempfile.NamedTemporaryFile(mode="w", delete=False)
    tf.write(generate_dockerfile(tag))
    tf.close()

    subprocess.check_call("docker build --rm -t %s -f %s ." % (image_name, tf.name), shell=True)

    os.unlink(tf.name)

    return image_name
