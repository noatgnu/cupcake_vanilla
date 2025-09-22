#!/usr/bin/env python3
"""
Independent py-pglite database startup script for Cupcake Vanilla.

This script starts a py-pglite PostgreSQL instance without relying on
Django settings. It can be used to start the database before running
Django or as a standalone process.

Usage:
    python start_pglite.py [options]

Options:
    --data-dir PATH     Database data directory (default: ./pglite_data)
    --port PORT         TCP port to bind to (default: 55432)
    --host HOST         Host to bind to (default: 127.0.0.1)
    --daemon           Run as daemon process
    --stop             Stop running py-pglite instance
    --status           Check if py-pglite is running
    --verbose          Enable verbose logging
"""

import argparse
import atexit
import os
import signal
import socket
import sys
import time
from pathlib import Path


class PGLiteManager:
    """Independent py-pglite database manager."""

    def __init__(self, data_dir=None, host="127.0.0.1", port=55432, verbose=False):
        """
        Initialize PGLite manager.

        Args:
            data_dir: Database data directory
            host: Host to bind to
            port: Port to bind to
            verbose: Enable verbose logging
        """
        self.data_dir = Path(data_dir or "./pglite_data").resolve()
        self.host = host
        self.port = port
        self.verbose = verbose
        self.process = None
        self.pid_file = self.data_dir / "pglite.pid"
        self.log_file = self.data_dir / "pglite.log"

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, message):
        """Log message if verbose mode is enabled."""
        if self.verbose:
            print(f"[PGLite] {message}")

    def _check_dependencies(self):
        """Check if py-pglite is installed."""
        try:
            import py_pglite  # noqa: F401

            return True
        except ImportError:
            print("Error: py-pglite is not installed. " "Install with: pip install py-pglite[django]")
            return False

    def _is_port_in_use(self):
        """Check if the specified port is already in use."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((self.host, self.port))
                return result == 0
        except Exception:
            return False

    def _get_running_pid(self):
        """Get PID of running py-pglite process."""
        if not self.pid_file.exists():
            return None

        try:
            with open(self.pid_file, "r") as f:
                pid = int(f.read().strip())

            # Check if process is actually running
            try:
                os.kill(pid, 0)  # Send signal 0 to check if process exists
                return pid
            except (OSError, ProcessLookupError):
                # Process doesn't exist, remove stale PID file
                self.pid_file.unlink()
                return None
        except (ValueError, FileNotFoundError):
            return None

    def _write_pid_file(self, pid):
        """Write PID to file."""
        with open(self.pid_file, "w") as f:
            f.write(str(pid))

    def _remove_pid_file(self):
        """Remove PID file."""
        if self.pid_file.exists():
            self.pid_file.unlink()

    def is_running(self):
        """Check if py-pglite is running."""
        # Check if port is in use
        if not self._is_port_in_use():
            return False

        # Check if our PID file exists and process is running
        pid = self._get_running_pid()
        return pid is not None

    def test_connection(self, timeout=30):
        """Test if py-pglite is accessible and ready for connections."""
        if not self._is_port_in_use():
            return False

        try:
            import psycopg2

            self._log(f"Testing connection to py-pglite on {self.host}:{self.port}")

            for attempt in range(timeout):
                try:
                    self._log(f"Connection attempt {attempt + 1}/{timeout}")
                    conn = psycopg2.connect(
                        host=self.host,
                        port=self.port,
                        database="postgres",
                        user="postgres",
                        password="postgres",
                        connect_timeout=5,
                        sslmode="disable",
                    )
                    # Test a simple query and ensure database exists
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        result = cursor.fetchone()
                        self._log(f"Query result: {result}")

                        # Try to create cupcake_vanilla database if it doesn't exist
                        try:
                            cursor.execute("CREATE DATABASE cupcake_vanilla")
                            self._log("Created cupcake_vanilla database")
                        except psycopg2.Error as e:
                            if "already exists" in str(e):
                                self._log("cupcake_vanilla database already exists")
                            else:
                                self._log(f"Database creation note: {e}")

                    conn.close()
                    self._log("Connection test successful")
                    return True
                except (psycopg2.OperationalError, psycopg2.DatabaseError) as e:
                    self._log(f"Connection attempt {attempt + 1} failed: {e}")
                    if attempt < timeout - 1:
                        time.sleep(2)  # Increased wait time between attempts
                        continue
                    return False
                except Exception as e:
                    self._log(f"Unexpected error during connection test: {e}")
                    if attempt < timeout - 1:
                        time.sleep(2)
                        continue
                    return False
        except ImportError:
            self._log("psycopg2 not available, just checking port")
            return self._is_port_in_use()

        return False

    def start(self, daemon=False):
        """
        Start py-pglite database.

        Args:
            daemon: Run as daemon process

        Returns:
            bool: True if started successfully, False otherwise
        """
        if not self._check_dependencies():
            return False

        # Check if already running
        if self.is_running():
            print(f"py-pglite is already running on {self.host}:{self.port}")
            return True

        # Check if port is in use by another process
        if self._is_port_in_use():
            print(f"Error: Port {self.port} is already in use by another " "process")
            return False

        self._log("Starting py-pglite database...")
        self._log(f"Data directory: {self.data_dir}")
        self._log(f"Host: {self.host}")
        self._log(f"Port: {self.port}")

        try:
            from py_pglite import PGliteConfig

            # Configure py-pglite
            config = PGliteConfig(
                work_dir=str(self.data_dir),
                use_tcp=True,
                tcp_host=self.host,
                tcp_port=self.port,
                extensions=[],
            )

            if daemon:
                # Start as daemon process
                return self._start_daemon(config)
            else:
                # Start in foreground
                return self._start_foreground(config)

        except Exception as e:
            print(f"Error starting py-pglite: {e}")
            return False

    def _start_foreground(self, config):
        """Start py-pglite in foreground."""
        try:
            from py_pglite import PGliteManager

            self._log("Starting py-pglite in foreground mode...")

            # Create manager and start
            manager = PGliteManager(config)
            manager.__enter__()

            # Write PID file
            self._write_pid_file(os.getpid())

            # Register cleanup handlers
            def cleanup():
                self._log("Shutting down py-pglite...")
                try:
                    manager.__exit__(None, None, None)
                except Exception as e:
                    self._log(f"Error during shutdown: {e}")
                finally:
                    self._remove_pid_file()

            atexit.register(cleanup)
            signal.signal(signal.SIGINT, lambda s, f: cleanup() or sys.exit(0))
            signal.signal(signal.SIGTERM, lambda s, f: cleanup() or sys.exit(0))

            print(f"py-pglite started successfully on " f"{self.host}:{self.port}")
            print(f"Data directory: {self.data_dir}")
            print("Press Ctrl+C to stop")

            # Keep running
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

            return True

        except Exception as e:
            print(f"Error starting py-pglite: {e}")
            return False

    def _start_daemon(self, config):
        """Start py-pglite as daemon process."""
        try:
            # Fork to create daemon
            pid = os.fork()
            if pid > 0:
                # Parent process - wait a moment for daemon to start
                time.sleep(2)

                # Check if daemon actually started successfully
                for _ in range(10):  # Wait up to 10 seconds
                    if self._is_port_in_use():
                        print(f"py-pglite daemon started successfully with PID {pid}")
                        return True
                    time.sleep(1)

                print(f"py-pglite daemon started with PID {pid} but port not accessible")
                return False

            # Child process - become daemon
            os.setsid()
            os.chdir("/")
            os.umask(0)

            # Redirect standard file descriptors
            with open(os.devnull, "r") as dev_null:
                os.dup2(dev_null.fileno(), sys.stdin.fileno())

            with open(self.log_file, "a") as log_file:
                os.dup2(log_file.fileno(), sys.stdout.fileno())
                os.dup2(log_file.fileno(), sys.stderr.fileno())

            # Start py-pglite in daemon
            from py_pglite import PGliteManager

            # Write PID file early
            self._write_pid_file(os.getpid())

            try:
                manager = PGliteManager(config)
                manager.__enter__()

                # Log successful startup
                with open(self.log_file, "a") as f:
                    f.write(f"py-pglite manager started successfully on {self.host}:{self.port}\n")
                    f.flush()
            except Exception as e:
                # Log startup error
                with open(self.log_file, "a") as f:
                    f.write(f"Failed to start py-pglite manager: {e}\n")
                    f.flush()
                raise

            # Register cleanup
            def cleanup():
                try:
                    manager.__exit__(None, None, None)
                except Exception:
                    pass
                finally:
                    self._remove_pid_file()

            atexit.register(cleanup)
            signal.signal(signal.SIGTERM, lambda s, f: cleanup() or sys.exit(0))

            # Keep daemon running
            while True:
                time.sleep(1)

        except OSError as e:
            print(f"Error forking daemon: {e}")
            return False
        except Exception as e:
            print(f"Error in daemon: {e}")
            self._remove_pid_file()
            return False

    def stop(self):
        """
        Stop py-pglite database.

        Returns:
            bool: True if stopped successfully, False otherwise
        """
        if not self.is_running():
            print("py-pglite is not running")
            return True

        pid = self._get_running_pid()
        if not pid:
            print("Could not find py-pglite process")
            return False

        self._log(f"Stopping py-pglite process {pid}...")

        try:
            # Send SIGTERM to gracefully stop
            os.kill(pid, signal.SIGTERM)

            # Wait for process to stop
            for _ in range(30):  # Wait up to 30 seconds
                try:
                    os.kill(pid, 0)
                    time.sleep(1)
                except (OSError, ProcessLookupError):
                    break
            else:
                # Force kill if still running
                self._log("Force killing py-pglite process...")
                os.kill(pid, signal.SIGKILL)

            self._remove_pid_file()
            print("py-pglite stopped successfully")
            return True

        except (OSError, ProcessLookupError):
            # Process already stopped
            self._remove_pid_file()
            print("py-pglite stopped")
            return True
        except Exception as e:
            print(f"Error stopping py-pglite: {e}")
            return False

    def status(self):
        """
        Check and display py-pglite status.

        Returns:
            bool: True if running, False otherwise
        """
        if self.is_running():
            pid = self._get_running_pid()
            print(f"py-pglite is running on {self.host}:{self.port}")
            if pid:
                print(f"Process ID: {pid}")
            print(f"Data directory: {self.data_dir}")
            return True
        else:
            print("py-pglite is not running")
            return False

    def get_connection_info(self):
        """Get database connection information."""
        return {
            "host": self.host,
            "port": self.port,
            "database": "postgres",
            "user": "postgres",
            "password": "postgres",
            "connection_string": (f"postgresql://postgres:postgres@" f"{self.host}:{self.port}/postgres"),
            "data_directory": str(self.data_dir),
        }


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Independent py-pglite database manager for " "Cupcake Vanilla",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--data-dir", default=None, help="Database data directory " "(default: ./pglite_data)")
    parser.add_argument("--port", type=int, default=55432, help="TCP port to bind to (default: 55432)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon process")
    parser.add_argument("--stop", action="store_true", help="Stop running py-pglite instance")
    parser.add_argument("--status", action="store_true", help="Check if py-pglite is running")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--connection-info", action="store_true", help="Display connection information")
    parser.add_argument("--test-connection", action="store_true", help="Test database connection")

    args = parser.parse_args()

    # Use default data directory if not specified
    if args.data_dir is None:
        # Try to use Electron app data directory if available
        electron_app_data = os.environ.get("ELECTRON_APP_DATA")
        if electron_app_data:
            args.data_dir = os.path.join(electron_app_data, "cupcake-vanilla", "database")
        else:
            args.data_dir = "./pglite_data"

    # Create manager
    manager = PGLiteManager(data_dir=args.data_dir, host=args.host, port=args.port, verbose=args.verbose)

    # Execute requested action
    if args.stop:
        success = manager.stop()
        sys.exit(0 if success else 1)
    elif args.status:
        is_running = manager.status()
        sys.exit(0 if is_running else 1)
    elif args.connection_info:
        info = manager.get_connection_info()
        print("Connection Information:")
        print(f"  Host: {info['host']}")
        print(f"  Port: {info['port']}")
        print(f"  Database: {info['database']}")
        print(f"  User: {info['user']}")
        print(f"  Password: {info['password']}")
        print(f"  Connection String: {info['connection_string']}")
        print(f"  Data Directory: {info['data_directory']}")
        sys.exit(0)
    elif args.test_connection:
        if manager.test_connection():
            print("Connection test successful")
            sys.exit(0)
        else:
            print("Connection test failed")
            sys.exit(1)
    else:
        # Start database
        success = manager.start(daemon=args.daemon)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
