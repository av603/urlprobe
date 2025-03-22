# URL Probe

[![Test Status](https://github.com/av603/urlprobe/actions/workflows/test.yml/badge.svg)](https://github.com/av603/urlprobe/actions/workflows/test.yml)
[![Code Coverage](https://codecov.io/gh/av603/urlprobe/branch/main/graph/badge.svg)](https://codecov.io/gh/av603/urlprobe)

This tool helps test complex cloud network setups, like those with private services that have specific exit points. It's especially useful for checking if your cloud services can talk to each other within a virtual private cloud and those services can make requests to the outside world as expected.

**Use Case** Say you have a Cloud Load Balancer, two Cloud Run services (Service A and Service B) and a Cloud Subnetwork with a static egress IP. You have deployed this infrastructure and want to verify that the Cloud Load Balancer can access Service A, that Service A can access Service B and that requests from Service B appear from the subnetwork static egress IP.

```
    Internet
        |
        |
    +-------+
    |       |
    | Cloud |
    |  Run  |  (A) - Publicly Accessible
    +-------+
        | (Target URL Parameter)
        |
        v (Internal Network Traffic)
    +-------+
    |       |
    | Cloud |
    |  Run  |  (B) - Internal Service
    +-------+
        | (Outbound Request via Static IP)
        |
        v
    +---------------+
    | External      |
    | Target Server |
    +---------------+
```

The network connectivity and the public IP can be verified by deploying the `urlprobe` tool to Service A and Service B and sending a chained `curl` request to the exposed service and requesting the public IP from `https://api.ipify.org` as the last step in the chain. For example, if the network is configured as per this use case, a `curl` request:

```bash
curl -s http://external-cloud-run-service-a-ip/?url=http://internal-cloud-run-service-b-ip/?url=https://api.ipify.org?format=json
```

will be received at Service A, then at Service B and finally at `https://api.ipify.org` will return the public IP.

## Installation

The `urlprobe` tool is available on PiPy and can be installed via pip:

1.  **Install Python 3.10+:** Ensure you have Python 3.10 or a later version installed.
2.  **Install the package from PyPI using pip:**
```bash
pip install urlprobe
```
3.  **(optional) Install the package from TestPyPI using pip:**
```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ urlprobe
```

How you deploy the `urlprobe` tool depends on the type of infrastructure under test e.g. packaged as a `Docker` image or deployed as a cloud function.

## Usage

### Running as a standalone application

1.  **Run the server:**
```bash
python -m urlprobe
```

**(optionally) run the server with non-default args**
```bash
python -m urlprobe --host 0.0.0.0 --port 8081 --debug
```

2.  **Send a GET request to the server with the `url` parameter:**
```bash
curl -s "http://<edge-service-ip>:8080/?url=https://<internal-service-ip>"
```

Replace `<edge-service-ip>` with the IP address or hostname of your externally accessible edge service. For example, when running as a standalone application on localhost:

```bash
curl -s "http://localhost:8080/?url=https://api.ipify.org?format=json"
```

## Output

The server will return a JSON object containing detailed information the request chain, including:

* **Edge Service Response:** Status code, headers, and body from the target service."
* **Error Messages:** Detailed error messages for any failures encountered during the request chain.

## Contributing

Please see [Contributing Guidelines](https://github.com/av603/urlprobe/blob/main/CONTRIBUTING.md) for details on:

- Setting up your development environment
- Code style and standards
- Pull request process
- Running tests

# Versioning

This project follows [Semantic Versioning](https://semver.org/). For the versions available, see the [tags on this repository](https://github.com/av603/urlprobe/tags).

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/av603/urlprobe/blob/main/LICENSE) file for details.
