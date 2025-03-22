"""
Command-line entry point for the urlprobe Flask application.

This script parses command-line arguments for configuring the host,
port, and debug mode of the urlprobe web service and then starts
the Flask development server.
"""

import argparse

from urlprobe.app import create_app, logger


def main():
    """Entry point for the urlprobe Flask application."""
    parser = argparse.ArgumentParser(
        description="Run the urlprobe application."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="The interface to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="The port to listen on (default: 8080)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug mode (default: False)",
    )
    args = parser.parse_args()

    app = create_app()

    logger.info(
        f"Starting urlprobe on host {args.host}, port {args.port}, "
        f"debug={args.debug}"
    )
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
