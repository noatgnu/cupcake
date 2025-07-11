"""
Django management command to run the MCP SDRF server.

This command starts the MCP server integrated with Django.
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import asyncio
import sys
from pathlib import Path

# Add the mcp_server to Python path
mcp_server_path = Path(settings.BASE_DIR) / 'mcp_server'
sys.path.insert(0, str(mcp_server_path))

from mcp_server.server import MCPSDRFServer


class Command(BaseCommand):
    """Django management command for MCP server."""
    
    help = 'Run the MCP SDRF Protocol Annotator Server'
    
    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument(
            '--transport',
            choices=['stdio', 'websocket'],
            default='stdio',
            help='Transport type for MCP server (default: stdio)'
        )
        parser.add_argument(
            '--port',
            type=int,
            default=8000,
            help='Port for WebSocket transport (default: 8000)'
        )
        parser.add_argument(
            '--host',
            default='localhost',
            help='Host for WebSocket transport (default: localhost)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose logging'
        )
    
    def handle(self, *args, **options):
        """Handle the command execution."""
        # Configure logging
        if options['verbose']:
            import logging
            logging.basicConfig(level=logging.DEBUG)
            self.stdout.write("Verbose logging enabled")
        
        transport = options['transport']
        
        self.stdout.write(f"Starting MCP SDRF Server...")
        self.stdout.write(f"Transport: {transport}")
        
        if transport == "websocket":
            self.stdout.write(f"Host: {options['host']}")
            self.stdout.write(f"Port: {options['port']}")
            self.stdout.write("WebSocket transport not yet implemented. Using stdio.")
            transport = "stdio"
        
        self.stdout.write("Server is ready. Use Ctrl+C to stop.")
        
        try:
            # Run the server
            asyncio.run(self._run_server(transport))
        except KeyboardInterrupt:
            self.stdout.write("\nServer stopped by user.")
        except Exception as e:
            self.stderr.write(f"Server error: {e}")
            sys.exit(1)
    
    async def _run_server(self, transport_type):
        """Run the MCP server asynchronously."""
        server = MCPSDRFServer()
        await server.run(transport_type=transport_type)