# PostgreSQL MCP Server

A PostgreSQL MCP server implementation using the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) Python SDK- an open protocol that enables seamless integration between LLM applications and external data sources. This server allows AI agents to interact with PostgreSQL databases through a standardized interface.

## Features

- List database schemas
- List tables within schemas
- Describe table structures
- List table constraints and relationships
- Get foreign key information
- Execute SQL queries

## Prerequisites

- Python 3.x
- PostgreSQL database server
- Access to a PostgreSQL database

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd mcp-postgres
```

2. Create and activate a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Start the MCP server by providing your PostgreSQL connection string:
```bash
python postgres_server.py "postgresql://username:password@host:port/database"
```

2. The server provides the following tools:

- `query`: Execute SQL queries against the database
- `list_schemas`: List all available schemas
- `list_tables`: List all tables in a specific schema
- `describe_table`: Get detailed information about a table's structure
- `get_foreign_keys`: Get foreign key relationships for a table
- `find_relationships`: Discover both explicit and implied relationships for a table

### Configuration with mcp.json

To integrate this server with MCP-compatible tools (like Cursor), add it to your `~/.cursor/mcp.json`:

```json
{
  "servers": {
    "postgres": {
      "command": "/path/to/venv/bin/python",
      "args": [
        "/path/to/postgres_server.py",
        "postgresql://username:password@host:5432/database?ssl=true"
      ]
    }
  }
}
```

Replace:
- `/path/to/venv` with your virtual environment path
- `/path/to/postgres_server.py` with the absolute path to the server script
- Connection string with your PostgreSQL database credentials

Note: Make sure to properly secure your `mcp.json` file as it contains sensitive database credentials.

## Security

- Never expose sensitive database credentials in your code
- Use environment variables or secure configuration files for database connection strings
- Consider using connection pooling for better resource management
- Implement proper access controls and user authentication

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Related Projects

- [MCP Specification](https://github.com/modelcontextprotocol/specification)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Servers](https://github.com/modelcontextprotocol/servers)

## License

MIT License

Copyright (c) 2025 gldc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE. 