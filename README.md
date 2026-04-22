# Config Analyzer Backend

The Config Analyzer Backend is a FastAPI-based service designed to analyze network device configurations (firewalls, routers, switches) and provide cross-vendor translation and AI-driven security auditing. It is a core component of the Defense Halo architecture.

## Overview

This service exposes a REST API that accepts raw configuration files or network topology graphs and utilizes LLMs (Large Language Models) to extract intent, generate equivalent configurations for different vendors, and perform security audits against industry best practices.

## Features

- **Security Audit:** Analyzes configurations to identify security risks, missing best practices, and potential misconfigurations.
- **Cross-Vendor Translation:** Translates firewall policies and network configurations between different vendor formats (e.g., Cisco ASA to Palo Alto, Check Point to Fortinet).
- **Network Graph Analysis:** Processes topological graph data to understand network segmentation and security posture.
- **Hot-Reload Development:** Configured with Uvicorn for seamless local development.

## Project Structure

```
config-analyzer-backend/
├── app/
│   ├── api/          # API routers and endpoints (v1)
│   ├── core/         # Application settings and configurations (config.py)
│   ├── prompts/      # System prompts and templates for LLM interactions
│   ├── services/     # Business logic and external service integrations (LLM calls)
│   ├── utils/        # Helper functions
│   └── main.py       # FastAPI application initialization
├── .env.example      # Example environment variables
├── .gitlab-ci.yml    # CI/CD pipeline configuration
├── Dockerfile        # Containerization instructions
├── dev.sh            # Development startup script
└── requirements.txt  # Python dependencies
```

## Setup & Local Development

### Prerequisites
- Python 3.11+
- Virtual Environment (`venv`)

### 1. Environment Configuration

Copy the example environment file and configure the necessary variables:

```bash
cp .env.example .env
```

Ensure you set the required LLM endpoints or API keys in the `.env` file (e.g., `VLLM_HOST`, `MODEL_NAME`).

### 2. Local Setup (Using `dev.sh`)

The provided `dev.sh` script automates the creation of the virtual environment, dependency installation, and server startup.

```bash
# Make the script executable if necessary
chmod +x dev.sh

# Run the development server
./dev.sh
```

Alternatively, you can set it up manually:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

The API will be available at `http://localhost:8010/v1`. You can access the interactive API documentation at `http://localhost:8010/docs`.

## Docker & Production Deployment

The service is containerized for deployment.

### Building the Image

```bash
docker build -t config-analyzer-backend .
```

### Running the Container

```bash
docker run -d -p 8010:8010 --env-file .env config-analyzer-backend
```

*Note: For production deployments, it is recommended to use Gunicorn to manage Uvicorn workers. Ensure the deployment manifests or CI/CD pipelines are configured accordingly.*

## CI/CD Pipeline

The project includes a `.gitlab-ci.yml` file configured to use standard container building templates. It builds the Docker image and publishes it to the designated container registry upon push.

```yaml
variables:
  CONTAINER_BUILD_NAME: $CI_PROJECT_NAME
  PLATFORM: "linux/amd64"
  CI_APPLICATION_REPOSITORY: $CI_REGISTRY_IMAGE
  ...
```
